"""bagpipe.app.failure_log — the one durable place a recurring job failure
can be spotted after per-job manifests are cleaned up.
"""

from __future__ import annotations

import json

from bagpipe.app import failure_log


def test_log_failure_appends_jsonl_record(tmp_path, monkeypatch):
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    monkeypatch.setattr(failure_log, "get_path", lambda key: uploads_dir)

    failure_log.log_failure("job-1", "report", "internal", "'bag'")
    failure_log.log_failure("job-2", "queue", "task_lost", "huey task dequeued but never executed")

    lines = (tmp_path / "failed_jobs.jsonl").read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["job_id"] == "job-1"
    assert first["stage"] == "report"
    assert first["code"] == "internal"
    assert first["message"] == "'bag'"
    assert "failed_at" in first
