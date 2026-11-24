import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import serve  # noqa: E402


def test_round1_dots_equal_sql_count():
    sql = ("SELECT COUNT(*) FROM casts c JOIN games g ON g.game_id = c.game_id "
           "WHERE g.map_name = 'fracture' AND c.is_live = 1 AND c.round_number = 1")
    expected = sqlite3.connect(serve.DB_PATH).execute(sql).fetchone()[0]
    with serve.connect() as db:
        assert expected > 0 and len(serve.casts(db, 1)) == expected


def test_round1_slider_extremes_and_view():
    with serve.connect() as db:
        rows = serve.casts(db, 1)
    times = [r["cast_time"] for r in rows]
    assert len(rows) == 14 and all("view_x" in r and "view_y" in r for r in rows)
    assert sum(t <= max(times) for t in times) == 14
    assert sum(t <= min(times) for t in times) == times.count(min(times)) == 1
