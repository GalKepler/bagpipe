#!/usr/bin/env bash
# Cron entry (crontab -l): retrains the CAT26 (v26) leaderboard trio every
# 12h against whatever outputs/datasets_v26 currently has (kept fresh by
# periodic_ingest_export.sh, every 3h) — baseline_v26 as a cheap sanity
# check, stacked_v26 and stacked_v26_surface for the real comparison
# (volume-only vs. full surface panel). Same trio
# notebooks/stacked_ensemble_review.ipynb §6 trains — MLflow accumulates
# every run (bagpipe-cat12v26 experiment), so the leaderboard's trend over
# time is visible there, not just the latest number.
#
# Does NOT itself call `bag models promote` — that now runs on its own
# daily timer (scripts/periodic_promote.sh, maintainer's explicit request
# 2026-08-25), separate from this eval-only trio so a slow/bad training run
# here can't block or race the promotion.
#
# Real resource contention, not fixed here: stacked.yaml's
# `stacker.n_jobs: -1` competes for CPU with the CAT12 cohort
# preprocessing (bag preprocess cat12-cohort, concurrency: 12, running
# separately in tmux) — both are legitimately CPU-heavy. Left as config's
# own decision (n_jobs is already what every stacked config in this repo
# sets) rather than silently overriding it here; revisit if training runs
# start measurably slowing the cohort reprocessing down.
set -euo pipefail
cd /media/storage/bagpipe
source .venv/bin/activate

bag models train-baseline --config config/models/baseline_v26.yaml
bag models train-stacked --config config/models/stacked_v26.yaml
bag models train-stacked --config config/models/stacked_v26_surface.yaml
