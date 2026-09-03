#!/usr/bin/env bash
# Cron entry: nightly pull of newly-arrived SNBB T1w sessions from the SMB
# source (paths.bids_root) into the local BIDS mirror (cat12_cohort.yaml's
# bids_root) — only the one best T1w per session, not the whole tree — then
# run those through the same container/cat12.sif as inference (bag
# preprocess cat12-cohort — ledger-resumable, skips already-succeeded
# subjects, safe to run every night regardless of how much is new).
#
# Guards against overlapping with an already-running cat12-cohort process
# (e.g. a manual backfill in tmux, or last night's run still going) — the
# ledger has no "running" state, so two concurrent invocations could
# double-submit the same pending file and double real GPU/apptainer load.
set -euo pipefail
cd /media/storage/bagpipe

if pgrep -f "bag preprocess cat12-cohort" > /dev/null; then
    echo "$(date): cat12-cohort already running, skip"
    exit 0
fi

source .venv/bin/activate
bag preprocess sync-t1w --config config/cat12_cohort.yaml
bag preprocess cat12-cohort --config config/cat12_cohort.yaml
