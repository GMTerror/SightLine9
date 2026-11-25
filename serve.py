"""Read-only viewer for local/sightline.sqlite (Python stdlib http.server + sqlite3 mode=ro).

Run: python serve.py  ->  http://localhost:8000
"""
import csv
import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent
DB_PATH = ROOT / "local" / "sightline.sqlite"
SERIES, MAP_NAME, WINDOW = "2748746", "fracture", 10
TOP_CACHE = ROOT / "local" / "top_abilities_all.json"
MIN_RATE_CASTS = 20
_top = None
OP_CACHE = ROOT / "local" / "operator_profile.json"
_op = None
POOLED = ROOT / "local" / "pooled"
_series_cache = None
_ingest_lock = threading.Lock()

# Live casts in one game, with the "followed by" outcome at WINDOW seconds.
BASE = """FROM casts c
JOIN cast_outcomes o ON o.cast_id = c.rowid AND o.window_s = ?
WHERE c.series_id = ? AND c.game_id = ? AND c.is_live = 1"""


def connect(db_path=DB_PATH):
    return sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)


def _args(db, series=SERIES, game=None):
    """Query args for a game; game=None means the original default (MAP_NAME game of SERIES)."""
    if game is None:
        game = db.execute("SELECT game_id FROM games WHERE series_id = ? AND map_name = ?", (series, MAP_NAME)).fetchone()[0]
    return (WINDOW, series, game)


def rounds(db, series=SERIES, game=None):
    return [r[0] for r in db.execute(f"SELECT DISTINCT c.round_number {BASE} ORDER BY 1", _args(db, series, game))]


def bounds(db, series=SERIES, game=None):
    r = db.execute(f"SELECT MIN(c.pos_x), MAX(c.pos_x), MIN(c.pos_y), MAX(c.pos_y), COUNT(*) {BASE}",
                   _args(db, series, game)).fetchone()
    return dict(zip(("min_x", "max_x", "min_y", "max_y", "n"), r))


def casts(db, round_number, series=SERIES, game=None):
    q = (f"SELECT c.pos_x, c.pos_y, o.caster_got_kill, c.ability, c.player_id, c.cast_time, c.view_x, c.view_y "
         f"{BASE} AND c.round_number = ? ORDER BY c.cast_time")
    return [dict(zip(("x", "y", "got_kill", "ability", "player_id", "cast_time", "view_x", "view_y"), r))
            for r in db.execute(q, _args(db, series, game) + (round_number,))]


def series_list():
    """Every game of the indexed (Cloud9) series, from meta/games.csv (names, map, game number)."""
    global _series_cache
    if _series_cache is None:
        import cast_outcome_card as coc
        _, sids = coc.cloud9(coc.DATA_ROOT)
        sids = set(sids)
        with open(coc.DATA_ROOT / "meta" / "games.csv", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r["title"] == "val" and r["series_id"] in sids]
        _series_cache = sorted(({"series_id": r["series_id"], "game_id": r["game_id"], "map_name": r["map"],
                                 "game_number": int(r["game_number"]), "team1": r["team1_name"],
                                 "team2": r["team2_name"]} for r in rows),
                               key=lambda g: (g["series_id"], g["game_number"]))
    return _series_cache


def db_path_for(series):
    """DB for a listed series; ingests it into local/pooled on first use. Raises KeyError if not listed."""
    if not any(g["series_id"] == series for g in series_list()):
        raise KeyError(series)
    if series == SERIES:
        return DB_PATH
    p = POOLED / f"{series}.sqlite"
    with _ingest_lock:
        if not p.exists():
            import ingest_series
            ingest_series.ingest(series, db_path=p)
    return p


def match_data(series, game, round_number=None):
    """meta (round_number None) or casts for one listed game."""
    if not any(g["series_id"] == series and g["game_id"] == game for g in series_list()):
        raise KeyError(game)
    with connect(db_path_for(series)) as db:
        if round_number is None:
            info = next(g for g in series_list() if g["game_id"] == game)
            return {"rounds": rounds(db, series, game), "bounds": bounds(db, series, game), "window_s": WINDOW,
                    "map": info["map_name"], "series": series, "game": game}
        return casts(db, round_number, series, game)


