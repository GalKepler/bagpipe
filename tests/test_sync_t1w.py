"""Pure-logic checks for sync_t1w: copies only the best T1w per new
session from the SMB source into the local mirror, skips sessions already
present locally, skips ambiguous sessions. No SMB/network access."""

from __future__ import annotations

from pathlib import Path

import yaml

from bagpipe.preprocess.sync_t1w import run


def _write_config(tmp_path: Path, local_root: Path) -> Path:
    config = {"bids_root": str(local_root)}
    config_path = tmp_path / "cat12_cohort.yaml"
    config_path.write_text(yaml.dump(config))
    return config_path


def test_sync_copies_best_t1w_for_new_session(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    local_root = tmp_path / "local"
    anat = source_root / "sub-S001" / "ses-20260101" / "anat"
    anat.mkdir(parents=True)
    preferred = anat / "sub-S001_ses-20260101_rec-norm_run-01_T1w.nii.gz"
    preferred.write_bytes(b"data")
    (anat / "sub-S001_ses-20260101_acq-defaced_run-01_T1w.nii.gz").write_bytes(b"data")

    monkeypatch.setattr("bagpipe.preprocess.sync_t1w.get_path", lambda key: source_root)

    summary = run(_write_config(tmp_path, local_root))

    copied = local_root / "sub-S001" / "ses-20260101" / "anat" / preferred.name
    assert copied.exists()
    assert summary == {
        "sessions_scanned": 1,
        "copied": 1,
        "already_present": 0,
        "skipped_ambiguous": 0,
    }


def test_sync_skips_session_already_present_locally(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    local_root = tmp_path / "local"
    src_anat = source_root / "sub-S002" / "ses-20260101" / "anat"
    src_anat.mkdir(parents=True)
    (src_anat / "sub-S002_ses-20260101_T1w.nii.gz").write_bytes(b"data")

    local_anat = local_root / "sub-S002" / "ses-20260101" / "anat"
    local_anat.mkdir(parents=True)
    existing = local_anat / "sub-S002_ses-20260101_T1w.nii"
    existing.write_bytes(b"already here")

    monkeypatch.setattr("bagpipe.preprocess.sync_t1w.get_path", lambda key: source_root)

    summary = run(_write_config(tmp_path, local_root))

    assert existing.read_bytes() == b"already here"  # untouched
    assert summary["already_present"] == 1
    assert summary["copied"] == 0


def test_sync_skips_ambiguous_session(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    local_root = tmp_path / "local"
    anat = source_root / "sub-S003" / "ses-20260101" / "anat"
    anat.mkdir(parents=True)
    (anat / "sub-S003_ses-20260101_acq-defaced_run-01_T1w.nii.gz").write_bytes(b"data")
    (anat / "sub-S003_ses-20260101_run-02_T1w.nii.gz").write_bytes(b"data")

    monkeypatch.setattr("bagpipe.preprocess.sync_t1w.get_path", lambda key: source_root)

    summary = run(_write_config(tmp_path, local_root))

    assert summary["skipped_ambiguous"] == 1
    assert summary["copied"] == 0
    assert not (local_root / "sub-S003").exists()
