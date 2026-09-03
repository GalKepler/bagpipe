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
    monkeypatch.setattr(api, "load_config", lambda: {"app": {}})
    calls = []
    monkeypatch.setattr(api, "process_job", lambda *a, **kw: calls.append((a, kw)))

    client = TestClient(api.app)
    resp = client.post(
        "/predict",
        files={"file": ("scan.nii.gz", b"fake-nifti-bytes", "application/octet-stream")},
        data={"sex": "F", "age": "30"},
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


def test_job_results_page_renders_for_succeeded_job(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    work_dir = tmp_path / "job3" / "run"
    predict_dir = work_dir / "predict"
    predict_dir.mkdir(parents=True)
    prediction = {
        "predicted_age": 52.3,
        "bag_corrected": 4.1,
        "regional_zscores": {"Schaefer2018N400n7Tian2020S2__LH_Vis_1__vol_gm": 1.2},
    }
    (predict_dir / "prediction.json").write_text(json.dumps(prediction))
    manifest = {
        "job_id": "job3",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "succeeded",
        "stages": [{"name": "qc_gate", "status": "succeeded", "metrics": {"siqr_pct": 87.2}}],
    }
    (work_dir / "manifest.json").write_text(json.dumps(manifest))

    client = TestClient(api.app)
    resp = client.get("/jobs/job3/view")

    assert resp.status_code == 200
    assert "+4.1 years" in resp.text
    assert "LH_Vis_1" in resp.text
    assert "/static/brainmap.js" in resp.text


def test_job_results_page_404s_for_unfinished_job(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    _write_manifest(tmp_path / "job4" / "run", "running")
    client = TestClient(api.app)
    assert client.get("/jobs/job4/view").status_code == 404


def test_upload_page_renders(monkeypatch):
    monkeypatch.setattr(api, "load_config", lambda: {"app": {"turnstile_site_key": "site-123"}})
    client = TestClient(api.app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "site-123" in resp.text


def test_predict_rejects_when_turnstile_configured_and_missing_token(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    monkeypatch.setattr(
        api,
        "load_config",
        lambda: {"app": {"turnstile_secret_key": "secret", "max_queue_depth": 5}},
    )
    calls = []
    monkeypatch.setattr(api, "process_job", lambda *a, **kw: calls.append((a, kw)))

    client = TestClient(api.app)
    resp = client.post(
        "/predict",
        files={"file": ("scan.nii.gz", b"bytes", "application/octet-stream")},
        data={"sex": "F", "age": "30"},
    )

    assert resp.status_code == 400
    assert not calls


def test_predict_accepts_when_turnstile_verifies(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    monkeypatch.setattr(
        api,
        "load_config",
        lambda: {"app": {"turnstile_secret_key": "secret", "max_queue_depth": 5}},
    )
    monkeypatch.setattr(api.turnstile, "verify", lambda *a, **kw: True)
    calls = []
    monkeypatch.setattr(api, "process_job", lambda *a, **kw: calls.append((a, kw)))

    client = TestClient(api.app)
    resp = client.post(
        "/predict",
        files={"file": ("scan.nii.gz", b"bytes", "application/octet-stream")},
        data={"sex": "F", "age": "30", "cf-turnstile-response": "solved-token"},
    )

    assert resp.status_code == 202
    assert len(calls) == 1


def test_predict_rejects_when_queue_full(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    monkeypatch.setattr(api, "load_config", lambda: {"app": {"max_queue_depth": 0}})
    calls = []
    monkeypatch.setattr(api, "process_job", lambda *a, **kw: calls.append((a, kw)))

    client = TestClient(api.app)
    resp = client.post(
        "/predict",
        files={"file": ("scan.nii.gz", b"bytes", "application/octet-stream")},
        data={"sex": "F", "age": "30"},
    )

    assert resp.status_code == 503
    assert not calls
