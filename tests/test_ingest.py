import csv
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from ingest_series import DATA_ROOT, ingest  # noqa: E402

SERIES = "2748746"


def _db(tmp_path):
    db = tmp_path / "t.sqlite"
    ingest(SERIES, db_path=db)
    return sqlite3.connect(db)


def test_rounds_per_game_equal_score_sum(tmp_path):
    db = _db(tmp_path)
    with open(DATA_ROOT / "meta" / "games.csv", newline="", encoding="utf-8") as f:
        expected = {r["game_id"]: int(r["team1_score"]) + int(r["team2_score"])
                    for r in csv.DictReader(f) if r["series_id"] == SERIES}
    got = dict(db.execute("SELECT game_id, COUNT(*) FROM rounds GROUP BY game_id"))
    assert expected and got == expected


def test_rounds_with_kill_equal_first_kills(tmp_path):
    db = _db(tmp_path)
    rounds_with_kill = db.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT game_id, round_number FROM kills)").fetchone()[0]
    first_kills = db.execute("SELECT COUNT(*) FROM kills WHERE first_kill = 1").fetchone()[0]
    assert rounds_with_kill == first_kills


def test_oxy_blast_pack_caster_got_kill_by_window(tmp_path):
    db = _db(tmp_path)
    got = dict(db.execute(
        "SELECT o.window_s, o.caster_got_kill FROM cast_outcomes o JOIN casts c ON c.rowid = o.cast_id "
        "WHERE c.cast_time = '2025-01-18T00:10:53.274Z' AND c.player_id = '10636' AND c.ability = 'blast-pack'"))
    assert got == {5: 0, 10: 0, 15: 1}


def test_invalid_kills_flagged_not_deleted(tmp_path):
    db = _db(tmp_path)
    total, invalid = db.execute("SELECT COUNT(*), SUM(is_valid_kill = 0) FROM kills").fetchone()
    same_team = db.execute(
        "SELECT COUNT(*) FROM kills WHERE killer_team_id = victim_team_id OR killer_id = victim_id").fetchone()[0]
    assert total == 348 and invalid == same_team
