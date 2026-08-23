# Getting started — the `bag` CLI

Everything below reflects the CLI's real, current behavior (checked against
`src/bagpipe/cli.py` 2026-08-23), not the aspirational plan in `DESIGN.md`.
If a command here disagrees with `DESIGN.md`, this doc wins for "what
actually runs today."

## 0. Setup

```bash
uv sync
cp config/local.yaml.example config/local.yaml   # then fill in real paths — gitignored
```

`config/local.yaml` is where every real filesystem path lives (`db.db_path`,
`db.cat12_dir`, `db.cat12_apptainer_image`, etc.) — see CLAUDE.md's
"Machine-specific facts" section for this machine's actual values. Code
reads them via `bagpipe.core.config.get_path(...)`; nothing is hardcoded.

All commands below are `bag <command> <subcommand> [--config ...]`, run from
the repo root (`uv run bag ...`, or activate the venv first).

## 1. The DB — where it lives, what's in it

One SQLite file, shared with the separate **brainlink** project
(`db.db_path` in your `config/local.yaml`). bagpipe's own tables, defined in
`src/bagpipe/db/models.py`:

| Table | What it holds |
|---|---|
| `features` | long-format CAT12 features — one row per (uid, session, source, atlas, region, metric) |
| `cat12_quality` | per-session QC (SIQR, NCR, ICR, resolution, WMH, CAT version) |
| `legacy_participant` | pre-SNBB cohort demographics |
| `legacy_imaging_path` | T1w NIfTI paths, both cohorts, for DL training |
| `events` | exposure events for the causal pillar (Oct 7 war, judicial reform, COVID waves) |
| `predictions` | per-session brain-age predictions from a registered model |
| `models_registry` | promoted model artifacts + metrics + MLflow run IDs |

**Inspecting it** — no GUI wired in yet (Datasette is the planned tool per
`DESIGN.md` but isn't a dependency yet); use plain `sqlite3` or Python for
now:

```bash
sqlite3 "$(python -c 'from bagpipe.core.config import get_path; print(get_path("db_path"))')"
```

```sql
.tables
.schema features
SELECT source, atlas, COUNT(*) FROM features GROUP BY 1, 2;
SELECT COUNT(*) FROM cat12_quality WHERE siqr_grade LIKE 'F%';
```

or from Python:

```python
import pandas as pd
from bagpipe.db.base import get_engine

df = pd.read_sql("SELECT * FROM features LIMIT 20", get_engine())
```

Every `bag ingest ...` command below is **idempotent** (safe to re-run —
upserts, never duplicates) and prints a summary of rows added.

## 2. Ingest commands (`bag ingest ...`)

No shared ordering requirement between these — each targets a different
table — except `ingest cat12-cohort`, which needs `preprocess cat12-cohort`
output to exist first (§3).

| Command | Reads | Writes | Config |
|---|---|---|---|
| `bag ingest cat12` | `db.cat12_dir` (tabular exports) + `db.cat12_images_dir` (raw XML reports, for QC) | `features` (`source="cat12"`), `cat12_quality` | none (paths from `config/local.yaml`) |
| `bag ingest cat12-cohort` | `output_derivatives_dir` from the cat12-cohort config | `features` (`source="cat12_v26"`), `cat12_quality` | `--config config/cat12_cohort.yaml` (default) |
| `bag ingest t1w-paths` | BIDS tree | `legacy_imaging_path` | none |
| `bag ingest legacy-demographics` | legacy cohort export | `legacy_participant` | none |
| `bag ingest events` | `config/events.yaml` | `events` | none (path is hardcoded to `config/events.yaml`) |

```bash
bag ingest cat12                          # training-era CAT12.9 tabular export
bag ingest cat12-cohort --config config/cat12_cohort.yaml   # after a preprocess run (§3)
bag ingest t1w-paths
bag ingest legacy-demographics
bag ingest events
```

Note: `cat12` and `cat12-cohort` write to `features` under **different**
`source` values (`"cat12"` vs `"cat12_v26"`) — both stay queryable side by
side, neither overwrites the other. Only the production Schaefer+Tian atlas
is ingested from the cohort run; the extra atlases it also computes
(neuromorphometrics, lpba40, cobra, thalamus, thalamic_nuclei, suit) aren't
wired into ingest yet. **Surface/thickness output (`surf/*.gii`, cortical
thickness) is not ingested at all** — CAT12 produces it now (fixed
2026-08-23, see CLAUDE.md Phase 4), but nothing in `bagpipe.db` consumes it
yet; it's real files on disk under each subject's `surf/`, not DB rows.

## 3. Bulk preprocessing (`bag preprocess ...`)

Reprocesses the SNBB BIDS tree through `container/cat12.sif` — the same
container used for Pillar 4 inference, so segmentation params can't drift
between training and serving.

```bash
bag preprocess cat12-cohort --config config/cat12_cohort.yaml
bag preprocess cat12-cohort-status --config config/cat12_cohort.yaml   # read-only progress check
```

Resumable by design: a SQLite ledger under `output_derivatives_dir` tracks
per-subject status; interrupting and re-running just picks up where it left
off. Tune via `config/cat12_cohort.yaml` — see the comments in that file for
`limit` (cap subjects per invocation, use a small number to validate a
config change before a full run), `concurrency`, `timeout_minutes`, and
`extra_batch_lines` (surface/thickness/extra-atlas toggles).

This step only produces files on disk — run `bag ingest cat12-cohort`
afterward to get the (non-surface) features into the DB.

## 4. Export + models (`bag export`, `bag models`)

```bash
bag export training-table                 # features -> Parquet, for model training
bag models train-baseline --config config/models/baseline.yaml   # or baseline_ridge.yaml / baseline_lightgbm.yaml
bag models train-stacked  --config config/models/stacked.yaml
bag models train-sfcn     --config config/models/sfcn.yaml
bag models promote --name stacked --config config/models/stacked.yaml --version v2
```

`promote` fits on full data (not just CV folds) and writes a row to
`models_registry`, auto-archiving any prior `production`-stage row with the
same name. Only `stacked` is wired into promotion currently.

## 5. Web app (`bag app ...`)

```bash
bag app serve --host 127.0.0.1 --port 8000    # FastAPI upload/predict endpoint
bag app worker --workers 1                     # Huey job queue consumer
```

Not yet production-verified end to end (see CLAUDE.md Phase 4 status) —
useful for local testing of the upload → CAT12 → predict flow.
