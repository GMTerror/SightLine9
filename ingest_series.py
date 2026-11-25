"""Ingest one series into local/sightline.sqlite by streaming .zst files (nothing is decompressed to disk).

Requires Python 3.14+ (compression.zstd).
"""
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from compression import zstd

def _load_env(path=Path(__file__).parent / ".env"):
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


_load_env()

DATA_ROOT = Path(os.environ.get(
    "SIGHTLINE_DATA_ROOT", "./data"))
DB_PATH = Path(__file__).parent / "local" / "sightline.sqlite"

# Cast-to-kill windows in seconds; cast_outcomes holds one row per live cast per window (window_s column).
WINDOW_S = (5, 10, 15)

SCHEMA = """
DROP TABLE IF EXISTS casts;
DROP TABLE IF EXISTS kills;
DROP TABLE IF EXISTS games;
DROP TABLE IF EXISTS rounds;
DROP TABLE IF EXISTS cast_outcomes;
CREATE TABLE casts (
    series_id TEXT, game_id TEXT, round_number INTEGER, player_id TEXT, team_id TEXT,
    ability TEXT, cast_time TEXT, pos_x REAL, pos_y REAL, pos_z REAL,
    view_x REAL, view_y REAL, view_z REAL, quality TEXT, side_at_cast TEXT,
    weight REAL, is_live INTEGER
);
CREATE TABLE kills (
    series_id TEXT, game_id TEXT, round_number INTEGER, time TEXT,
    killer_id TEXT, victim_id TEXT, first_kill INTEGER,
    killer_team_id TEXT, victim_team_id TEXT, is_valid_kill INTEGER
);
CREATE TABLE cast_outcomes (
    cast_id INTEGER, window_s INTEGER, caster_got_kill INTEGER, teammate_got_kill INTEGER,
    caster_died INTEGER, enemy_got_kill_on_team INTEGER
);
CREATE TABLE games (
    series_id TEXT, game_id TEXT, game_number INTEGER, map_name TEXT
);
CREATE TABLE rounds (
    series_id TEXT, game_id TEXT, round_number INTEGER, start_time TEXT,
    freezetime_end_time TEXT, end_time TEXT, winner_team_id TEXT
);
"""

ROUND_EVENTS = ("game-started-round", "round-ended-freezetime", "game-ended-round", "team-won-round")


def _jsonl(path):
    with zstd.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def _round_event(base, actor, target, current_game):
    """Returns (game_id, round_number) the round event refers to."""
    if base == "game-started-round":
        return actor["id"], target["state"]["sequenceNumber"]
    if base == "game-ended-round":
        return actor["id"], actor["stateDelta"]["segments"][0]["sequenceNumber"]
    ref = target if base == "team-won-round" else actor
    return current_game, ref["state"]["sequenceNumber"]


def _ts(s):
    return datetime.fromisoformat(s).timestamp()


def _outcomes(casts, kills, windows):
    """Rows for live casts (cast_id = casts rowid). Only valid kills, same game+round, 0 < kill - cast <= window.

    All columns are 'followed by' outcomes, not effects of the cast:
    caster_got_kill: the caster is the killer. teammate_got_kill: a teammate (not the caster) is the killer.
    caster_died: the caster is the victim. enemy_got_kill_on_team: the killer is on the other team and the
    victim is on the caster's team (includes the caster).
    """
    by_round = {}
    for k in kills:
        if k[9]:
            by_round.setdefault((k[1], k[2]), []).append((_ts(k[3]), k[4], k[5], k[7], k[8]))
    rows = []
    for i, c in enumerate(casts, start=1):
        if not c[16]:
            continue
        t0, pid, team = _ts(c[6]), c[3], c[4]
        after = [(kt - t0, kr, v, kteam, vteam) for kt, kr, v, kteam, vteam in by_round.get((c[1], c[2]), [])
                 if kt > t0]
        for w in windows:
            hit = [x for x in after if x[0] <= w]
            rows.append((i, w,
                         int(any(x[1] == pid for x in hit)),
                         int(any(x[1] != pid and x[3] == team for x in hit)),
                         int(any(x[2] == pid for x in hit)),
                         int(any(x[3] != team and x[4] == team for x in hit))))
    return rows


