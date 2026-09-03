#!/usr/bin/env bash
# Cron entry (crontab -l): promotes a fresh stacked v26 model to production
# every 24h, against whatever outputs/datasets_v26 currently has (kept
# fresh by periodic_ingest_export.sh, every 3h). Version tag is the date
# the promotion ran, so `models_registry` accumulates one row per day
# (previous production row auto-archives, per promote.py).
#
# Uses stacked_v26_surface.yaml (volume + full surface panel, one shared
# Schaefer400 parcellation) instead of stacked_v26.yaml (volume-only) as
# of 2026-09-03 — mae_raw=4.79y verified 2026-08-26 vs stacked_v26.yaml's
# volume-only number, on the surface-covered subset of the cohort. Session
# count on the surface side is smaller than the full v26 cohort (build_
# region_matrix drops rows missing any surface column) — check n_samples
# in production_model_status.ipynb, don't assume parity with the old run.
#
# The cohort is still reprocessing (CLAUDE.md, 2026-08-25) — early runs of
# this script promote on a small, growing sample; check
# notebooks/production_model_status.ipynb rather than assuming today's
# number beats yesterday's.
set -euo pipefail
cd /media/storage/bagpipe
source .venv/bin/activate

bag models promote --name stacked --config config/models/stacked_v26_surface.yaml --version "v26-$(date +%Y%m%d)"
