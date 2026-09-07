"""bagpipe.app.api — /predict enqueue + /jobs polling contract. Stubs the
queue task (no huey worker, no CAT12) so this only exercises the HTTP layer:
upload handling, job_id issuance, and manifest -> response translation.
"""

from __future__ import annotations

import json
import os
import time
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

    class _FakeResult:
        id = "fake-task-id"

    def _fake_process_job(*a, **kw):
        calls.append((a, kw))
        return _FakeResult()

    monkeypatch.setattr(api, "process_job", _fake_process_job)

    client = TestClient(api.app)
    resp = client.post(
        "/predict",
        files={"file": ("scan.nii.gz", b"fake-nifti-bytes", "application/octet-stream")},
        data={"sex": "F", "age": "30"},
    )

    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert (tmp_path / job_id / "input" / "upload.nii.gz").read_bytes() == b"fake-nifti-bytes"
    assert len(calls) == 1


JOB1 = "11111111-1111-1111-1111-111111111111"
JOB2 = "22222222-2222-2222-2222-222222222222"
JOB3 = "33333333-3333-3333-3333-333333333333"
JOB4 = "44444444-4444-4444-4444-444444444444"
UNKNOWN_JOB = "99999999-9999-9999-9999-999999999999"


def test_job_status_unknown_job_404(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    client = TestClient(api.app)
    assert client.get(f"/jobs/{UNKNOWN_JOB}").status_code == 404


def test_job_status_non_uuid_job_id_404(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    client = TestClient(api.app)
    resp = client.get("/jobs/../../etc/passwd".replace("/", "%2F"))
    assert resp.status_code == 404
    resp = client.get("/jobs/does-not-exist")
    assert resp.status_code == 404


def test_job_status_queued_before_manifest_exists(tmp_path, monkeypatch):
    """A job dir with no run/manifest.json yet (normal pre-pickup state with
    a single worker) must report 200 'queued', not 404 — see api.py's
    job_status docstring.
    """
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    (tmp_path / JOB1).mkdir(parents=True)

    client = TestClient(api.app)
    body = client.get(f"/jobs/{JOB1}").json()

    assert body == {"job_id": JOB1, "status": "queued", "stages": []}


def test_job_status_still_queued_if_task_still_pending(tmp_path, monkeypatch):
    """task_id recorded, old enough to clear the grace window, but huey
    still reports it pending — a real queued-behind-another-job wait, not a
    lost task. Must stay 'queued'.
    """
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    job_dir = tmp_path / JOB1
    job_dir.mkdir(parents=True)
    (job_dir / "task_id").write_text("task-1")
    old = time.time() - api._ORPHAN_GRACE_SECONDS - 60
    os.utime(job_dir / "task_id", (old, old))

    class _PendingTask:
        id = "task-1"

    monkeypatch.setattr(api.huey, "pending", lambda: [_PendingTask()])

    client = TestClient(api.app)
    body = client.get(f"/jobs/{JOB1}").json()

    assert body["status"] == "queued"


def test_job_status_failed_if_task_lost(tmp_path, monkeypatch):
    """task_id recorded, grace window elapsed, and huey no longer has the
    task pending (dequeued or silently dropped — see api.py's `_job_task_lost`
    docstring). Must report 'failed' instead of spinning forever.
    """
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    job_dir = tmp_path / JOB1
    job_dir.mkdir(parents=True)
    (job_dir / "task_id").write_text("task-1")
    old = time.time() - api._ORPHAN_GRACE_SECONDS - 60
    os.utime(job_dir / "task_id", (old, old))
    monkeypatch.setattr(api.huey, "pending", lambda: [])

    client = TestClient(api.app)
    body = client.get(f"/jobs/{JOB1}").json()

    assert body["status"] == "failed"
    assert "error" in body


def test_job_status_succeeded_includes_result(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    _write_manifest(tmp_path / JOB1 / "run", "succeeded")

    client = TestClient(api.app)
    body = client.get(f"/jobs/{JOB1}").json()

    assert body["status"] == "succeeded"
    assert body["result"] == {"predicted_age": 42.0}


def test_job_status_failed_includes_error(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    _write_manifest(tmp_path / JOB2 / "run", "failed")

    client = TestClient(api.app)
    body = client.get(f"/jobs/{JOB2}").json()

    assert body["status"] == "failed"
    assert body["error"]["user_message"] == "Something went wrong."


def test_job_results_page_renders_for_succeeded_job(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    work_dir = tmp_path / JOB3 / "run"
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
    resp = client.get(f"/jobs/{JOB3}/view")

    assert resp.status_code == 200
    assert "+4.1 years" in resp.text
    assert "LH_Vis_1" in resp.text
    assert "/static/brainmap.js" in resp.text


def test_job_results_page_404s_for_unfinished_job(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    _write_manifest(tmp_path / JOB4 / "run", "running")
    client = TestClient(api.app)
    assert client.get(f"/jobs/{JOB4}/view").status_code == 404


def test_report_pdf_served_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    report_dir = tmp_path / JOB1 / "run" / "report"
    report_dir.mkdir(parents=True)
    (report_dir / "report.pdf").write_bytes(b"%PDF-fake-bytes")

    client = TestClient(api.app)
    resp = client.get(f"/jobs/{JOB1}/report.pdf")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"%PDF-fake-bytes"


def test_report_pdf_404s_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    client = TestClient(api.app)
    assert client.get(f"/jobs/{JOB1}/report.pdf").status_code == 404


def test_report_pdf_rejects_non_uuid_job_id(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    client = TestClient(api.app)
    assert client.get("/jobs/not-a-uuid/report.pdf").status_code == 404


def test_landing_page_renders(monkeypatch):
    monkeypatch.setattr(api, "load_config", lambda: {"app": {"turnstile_site_key": "site-123"}})
    client = TestClient(api.app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "site-123" in resp.text
    assert 'id="upload"' in resp.text
    assert 'id="science"' in resp.text
    assert 'id="privacy"' in resp.text


def test_predict_rejects_when_turnstile_configured_and_missing_token(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    monkeypatch.setattr(
        api,
        "load_config",
        lambda: {"app": {"turnstile_secret_key": "secret", "max_queue_depth": 5}},
    )
    calls = []

    class _FakeResult:
        id = "fake-task-id"

    def _fake_process_job(*a, **kw):
        calls.append((a, kw))
        return _FakeResult()

    monkeypatch.setattr(api, "process_job", _fake_process_job)

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

    class _FakeResult:
        id = "fake-task-id"

    def _fake_process_job(*a, **kw):
        calls.append((a, kw))
        return _FakeResult()

    monkeypatch.setattr(api, "process_job", _fake_process_job)

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

    class _FakeResult:
        id = "fake-task-id"

    def _fake_process_job(*a, **kw):
        calls.append((a, kw))
        return _FakeResult()

    monkeypatch.setattr(api, "process_job", _fake_process_job)

    client = TestClient(api.app)
    resp = client.post(
        "/predict",
        files={"file": ("scan.nii.gz", b"bytes", "application/octet-stream")},
        data={"sex": "F", "age": "30"},
    )

    assert resp.status_code == 503
    assert not calls


def test_predict_neutralizes_traversal_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    monkeypatch.setattr(api, "load_config", lambda: {"app": {}})
    calls = []

    class _FakeResult:
        id = "fake-task-id"

    def _fake_process_job(*a, **kw):
        calls.append((a, kw))
        return _FakeResult()

    monkeypatch.setattr(api, "process_job", _fake_process_job)

    client = TestClient(api.app)
    resp = client.post(
        "/predict",
        files={
            "file": ("../../../../../../tmp/pwned.nii.gz", b"bytes", "application/octet-stream")
        },
        data={"sex": "F", "age": "30"},
    )

    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    # Written under the job's own input/ dir with a fixed name, nowhere else.
    assert (tmp_path / job_id / "input" / "upload.nii.gz").read_bytes() == b"bytes"
    assert not (tmp_path.parent / "pwned.nii.gz").exists()
    assert len(calls) == 1


def test_predict_rejects_oversize_upload_and_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    monkeypatch.setattr(api, "load_config", lambda: {"app": {"max_upload_size_mb": 1}})
    calls = []

    class _FakeResult:
        id = "fake-task-id"

    def _fake_process_job(*a, **kw):
        calls.append((a, kw))
        return _FakeResult()

    monkeypatch.setattr(api, "process_job", _fake_process_job)

    client = TestClient(api.app)
    oversize_body = b"x" * (2 * 1024 * 1024)  # 2 MiB > the 1 MB cap above
    resp = client.post(
        "/predict",
        files={"file": ("scan.nii.gz", oversize_body, "application/octet-stream")},
        data={"sex": "F", "age": "30"},
    )

    assert resp.status_code == 413
    assert not calls
    # No partial job directory left behind.
    assert list(tmp_path.iterdir()) == []


def test_predict_rejects_bad_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    monkeypatch.setattr(api, "load_config", lambda: {"app": {}})
    calls = []

    class _FakeResult:
        id = "fake-task-id"

    def _fake_process_job(*a, **kw):
        calls.append((a, kw))
        return _FakeResult()

    monkeypatch.setattr(api, "process_job", _fake_process_job)

    client = TestClient(api.app)
    resp = client.post(
        "/predict",
        files={"file": ("scan.exe", b"bytes", "application/octet-stream")},
        data={"sex": "F", "age": "30"},
    )

    assert resp.status_code == 400
    assert not calls


def test_predict_rejects_bad_sex(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    monkeypatch.setattr(api, "load_config", lambda: {"app": {}})
    calls = []

    class _FakeResult:
        id = "fake-task-id"

    def _fake_process_job(*a, **kw):
        calls.append((a, kw))
        return _FakeResult()

    monkeypatch.setattr(api, "process_job", _fake_process_job)

    client = TestClient(api.app)
    resp = client.post(
        "/predict",
        files={"file": ("scan.nii.gz", b"bytes", "application/octet-stream")},
        data={"sex": "X", "age": "30"},
    )

    assert resp.status_code == 400
    assert not calls


def test_predict_rejects_age_below_range(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    monkeypatch.setattr(api, "load_config", lambda: {"app": {}})
    calls = []

    class _FakeResult:
        id = "fake-task-id"

    def _fake_process_job(*a, **kw):
        calls.append((a, kw))
        return _FakeResult()

    monkeypatch.setattr(api, "process_job", _fake_process_job)

    client = TestClient(api.app)
    resp = client.post(
        "/predict",
        files={"file": ("scan.nii.gz", b"bytes", "application/octet-stream")},
        data={"sex": "F", "age": "-500"},
    )

    assert resp.status_code == 400
    assert not calls


def test_predict_rejects_age_above_range(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    monkeypatch.setattr(api, "load_config", lambda: {"app": {}})
    calls = []

    class _FakeResult:
        id = "fake-task-id"

    def _fake_process_job(*a, **kw):
        calls.append((a, kw))
        return _FakeResult()

    monkeypatch.setattr(api, "process_job", _fake_process_job)

    client = TestClient(api.app)
    resp = client.post(
        "/predict",
        files={"file": ("scan.nii.gz", b"bytes", "application/octet-stream")},
        data={"sex": "F", "age": "91"},
    )

    assert resp.status_code == 400
    assert not calls


def test_predict_accepts_boundary_ages(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "get_path", lambda key: tmp_path)
    monkeypatch.setattr(api, "load_config", lambda: {"app": {}})
    calls = []

    class _FakeResult:
        id = "fake-task-id"

    def _fake_process_job(*a, **kw):
        calls.append((a, kw))
        return _FakeResult()

    monkeypatch.setattr(api, "process_job", _fake_process_job)

    client = TestClient(api.app)
    for age in ("18", "90"):
        resp = client.post(
            "/predict",
            files={"file": ("scan.nii.gz", b"bytes", "application/octet-stream")},
            data={"sex": "F", "age": age},
        )
        assert resp.status_code == 202, resp.text
    assert len(calls) == 2
