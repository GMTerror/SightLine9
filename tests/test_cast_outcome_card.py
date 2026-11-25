import gc
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import cast_outcome_card as card  # noqa: E402
from ingest_series import DATA_ROOT, ingest  # noqa: E402
from operator_profile import cloud9, valid_games  # noqa: E402


SERIES = "2748746"


def test_series_2748746_window_10_aggregation_and_card(tmp_path):
    team_ids, _ = cloud9()
    db_path = tmp_path / "2748746.sqlite"
    ingest(SERIES, db_path=db_path, data_root=DATA_ROOT)
    summary = card.summarize_database(db_path, valid_games(), team_ids)
    text = card.format_card(summary, series_count=28)

    assert summary["total_casts"] == 1323
    assert summary["total_kills"] == 174
    assert "n=1323" in text and "n=174" in text
    assert "followed by" in text
    gc.collect()