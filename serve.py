"""Read-only viewer for local/sightline.sqlite (Python stdlib http.server + sqlite3 mode=ro).

Run: python serve.py  ->  http://localhost:8000
"""
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent
DB_PATH = ROOT / "local" / "sightline.sqlite"
SERIES, MAP_NAME, WINDOW = "2748746", "fracture", 10

# Live casts in the fracture game(s) of the series, with the "followed by" outcome at WINDOW seconds.
BASE = """FROM casts c
JOIN games g ON g.series_id = c.series_id AND g.game_id = c.game_id
JOIN cast_outcomes o ON o.cast_id = c.rowid AND o.window_s = ?
WHERE c.series_id = ? AND g.map_name = ? AND c.is_live = 1"""
ARGS = (WINDOW, SERIES, MAP_NAME)


def connect(db_path=DB_PATH):
    return sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)


def rounds(db):
    return [r[0] for r in db.execute(f"SELECT DISTINCT c.round_number {BASE} ORDER BY 1", ARGS)]


def bounds(db):
    r = db.execute(f"SELECT MIN(c.pos_x), MAX(c.pos_x), MIN(c.pos_y), MAX(c.pos_y), COUNT(*) {BASE}", ARGS).fetchone()
    return dict(zip(("min_x", "max_x", "min_y", "max_y", "n"), r))


def casts(db, round_number):
    q = f"SELECT c.pos_x, c.pos_y, o.caster_got_kill, c.ability, c.player_id, c.cast_time {BASE} AND c.round_number = ?"
    return [dict(zip(("x", "y", "got_kill", "ability", "player_id", "cast_time"), r))
            for r in db.execute(q, ARGS + (round_number,))]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            body, ctype = (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8"
        elif u.path in ("/api/meta", "/api/casts"):
            with connect() as db:
                if u.path == "/api/meta":
                    data = {"rounds": rounds(db), "bounds": bounds(db), "window_s": WINDOW,
                            "map": MAP_NAME, "series": SERIES}
                else:
                    data = casts(db, int(parse_qs(u.query).get("round", ["0"])[0]))
            body, ctype = json.dumps(data).encode(), "application/json"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print("http://localhost:8000")
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