def compute_top():
    """Top-N from cast_outcome_card's ranking over the pooled per-series DBs (ingests only a missing DB)."""
    import cast_outcome_card as coc
    team_ids, series_ids = coc.cloud9(coc.DATA_ROOT)
    valid = coc.valid_games(coc.DATA_ROOT)
    summaries = []
    for sid in series_ids:
        p = coc.DB_DIR / f"{sid}.sqlite"
        if not p.exists():
            coc.ingest(sid, db_path=p, data_root=coc.DATA_ROOT)
        summaries.append(coc.summarize_database(p, valid, team_ids))
    merged = coc.merge_summaries(summaries)
    rows = [{"ability": a, "casts": v["casts"], "caster_got_kill": v["caster_got_kill"]}
            for a, v in coc._ranked(merged["counts"])]
    return {"window_s": coc.WINDOW, "series_n": len(series_ids), "all": rows, "top_n": coc.TOP_N}


def top_abilities(sort="count"):
    """Cached all-ability counts (delete local/top_abilities_all.json to refresh); returns top N by count or rate."""
    global _top
    if _top is None:
        if TOP_CACHE.exists():
            _top = json.loads(TOP_CACHE.read_text())
        else:
            _top = compute_top()
            TOP_CACHE.write_text(json.dumps(_top))
    rows = _top["all"]
    if sort == "rate":
        rows = sorted((r for r in rows if r["casts"] >= MIN_RATE_CASTS),
                      key=lambda r: (-r["caster_got_kill"] / r["casts"], -r["casts"], r["ability"]))
    return {"window_s": _top["window_s"], "series_n": _top["series_n"], "sort": sort,
            "min_casts": MIN_RATE_CASTS if sort == "rate" else 0, "rows": rows[:_top["top_n"]]}


def compute_operator():
    """Top opponents by Operator rounds, via operator_profile.top_opponents (streams the GRID feeds once)."""
    import operator_profile as op
    team_ids, sids = op.cloud9()
    ok = op.valid_games()
    rounds, players = [], {}
    for sid in sids:
        rs, ps = op.scan_series(sid)
        players.update(ps)
        rounds += [r for r in rs if r["game"] in ok]
    out = []
    for p in op.top_opponents(rounds, players, team_ids):
        sides = {}
        for a in p["analyzed"]:
            sides[a["side"]] = sides.get(a["side"], 0) + 1
        side = ", ".join(f"{s} (n={n})" for s, n in sorted(sides.items(), key=lambda x: str(x[0]))) or "unknown"
        out.append({"name": p["name"], "side": side, "op_rounds": p["op_rounds"], "early_deaths": len(p["analyzed"]),
                    "abilities": [{"ability": a, "n": n, "casts": len(c)} for a, n, c in p["ranked"][:3]],
                    "too_small": not p["ranked"] or p["ranked"][0][1] < op.MIN_N})
    return {"window_s": op.WINDOW_S, "min_n": op.MIN_N, "series_n": len(sids), "opponents": out}


def operator_profile_data():
    """Cached like top_abilities (delete local/operator_profile.json to refresh)."""
    global _op
    if _op is None:
        if OP_CACHE.exists():
            _op = json.loads(OP_CACHE.read_text())
        else:
            _op = compute_operator()
            OP_CACHE.write_text(json.dumps(_op))
    return _op


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            body, ctype = (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8"
        elif u.path == "/api/series_list":
            body, ctype = json.dumps(series_list()).encode(), "application/json"
        elif u.path in ("/api/meta", "/api/casts"):
            q = parse_qs(u.query)
            sid, gid = q.get("series", [None])[0], q.get("game", [None])[0]
            try:
                if sid is None or gid is None:  # original behaviour: default series/map
                    with connect() as db:
                        if u.path == "/api/meta":
                            data = {"rounds": rounds(db), "bounds": bounds(db), "window_s": WINDOW,
                                    "map": MAP_NAME, "series": SERIES}
                        else:
                            data = casts(db, int(q.get("round", ["0"])[0]))
                else:
                    data = match_data(sid, gid, int(q.get("round", ["0"])[0]) if u.path == "/api/casts" else None)
            except KeyError:
                self.send_error(404)
                return
            body, ctype = json.dumps(data).encode(), "application/json"
        elif u.path == "/api/top_abilities":
            sort = "rate" if parse_qs(u.query).get("sort", ["count"])[0] == "rate" else "count"
            body, ctype = json.dumps(top_abilities(sort)).encode(), "application/json"
        elif u.path == "/api/operator_profile":
            body, ctype = json.dumps(operator_profile_data()).encode(), "application/json"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print("http://localhost:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
