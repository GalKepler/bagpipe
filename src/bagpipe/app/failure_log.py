"""Durable, append-only record of every failed job.

Per-job detail lives in that job's own `run/manifest.json`, but job
directories get cleaned up (retention) and there's no single place to spot a
recurring failure pattern across jobs — see the 2026-09-07 incident (a
`report` stage KeyError, and a run of orphaned-queue-task failures) that
prompted this. One line per failure, in `outputs/failed_jobs.jsonl`, next to
`uploads/` — `grep`/`jq` it for patterns rather than digging through
per-job manifests.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from bagpipe.core.config import get_path


def log_failure(job_id: str, stage: str, code: str, message: str) -> None:
    path = get_path("uploads_dir").parent / "failed_jobs.jsonl"
    record = {
        "job_id": job_id,
        "stage": stage,
        "code": code,
        "message": message,
        "failed_at": datetime.now(UTC).isoformat(),
    }
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")
