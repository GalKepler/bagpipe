# bagpipe — Brain Age Gap PIPEline

Framework for deep investigation of Brain Age Gap (BAG) on the SNBB dataset
(single-site Israeli cohort, ~4,500 participants, ~6,000 sessions).

Four pillars: **database** (canonical SQLite store), **modeling** (brain-age
regressors + CNNs), **causal** (event-associated BAG change), **web app**
(public DICOM-upload BAG report service).

See [`docs/DESIGN.md`](docs/DESIGN.md) for the full architecture and
[`docs/data_audit.md`](docs/data_audit.md) for the Phase 0 environment/data
audit. Read `CLAUDE.md` before contributing — it lists hard constraints
(this repo is public, the data is private).

## Setup

```bash
uv sync --extra dev
cp config/local.yaml.example config/local.yaml   # fill in your machine's paths; git-ignored
```

## Status

Phase 0 (audit) in progress. See `docs/DESIGN.md` §7 for the full phased
build plan.
