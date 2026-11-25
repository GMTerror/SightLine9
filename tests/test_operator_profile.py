import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import operator_profile as op  # noqa: E402

LOTUS = "67293f23-ec04-4774-a105-9fcb6afdca81"


def test_mada_series_2748746_matches_hand_query():
    rounds, players = op.scan_series("2748746")
    mada = next(pid for pid, (name, _) in players.items() if name == "mada")
    assert sorted((r["game"], r["round"]) for r in rounds if mada in r["op"]) == [(LOTUS, 10), (LOTUS, 17), (LOTUS, 18)]
    p = op.profile(rounds, players, "79", player_id=mada)
    assert [a["round"] for a in p["analyzed"]] == [17, 18]  # round 10 death is after the round's median
    assert p["ranked"][0][:2] == ("dark-cover", 2)


def test_cloud9_and_gc_give_28_series():
    team_ids, series = op.cloud9()
    assert team_ids == {"79", "3429"} and len(series) == len(set(series)) == 28


def test_card_shows_denominator_and_flags_small_n():
    p = {"name": "X", "op_rounds": 4, "analyzed": [{"side": "defender"}, {"side": "defender"}],
         "ranked": [("smoke", 2, ["a", "b"]), ("flash", 1, ["c"])]}
    text = op.card(p)
    assert "smoke was followed by X's early death in 2 of 2 Operator rounds analyzed" in text
    assert "TOO SMALL TO SHOW" in text and "caused" not in text.replace("caused-by", "")
