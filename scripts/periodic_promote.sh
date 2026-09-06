#!/usr/bin/env bash
# Cron entry (crontab -l): promotes a fresh stacked v26 model to production
# every 24h, against whatever outputs/datasets_v26 currently has (kept
# fresh by periodic_ingest_export.sh, every 3h). Version tag is the date
# the promotion ran, so `models_registry` accumulates one row per day
# (previous production row auto-archives, per promote.py).
#
# MUST stay stacked_v26.yaml (volume-only). Reverted from
# stacked_v26_surface.yaml on 2026-09-03, before that config's first
# promotion ever ran: the Pillar 4 web app CANNOT serve a surface model.
# bagpipe.app.pipeline.features parses catROI_*.xml volume tissues only —
# bagpipe.app.surface_atlas is called from bagpipe.db.ingest_cat12_cohort
# and nowhere else — so every upload would die at extract_features with
# FEATURE_SCHEMA_MISMATCH. The surface model IS the better model
# (mae_raw 4.69 vs 4.86); promoting it is gated on wiring surface
# extraction into the app's features stage first.
#
# The cohort is still reprocessing (CLAUDE.md, 2026-08-25) — early runs of
# this script promote on a small, growing sample; check
# notebooks/production_model_status.ipynb rather than assuming today's
# number beats yesterday's.
#
# `bag models promote` now refuses to promote (nonzero exit, no DB change)
# unless the challenger's mae_corrected beats the incumbent's stored
# `predictions` with a paired-subject-bootstrap CI excluding 0 — see
# bagpipe.models.promote.PromotionRejected. A cron failure here most likely
# means "today's retrain wasn't confidently better", not a real error; check
# the log before assuming something broke. `--force` overrides.
set -euo pipefail
cd /media/storage/bagpipe
source .venv/bin/activate

bag models promote --name stacked --config config/models/stacked_v26.yaml --version "v26-$(date +%Y%m%d)"
