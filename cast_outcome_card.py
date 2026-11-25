"""General cast-outcome card pooled across indexed Cloud9 and Cloud9 GC series.

Streams each GRID series through ingest_series.ingest, then reports live casts and
the kills that followed them within the configured outcome window.
Requires Python 3.14+ (compression.zstd). Run: python cast_outcome_card.py
"""
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from ingest_series import DATA_ROOT, ingest
from operator_profile import cloud9, valid_games

WINDOW = 10
DB_DIR = Path(__file__).parent / "local" / "pooled"
TOP_N = 5


def summarize_database(db_path, valid_game_ids, team_ids):
    """Returns all-caster and Cloud9/GC ability counts plus successful examples."""
    counts = defaultdict(lambda: {"casts": 0, "caster_got_kill": 0})
    team_counts = defaultdict(lambda: {"casts": 0, "caster_got_kill": 0})
    examples = defaultdict(list)
    total_casts = total_kills = team_total_casts = team_total_kills = 0
    with closing(sqlite3.connect(db_path)) as db:
        rows = db.execute(
            "SELECT c.series_id, c.game_id, c.player_id, c.ability, c.cast_time, c.team_id, "
            "o.caster_got_kill FROM casts c JOIN cast_outcomes o ON o.cast_id = c.rowid "
            "WHERE c.is_live = 1 AND o.window_s = ? ORDER BY c.series_id, c.cast_time, c.rowid",
            (WINDOW,),
        )
        for series_id, game_id, player_id, ability, cast_time, team_id, got_kill in rows:
            if game_id not in valid_game_ids:
                continue
            hit = int(got_kill == 1)
            counts[ability]["casts"] += 1
            counts[ability]["caster_got_kill"] += hit
            total_casts += 1
            total_kills += hit
            if team_id in team_ids:
                team_counts[ability]["casts"] += 1
                team_counts[ability]["caster_got_kill"] += hit
                team_total_casts += 1
                team_total_kills += hit
            if hit:
                examples[ability].append((series_id, player_id, cast_time))
    return {
        "counts": dict(counts),
        "team_counts": dict(team_counts),
        "examples": dict(examples),
        "total_casts": total_casts,
        "total_kills": total_kills,
        "team_total_casts": team_total_casts,
        "team_total_kills": team_total_kills,
    }


def merge_summaries(summaries):
    """Combines per-series summaries without retaining individual database rows."""
    merged = {
        "counts": defaultdict(lambda: {"casts": 0, "caster_got_kill": 0}),
        "team_counts": defaultdict(lambda: {"casts": 0, "caster_got_kill": 0}),
        "examples": defaultdict(list),
        "total_casts": 0,
        "total_kills": 0,
        "team_total_casts": 0,
        "team_total_kills": 0,
    }
    for summary in summaries:
        for key in ("total_casts", "total_kills", "team_total_casts", "team_total_kills"):
            merged[key] += summary[key]
        for group in ("counts", "team_counts"):
            for ability, values in summary[group].items():
                merged[group][ability]["casts"] += values["casts"]
                merged[group][ability]["caster_got_kill"] += values["caster_got_kill"]
        for ability, values in summary["examples"].items():
            merged["examples"][ability].extend(values)
    merged["counts"] = dict(merged["counts"])
    merged["team_counts"] = dict(merged["team_counts"])
    merged["examples"] = dict(merged["examples"])
    return merged


def _ranked(counts):
    return sorted(counts.items(), key=lambda item: (-item[1]["caster_got_kill"], -item[1]["casts"], item[0]))


def format_card(summary, series_count, top=TOP_N):
    """Formats a Markdown card, with sample sizes attached to every count."""
    rows = _ranked(summary["counts"])
    lines = [
        f"### General Cast-Outcome Card (window_s={WINDOW})",
        f"Scope: Cloud9 / Cloud9 GC indexed series (n={series_count}); all teams' live casts in valid-session games.",
        f"Eligible live-cast population: n={summary['total_casts']}; casts followed by a caster kill within {WINDOW}s: "
        f"n={summary['total_kills']}.",
        f"| Rank | Ability | Live casts (n) | Caster got kill within {WINDOW}s (n) |",
        "|---:|---|---:|---:|",
    ]
    for rank, (ability, values) in enumerate(rows[:top], start=1):
        lines.append(f"| {rank} | `{ability}` | n={values['casts']} | n={values['caster_got_kill']} |")
    if rows:
        top_ability = rows[0][0]
        top_examples = sorted(summary["examples"].get(top_ability, []))[:3]
        lines.append(f"Examples of `{top_ability}` casts followed by a caster kill within {WINDOW}s (n={len(top_examples)}):")
        for series_id, player_id, cast_time in top_examples:
            lines.append(f"- Series `{series_id}`, player `{player_id}`, cast time `{cast_time}`.")
    lines.extend([
        f"Cloud9 / Cloud9 GC-only subset: live casts n={summary['team_total_casts']}; "
        f"casts followed by a caster kill within {WINDOW}s n={summary['team_total_kills']}.",
        "Assumptions: every team is included in the main ranking; Cloud9 and Cloud9 GC are identified by exact team names; "
        "games without a `session_valid=True` metadata row are excluded; only `is_live=1` casts and "
        f"`cast_outcomes.window_s={WINDOW}` are counted. These are followed-by associations.",
    ])
    return "\n".join(lines)


def build_card(data_root=DATA_ROOT, db_dir=DB_DIR):
    team_ids, series_ids = cloud9(data_root)
    valid_game_ids = valid_games(data_root)
    summaries = []
    for series_id in series_ids:
        db_path = db_dir / f"{series_id}.sqlite"
        ingest(series_id, db_path=db_path, data_root=data_root)
        summaries.append(summarize_database(db_path, valid_game_ids, team_ids))
    return format_card(merge_summaries(summaries), len(series_ids)), len(series_ids)


def main(data_root=DATA_ROOT, db_dir=DB_DIR):
    card, series_count = build_card(data_root, db_dir)
    print(f"Series processed: n={series_count}")
    print(card)


if __name__ == "__main__":
    main()