#!/usr/bin/env bash
# Cron entry (crontab -l): picks up newly-processed CAT12 cohort subjects
# (bag preprocess cat12-cohort, running separately in tmux) into the shared
# DB, then refreshes the CAT26 training-table Parquet export so the model
# training script (periodic_train_models.sh) always has current data.
# Idempotent — safe to run every 3h regardless of how much new data landed.
set -euo pipefail
cd /media/storage/bagpipe
source .venv/bin/activate

bag ingest cat12-cohort --config config/cat12_cohort.yaml
bag export training-table --source cat12_v26 --out-dir outputs/datasets_v26
