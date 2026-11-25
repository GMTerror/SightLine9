# Sightline9

A small local viewer for Cloud9 VALORANT ability casts. It shows where casts happened on a map, which of them were **followed by** a caster kill within 10 seconds, and which abilities most often show that pattern across 28 series.

> **Followed by, not caused by.** Every number here is a temporal association inside a fixed window. The data has no counterfactual, so it cannot show that an ability produced a kill. Every stat is shown with its sample size (n), and small samples are flagged instead of presented as tendencies.

## Features

- **Match selector:** pick any of the 66 games across the 28 indexed series. Round list, slider and map outline follow the selected game.
- **Cast map:** one dot per live cast, green if the caster got a kill within 10s after the cast, grey otherwise. Click a dot to see its aim line. The outline is the bounding box of the game's cast positions, not the true map shape. No Riot map textures are used.
- **Round and time controls:** filter by round and by `cast_time <=`.
- **General patterns:** top 5 abilities across all series, sortable by count or rate, each with n. "Copy callout" copies a one-line summary of the current #1 ability.
- **Operator tendencies:** for top opponents by Operator rounds, the abilities cast in the 10s before an early death, with n/M. If the top ability has n < 3, the card shows an amber "Sample too small" warning. Compare two opponents side by side, or list all.

## Requirements

- Python 3.14 or newer (the code uses `compression.zstd`). Standard library only; nothing to install to run the viewer.
- `pytest` to run the tests (`pip install pytest`)
- The GRID starter data folder (contains `meta/` and `val/`). It is not in this repo. Set the `SIGHTLINE_DATA_ROOT` environment variable to its path. If unset, `ingest_series.py` falls back to a hard-coded path on the author's machine, which will not exist on yours.
- `local/` holds generated databases and caches. It is created on first use and is not committed.

## Run

```
python serve.py
```

Then open http://localhost:8000. The server binds to `127.0.0.1` only, so other machines can't reach it unless you change that in `serve.py`.

Example (PowerShell):

```
$env:SIGHTLINE_DATA_ROOT = "C:\path\to\stl-hackathon-2026-grid-starter"
python serve.py
```

The first call to the Operator tendencies tab scans all feeds and can take up to about 90 seconds. The result is cached in `local/operator_profile.json`; delete it to refresh. A listed series whose database is missing is ingested into `local/pooled/` on first selection.

## Test

```
python -m pytest tests
```

`tests/test_viewer.py` mostly uses the databases in `local/`. `test_ingest.py`, `test_cast_outcome_card.py` and `test_operator_profile.py` read the real GRID data, so they need `SIGHTLINE_DATA_ROOT` set.

Manual check: reload the page, confirm round 1 of series 2748746 (fracture) shows 14 dots, 3 green; the slider reduces the dot count; By count / By rate reorders the list.

## Layout

| Path | Purpose |
|---|---|
| `serve.py` | HTTP server and JSON routes |
| `index.html` | The viewer (HTML, CSS and JS in one file) |
| `ingest_series.py` | Ingests one series into a SQLite database |
| `cast_outcome_card.py` | Ranks abilities by caster kills in the window |
| `operator_profile.py` | Operator opponent profiles (`top_opponents()`) |
| `tests/` | Viewer and API tests |
| `local/` | Generated databases and caches (not committed) |
| `WORKLOG.md` | Project history |

## API

| Route | Returns |
|---|---|
| `/` | The viewer page (`index.html`) |
| `/api/series_list` | `series_id`, `map_name`, `game_number`, team names, `game_id` for each game |
| `/api/meta`, `/api/casts` | Rounds and casts. Accept `series` and `game`; without them they default to series 2748746 on fracture. `/api/casts` also takes `round` |
| `/api/top_abilities` | Top abilities across all series. `sort=count` (default) or `sort=rate` |
| `/api/operator_profile` | Opponent profiles, with a `too_small` flag |

## Data rules

- GRID data stays outside the repo (set `SIGHTLINE_DATA_ROOT`); `local/` and the data file patterns are gitignored.
- Maps use simple vector shapes only, with no Riot textures.

## License

See [LICENSE](LICENSE).
