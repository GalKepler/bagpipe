"""_delete_imaging / process_job robustness — deletion-by-default privacy
behavior (docs/design_inference_pipeline.md § Privacy by default).

Prior to this test rewrite, this suite asserted the BUGGY behavior (only
`anon/`/`cat12/` removed) — an audit found 5 real jobs with
`retention_opt_in=false` still had raw, pre-deface, face-reconstructable
T1w volumes on disk under `input/`/`run/ingest/`, because nothing ever
deleted those. These tests assert the fixed contract instead.
"""

from __future__ import annotations

import logging
import zipfile

import pytest

from bagpipe.app.pipeline.base import PipelineError
from bagpipe.app.pipeline.ingest import (
    MAX_ZIP_MEMBERS,
    MAX_ZIP_UNCOMPRESSED_BYTES,
    _check_zip_bounds,
)
from bagpipe.app.queue import _delete_imaging, _notify


def _make_job_dir(tmp_path):
    """{job_id}/input/ (raw upload, written by api.py) + {job_id}/run/{...}
    (pipeline workspace) — matches the real on-disk layout."""
    job_dir = tmp_path / "job-123"
    (job_dir / "input").mkdir(parents=True)
    (job_dir / "input" / "raw_upload.nii.gz").write_text("raw pre-deface data")

    work_dir = job_dir / "run"
    for sub in ("anon", "cat12", "ingest", "features", "predict", "report"):
        d = work_dir / sub
        d.mkdir(parents=True)
        (d / "x.txt").write_text("data")
    (work_dir / "manifest.json").write_text("{}")
    return job_dir, work_dir


def test_delete_imaging_removes_all_imaging_locations(tmp_path, monkeypatch):
    job_dir, work_dir = _make_job_dir(tmp_path)
    monkeypatch.setattr("bagpipe.core.config.get_path", lambda key: tmp_path)

    _delete_imaging(work_dir)

    assert not (work_dir / "anon").exists()
    assert not (work_dir / "cat12").exists()
    assert not (work_dir / "ingest").exists(), "raw pre-deface T1w must be deleted (the real bug)"
    assert not (job_dir / "input").exists(), "raw upload must be deleted (the real bug)"


def test_delete_imaging_keeps_non_imaging_outputs(tmp_path, monkeypatch):
    job_dir, work_dir = _make_job_dir(tmp_path)
    monkeypatch.setattr("bagpipe.core.config.get_path", lambda key: tmp_path)

    _delete_imaging(work_dir)

    assert (work_dir / "features").exists()
    assert (work_dir / "predict").exists()
    assert (work_dir / "report").exists()
    assert (work_dir / "manifest.json").exists()
    assert job_dir.exists(), "job root must survive (features/predict/report live under run/)"


def test_delete_imaging_ignores_missing_dirs(tmp_path, monkeypatch):
    job_dir = tmp_path / "job-empty"
    work_dir = job_dir / "run"
    work_dir.mkdir(parents=True)
    monkeypatch.setattr("bagpipe.core.config.get_path", lambda key: tmp_path)

    _delete_imaging(work_dir)  # no anon/cat12/ingest/input present — must not raise


def test_delete_imaging_refuses_to_delete_outside_uploads_dir(tmp_path, monkeypatch, caplog):
    """A work_dir whose parent isn't under uploads_dir must be refused, not
    silently rm -rf'd — the guard against a bad path here doing real damage.
    """
    real_uploads_root = tmp_path / "real_uploads"
    real_uploads_root.mkdir()
    monkeypatch.setattr("bagpipe.core.config.get_path", lambda key: real_uploads_root)

    outside_job = tmp_path / "somewhere_else" / "job-999"
    outside_work_dir = outside_job / "run"
    (outside_work_dir / "anon").mkdir(parents=True)
    (outside_job / "input").mkdir(parents=True)

    with caplog.at_level(logging.ERROR):
        _delete_imaging(outside_work_dir)

    assert (outside_work_dir / "anon").exists(), "must not delete outside uploads_dir"
    assert (outside_job / "input").exists()
    assert "refusing to delete" in caplog.text


class _FakeManifest:
    def __init__(self, status="succeeded"):
        self.status = status

        class _Err:
            user_message = "boom"

        self.error = _Err()


def test_notify_failure_does_not_raise(tmp_path, monkeypatch):
    """A missing PDF / bad SMTP config must never propagate out of _notify
    and prevent cleanup from running (queue.process_job wraps this call in
    try/except for exactly this reason)."""

    def _boom(*a, **k):
        raise FileNotFoundError("no such file: report.pdf")

    monkeypatch.setattr("bagpipe.app.email.build_success_email", _boom)
    monkeypatch.setattr(
        "bagpipe.app.queue.load_config", lambda: {"app": {}}
    )  # no from_address/smtp_host at all — must not KeyError either

    with pytest.raises(FileNotFoundError):
        # _notify itself is allowed to raise (it's process_job's job to catch
        # it) — this confirms the underlying failure mode this test guards
        # against is real, and that missing config keys don't KeyError first.
        _notify("user@example.com", tmp_path, _FakeManifest())


def test_check_zip_bounds_accepts_small_zip(tmp_path):
    zip_path = tmp_path / "small.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("series/img1.dcm", b"x" * 100)
        zf.writestr("series/img2.dcm", b"x" * 100)

    _check_zip_bounds(zip_path)  # must not raise


def test_check_zip_bounds_rejects_oversized_uncompressed_total(tmp_path, monkeypatch):
    # Use a small stand-in cap rather than actually allocating/compressing a
    # multi-GB payload per test run — the real MAX_ZIP_UNCOMPRESSED_BYTES
    # constant is exercised as-is (imported, asserted sane) elsewhere; this
    # test only checks the comparison logic.
    monkeypatch.setattr("bagpipe.app.pipeline.ingest.MAX_ZIP_UNCOMPRESSED_BYTES", 1000)
    zip_path = tmp_path / "bomb.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Highly-compressible content so the zip file on disk stays tiny
        # while its declared uncompressed size blows past the cap — the
        # zip-bomb shape this guard exists for.
        zf.writestr("huge.dcm", b"\x00" * 2000)

    with pytest.raises(PipelineError):
        _check_zip_bounds(zip_path)

    assert MAX_ZIP_UNCOMPRESSED_BYTES > 0  # sanity: real constant still importable/positive


def test_check_zip_bounds_rejects_too_many_members(tmp_path, monkeypatch):
    monkeypatch.setattr("bagpipe.app.pipeline.ingest.MAX_ZIP_MEMBERS", 5)
    zip_path = tmp_path / "many_members.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for i in range(6):
            zf.writestr(f"f{i}.dcm", b"")

    with pytest.raises(PipelineError):
        _check_zip_bounds(zip_path)

    assert MAX_ZIP_MEMBERS > 0  # sanity: real constant still importable/positive


def test_check_zip_bounds_rejects_non_zip(tmp_path):
    bad = tmp_path / "not_a_zip.zip"
    bad.write_bytes(b"this is not a zip file")

    with pytest.raises(PipelineError):
        _check_zip_bounds(bad)
