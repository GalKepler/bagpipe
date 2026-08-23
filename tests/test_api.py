"""bagpipe.app.api — /predict enqueue + /jobs polling contract. Stubs the
queue task (no huey worker, no CAT12) so this only exercises the HTTP layer:
upload handling, job_id issuance, and manifest -> response translation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from bagpipe.app import api


def _write_manifest(work_dir, status: str) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "job_id": "x",
        "created_at": datetime.now(UTC).isoformat(),
        "status": status,
        "stages": [{"name": "ingest", "status": "succeeded"}],
    }
    if status == "failed":
        manifest["error"] = {
            "stage": "segment",
            "code": "internal",
            "message": "boom",
            "user_message": "Something went wrong.",
        }
    elif status == "succeeded":
        predict_dir = work_dir / "predict"
        predict_dir.mkdir()
        (predict_dir / "prediction.json").write_text(json.dumps({"predicted_age": 42.0}))
    (work_dir / "manifest.json").write_text(json.dumps(manifest))


def test_predict_enqueues_and_returns_job_id(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)  # uploads_dir
    calls = []
    monkeypatch.setattr(api, "process_job", lambda *a, **kw: calls.append((a, kw)))

    client = TestClient(api.app)
    resp = client.post(
        "/predict",
        files={"file": ("scan.nii.gz", b"fake-nifti-bytes", "application/octet-stream")},
        data={"sex": "F"},
    )

    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert (tmp_path / job_id / "input" / "scan.nii.gz").read_bytes() == b"fake-nifti-bytes"
    assert len(calls) == 1


def test_job_status_unknown_job_404(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    client = TestClient(api.app)
    assert client.get("/jobs/does-not-exist").status_code == 404


def test_job_status_succeeded_includes_result(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    _write_manifest(tmp_path / "job1" / "run", "succeeded")

    client = TestClient(api.app)
    body = client.get("/jobs/job1").json()

    assert body["status"] == "succeeded"
    assert body["result"] == {"predicted_age": 42.0}


def test_job_status_failed_includes_error(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    _write_manifest(tmp_path / "job2" / "run", "failed")

    client = TestClient(api.app)
    body = client.get("/jobs/job2").json()

    assert body["status"] == "failed"
    assert body["error"]["user_message"] == "Something went wrong."
