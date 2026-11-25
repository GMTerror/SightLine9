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


def test_series_list_covers_28_series_and_has_fields():
    games = serve.series_list()
    assert len({g["series_id"] for g in games}) == 28 and len(games) >= 28
    assert all({"series_id", "map_name", "game_number", "team1", "team2", "game_id"} <= g.keys() for g in games)


def test_other_match_round1_equals_sql_and_bounds_differ():
    other = next(g for g in serve.series_list() if g["series_id"] != serve.SERIES)
    path = serve.db_path_for(other["series_id"])
    sql = ("SELECT COUNT(*) FROM casts WHERE series_id = ? AND game_id = ? AND is_live = 1 AND round_number = 1")
    expected = sqlite3.connect(path).execute(sql, (other["series_id"], other["game_id"])).fetchone()[0]
    meta = serve.match_data(other["series_id"], other["game_id"])
    assert expected > 0 and 1 in meta["rounds"]
    assert len(serve.match_data(other["series_id"], other["game_id"], 1)) == expected
    with serve.connect() as db:
        assert meta["bounds"] != serve.bounds(db)  # recalculated per game


def test_unknown_match_rejected():
    import pytest
    with pytest.raises(KeyError):
        serve.match_data("../x", "nope")


def test_top_abilities_matches_card_ranking():
    top = serve.top_abilities()
    assert top["series_n"] == 28 and top["window_s"] == 10 and len(top["rows"]) == 5
    assert top["rows"][0] == {"ability": "dark-cover", "casts": 4834, "caster_got_kill": 370}
    assert serve.top_abilities() == top  # served from cache


def test_top_abilities_rate_sort():
    rows = serve.top_abilities("rate")["rows"]
    assert len(rows) == 5 and all(r["casts"] >= 20 for r in rows)
    rates = [r["caster_got_kill"] / r["casts"] for r in rows]
    assert rates == sorted(rates, reverse=True) and rows[0]["ability"] != "dark-cover"


def test_round1_slider_extremes_and_view():
    with serve.connect() as db:
        rows = serve.casts(db, 1)
    times = [r["cast_time"] for r in rows]
    assert len(rows) == 14 and all("view_x" in r and "view_y" in r for r in rows)
    assert sum(t <= max(times) for t in times) == 14
    assert sum(t <= min(times) for t in times) == times.count(min(times)) == 1
