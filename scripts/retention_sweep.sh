#!/usr/bin/env bash
# Cron entry (suggested, NOT installed automatically — add manually):
#   0 4 * * * /media/storage/bagpipe/scripts/retention_sweep.sh >> /media/storage/bagpipe/outputs/retention_sweep.log 2>&1
#
# Deletes job directories under paths.uploads_dir older than
# --max-age-days (default 30). Applies to every job dir, opted-in
# (retention_opt_in=true) uploads included — deploy/README.md admits there
# is no retention duration and nothing ever deletes retained data; this is
# that missing piece. Non-consenting job dirs should already be imaging-free
# by the time this runs (bagpipe.app.queue._delete_imaging, at job
# completion) — this sweep only clears the remaining tabular/report
# leftovers and any dir that somehow escaped that cleanup.
#
# Idempotent — safe to run daily regardless of how much is due for removal.
set -euo pipefail
cd /media/storage/bagpipe
source .venv/bin/activate

bag app retention-sweep --max-age-days 30
