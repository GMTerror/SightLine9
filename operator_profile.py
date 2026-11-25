"""Operator tendency profiler + one anti-strat card, across all indexed Cloud9 series (streams GRID .zst feeds).

Weapon identity: inventory.items[].id == "operator" on player objects in seriesState.games[] (current game only).
A player is "on Operator" in a round if any snapshot in that round shows it (user choice: any snapshot).
Early death: the player's valid death is before the median valid-kill time of that round (user choice).
Counter-utility: Cloud9 casts (GRID player-used-ability, cast_id = GRID event id) in the same game and round,
live (cast_time >= freezetime end), and 0 < death_time - cast_time <= WINDOW_S.
All results are "followed by" associations, not effects.

Requires Python 3.14+ (compression.zstd). Run: python operator_profile.py
"""
import csv
import statistics
import sys
from pathlib import Path

from ingest_series import DATA_ROOT, ROUND_EVENTS, _jsonl, _round_event, _ts

WINDOW_S = 10
MIN_N = 3
TEAM_NAMES = ("Cloud9", "Cloud9 GC")
TOP_OPPONENTS = 3


def cloud9(data_root=DATA_ROOT, names=TEAM_NAMES):
    """Returns ({team_id}, [series_id]) using exact team-name matches in meta/teams.csv and val/series.csv."""
    with open(data_root / "meta" / "teams.csv", encoding="utf-8") as f:
        team_ids = {r["team_id"] for r in csv.DictReader(f) if r["title"] == "val" and r["name"] in names}
    with open(data_root / "val" / "series.csv", encoding="utf-8") as f:
        series = [r["series_id"] for r in csv.DictReader(f) if set(names) & set(r["teams"].split(" vs "))]
    return team_ids, series


def valid_games(data_root=DATA_ROOT):
    """game_ids with at least one session_valid=True row in meta/games.csv."""
    with open(data_root / "meta" / "games.csv", encoding="utf-8") as f:
        return {r["game_id"] for r in csv.DictReader(f) if r["title"] == "val" and r["session_valid"] == "True"}


def _new_round(series_id, gid, rn, start):
    return {"series": series_id, "game": gid, "round": rn, "start": start, "freeze_end": None, "end": None,
            "op": set(), "deaths": [], "casts": []}


def scan_series(series_id, data_root=DATA_ROOT):
    """Returns (rounds, players). rounds: list of round dicts; players: {player_id: (name, team_id)}."""
    rounds, players = {}, {}
    game_id = round_no = None
    for env in _jsonl(data_root / "val" / f"events_{series_id}_grid.jsonl.zst"):
        for e in env["events"]:
            t = e["type"]
            actor, target = e.get("actor") or {}, e.get("target") or {}
            undo = "!" in t
            base = t.replace("!", "")
            if base == "series-started-game" and undo:
                rolled = target.get("id") or actor.get("id")
                for k in [k for k in rounds if k[0] == rolled]:
                    del rounds[k]
                continue
            if base in ROUND_EVENTS:
                gid, rn = _round_event(base, actor, target, game_id)
                if base == "game-started-round" and not undo:
                    rounds[(gid, rn)] = _new_round(series_id, gid, rn, env["occurredAt"])  # restart resets
                    game_id, round_no = gid, rn
                r = rounds.get((gid, rn))
                if r is not None and base == "round-ended-freezetime":
                    r["freeze_end"] = None if undo else env["occurredAt"]
                elif r is not None and base == "game-ended-round":
                    r["end"] = None if undo else env["occurredAt"]
            r = rounds.get((game_id, round_no))
            if undo or r is None:
                continue
            for g in (e.get("seriesState") or {}).get("games") or []:
                if g.get("id") != game_id:
                    continue
                for tm in g.get("teams") or []:
                    for p in tm.get("players") or []:
                        if p.get("id") and p.get("name"):
                            players[p["id"]] = (p["name"], tm.get("id"))
                        if any(i.get("id") == "operator" for i in (p.get("inventory") or {}).get("items") or []):
                            r["op"].add(p["id"])
            if t == "player-used-ability":
                r["casts"].append((env["occurredAt"], e["id"], target.get("id"), actor.get("id"),
                                   (actor.get("state") or {}).get("teamId")))
            elif t == "player-killed-player":
                ks, vs = actor.get("state") or {}, target.get("state") or {}
                if ks.get("teamId") and vs.get("teamId") and ks["teamId"] != vs["teamId"] \
                        and actor.get("id") != target.get("id"):
                    r["deaths"].append((env["occurredAt"], actor.get("id"), target.get("id"),
                                        vs.get("teamId"), vs.get("side")))
    return list(rounds.values()), players