def ingest(series_id, db_path=DB_PATH, data_root=DATA_ROOT):
    """Returns a dict of counts."""
    stats = {"supplement_rows": 0, "skipped_gap_exceeded": 0, "skipped_null_interpolated": 0,
             "skipped_not_in_grid": 0, "skipped_other_not_in_feed": 0, "casts": 0, "kills": 0,
             "games": 0, "rounds": 0, "casts_not_live": 0}
    keep = {}
    for c in _jsonl(data_root / "val-ability-supplements" / f"{series_id}.jsonl.zst"):
        stats["supplement_rows"] += 1
        if c.get("quality") == "gap_exceeded":
            stats["skipped_gap_exceeded"] += 1
        elif not c.get("interpolated"):
            stats["skipped_null_interpolated"] += 1
        elif not c.get("in_grid") or not c.get("grid_event_id"):
            stats["skipped_not_in_grid"] += 1
        else:
            keep[c["grid_event_id"]] = c

    casts, kills = [], []
    games = {}
    rounds = {}
    game_id = round_no = None
    for env in _jsonl(data_root / "val" / f"events_{series_id}_grid.jsonl.zst"):
        for e in env["events"]:
            t = e["type"]
            actor, target = e.get("actor") or {}, e.get("target") or {}
            undo = "!" in t
            base = t.replace("!", "")
            if base == "series-started-game" and undo:
                rolled = target.get("id") or actor.get("id")
                games.pop(rolled, None)
                for k in [k for k in rounds if k[0] == rolled]:
                    del rounds[k]
            elif base in ROUND_EVENTS:
                gid, rn = _round_event(base, actor, target, game_id)
                r = rounds.setdefault((gid, rn), {})
                if base == "game-started-round":
                    r["start"] = None if undo else env["occurredAt"]
                    if not undo:
                        gs = actor.get("state") or {}
                        games[gid] = (gs.get("sequenceNumber"), (gs.get("map") or {}).get("name"))
                        game_id, round_no = gid, rn
                elif base == "round-ended-freezetime":
                    r["freeze_end"] = None if undo else env["occurredAt"]
                elif base == "game-ended-round":
                    r["end"] = None if undo else env["occurredAt"]
                else:
                    r["winner"] = None if undo else actor.get("id")
            elif undo:
                continue
            elif t == "player-used-ability" and e["id"] in keep:
                c = keep.pop(e["id"])
                st = actor.get("state") or {}
                ip = c["interpolated"]
                p, v = ip["position"], ip["view"]
                casts.append([series_id, c["game_id"], round_no, c["player_id"], st.get("teamId"),
                              c["ability"], c["occurred_at"], p["x"], p["y"], p["z"],
                              v["x"], v["y"], v["z"], c["quality"], st.get("side"),
                              ip.get("weight"), 0])
            elif t == "player-killed-player":
                fk = ((actor.get("stateDelta") or {}).get("round") or {}).get("firstKill") is True
                kt = (actor.get("state") or {}).get("teamId")
                vt = (target.get("state") or {}).get("teamId")
                valid = int(kt is not None and vt is not None and kt != vt
                            and actor.get("id") != target.get("id"))
                kills.append((series_id, game_id, round_no, env["occurredAt"],
                              actor.get("id"), target.get("id"), int(fk), kt, vt, valid))
    stats["skipped_other_not_in_feed"] = len(keep)

    # is_live: cast_time within [freezetime_end, end] of its round (ISO-8601 UTC strings sort in time order).
    for c in casts:
        r = rounds.get((c[1], c[2])) or {}
        fe, end = r.get("freeze_end"), r.get("end")
        c[16] = int(bool(fe and end and fe <= c[6] <= end))
    stats["casts_not_live"] = sum(1 for c in casts if not c[16])
    games_rows = [(series_id, g, n, m) for g, (n, m) in games.items()]
    rounds_rows = [(series_id, g, n, r.get("start"), r.get("freeze_end"), r.get("end"), r.get("winner"))
                   for (g, n), r in rounds.items()]

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as db:
        db.executescript(SCHEMA)
        db.executemany("INSERT INTO casts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", casts)
        db.executemany("INSERT INTO kills VALUES (?,?,?,?,?,?,?,?,?,?)", kills)
        db.executemany("INSERT INTO cast_outcomes VALUES (?,?,?,?,?,?)", _outcomes(casts, kills, WINDOW_S))
        db.executemany("INSERT INTO games VALUES (?,?,?,?)", games_rows)
        db.executemany("INSERT INTO rounds VALUES (?,?,?,?,?,?,?)", rounds_rows)
    stats["casts"], stats["kills"] = len(casts), len(kills)
    stats["games"], stats["rounds"] = len(games_rows), len(rounds_rows)
    return stats


if __name__ == "__main__":
    print(ingest(sys.argv[1] if len(sys.argv) > 1 else "2748746"))