def profile(rounds, players, team_ids, player_id=None, window_s=WINDOW_S):
    """Picks the opponent with most Operator rounds (unless player_id given) and ranks Cloud9 counter-utility."""
    team_ids = {team_ids} if isinstance(team_ids, str) else set(team_ids)
    op_rounds = {}
    for r in rounds:
        for pid in r["op"]:
            if players.get(pid, (None, None))[1] not in team_ids | {None}:
                op_rounds.setdefault(pid, []).append(r)
    if player_id is None:
        if not op_rounds:
            return None
        player_id = max(op_rounds, key=lambda p: (len(op_rounds[p]), players[p][0]))
    analyzed, by_ability = [], {}
    for r in op_rounds.get(player_id, []):
        times = [_ts(d[0]) for d in r["deaths"]]
        death = next((d for d in r["deaths"] if d[2] == player_id), None)
        if not death or not r["freeze_end"] or _ts(death[0]) >= statistics.median(times):
            continue
        td = _ts(death[0])
        analyzed.append({"series": r["series"], "game": r["game"], "round": r["round"], "death_time": death[0],
                         "side": death[4]})
        for ct, cid, ability, pid, tid in r["casts"]:
            if tid in team_ids and ct >= r["freeze_end"] and 0 < td - _ts(ct) <= window_s:
                a = by_ability.setdefault(ability, {"rounds": set(), "cast_ids": []})
                a["rounds"].add((r["series"], r["game"], r["round"]))
                a["cast_ids"].append(cid)
    ranked = sorted(((ab, len(v["rounds"]), v["cast_ids"]) for ab, v in by_ability.items()),
                    key=lambda x: (-x[1], -len(x[2]), x[0]))
    return {"player_id": player_id, "name": players.get(player_id, ("?",))[0],
            "op_rounds": len(op_rounds.get(player_id, [])), "analyzed": analyzed, "ranked": ranked,
            "op_round_counts": {players[p][0]: len(v) for p, v in op_rounds.items()},
            "op_round_ids": {p: len(v) for p, v in op_rounds.items()}}


def top_opponents(rounds, players, team_ids, k=TOP_OPPONENTS):
    """Profiles the k opponents with the most Operator rounds (ties broken by name)."""
    p = profile(rounds, players, team_ids)
    if p is None:
        return []
    n = p["op_round_ids"]
    return [profile(rounds, players, team_ids, player_id=pid)
            for pid in sorted(n, key=lambda q: (-n[q], players[q][0]))[:k]]


def card(p, top=3):
    m = len(p["analyzed"])
    sides = {}
    for a in p["analyzed"]:
        sides[a["side"]] = sides.get(a["side"], 0) + 1
    lines = [f"ANTI-STRAT CARD: {p['name']} (Operator)",
             "Side at death: " + ", ".join(f"{s} (n={n})" for s, n in sorted(sides.items(), key=str)),
             f"Operator rounds found: n={p['op_rounds']}; early-death Operator rounds analyzed: M={m}",
             f"Ranked Counter-Utility ({' / '.join(TEAM_NAMES)} casts within {WINDOW_S}s before the death, "
             "live, same round):"]
    for ability, n, cids in p["ranked"][:top]:
        lines.append(f"- {' / '.join(TEAM_NAMES)} {ability} was followed by {p['name']}'s early death in {n} of {m} "
                     f"Operator rounds analyzed (casts n={len(cids)}).")
    if not p["ranked"] or p["ranked"][0][1] < MIN_N:
        lines.append(f"WARNING: TOO SMALL TO SHOW. Top ability n={p['ranked'][0][1] if p['ranked'] else 0} "
                     f"< {MIN_N} (M={m}). Do not use as a tendency.")
    lines.append("Followed-by association only, not caused-by.")
    return "\n".join(lines)


def main(data_root=DATA_ROOT):
    team_ids, series = cloud9(data_root)
    ok_games = valid_games(data_root)
    rounds, players, dropped = [], {}, 0
    for sid in series:
        rs, ps = scan_series(sid, data_root)
        players.update(ps)
        dropped += sum(1 for r in rs if r["game"] not in ok_games)
        rounds += [r for r in rs if r["game"] in ok_games]
    p = profile(rounds, players, team_ids)
    print(f"series={len(series)} rounds kept={len(rounds)} rounds dropped (no valid session)={dropped}")
    print("Opponent Operator rounds:", sorted(p["op_round_counts"].items(), key=lambda x: -x[1]))
    top = top_opponents(rounds, players, team_ids)
    for q in top:
        n = q["ranked"][0][1] if q["ranked"] else 0
        print(f"\nTOP: {q['name']} ({q['player_id']}) op_rounds={q['op_rounds']} early_deaths={len(q['analyzed'])} "
              f"top_ability={q['ranked'][0][0] if q['ranked'] else None} n={n}" + (" BELOW n=3" if n < MIN_N else ""))
        for a in q["analyzed"]:
            print("analyzed:", a)
        for ability, k, cids in q["ranked"]:
            print(f"  {ability}: rounds n={k}, casts n={len(cids)}, cast_ids={cids}")
        print()
        print(card(q))
    return top


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DATA_ROOT)
