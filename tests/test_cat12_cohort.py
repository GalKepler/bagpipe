"""Pure-logic checks for the cat12-cohort driver: raw-T1w filtering (must
exclude every CAT12 output naming convention, not just some), input
staging (the mechanism that replaced CAT12's own BIDS-redirect field,
which turned out not to exist in this CAT26 build), chunking, and the
resumability ledger (the actual fail-safe mechanism — a subject already
succeeded must never be resubmitted, and real output on disk must be
trusted over ledger history). No apptainer invoked."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path

from bagpipe.preprocess.cat12_cohort import (
    _REQUIRED_SURFACE_FILE_PREFIXES,
    _chunks,
    _ensure_staged,
    _expected_output_xml,
    _find_raw_t1w,
    _has_full_surface_output,
    _is_complete,
    _ledger_connect,
    _ledger_mark,
    _ledger_pending,
    _ledger_reconcile_existing_outputs,
    _ledger_seed,
    _staged_input_path,
    _stem,
)


def _touch_full_surface_output(t1w: Path, bids_root: Path, out_dir: Path) -> None:
    staged = _staged_input_path(t1w, bids_root, out_dir)
    surf_dir = staged.parent / "surf"
    surf_dir.mkdir(parents=True, exist_ok=True)
    stem = _stem(t1w)
    for prefix in _REQUIRED_SURFACE_FILE_PREFIXES:
        (surf_dir / f"lh.{prefix}.{stem}").touch()


def test_find_raw_t1w_excludes_all_cat12_output_prefixes(tmp_path: Path):
    anat = tmp_path / "sub-S001" / "ses-20260101" / "anat"
    anat.mkdir(parents=True)
    raw = anat / "sub-S001_ses-20260101_rec-norm_run-01_T1w.nii"
    raw.touch()
    for prefix in ["mwp1", "mwp2", "wc", "wm", "p0", "ct", "cat_", "catROI_", "catlog_", "y_"]:
        (anat / f"{prefix}sub-S001_ses-20260101_T1w.nii").touch()

    found = _find_raw_t1w(tmp_path)

    assert found == [raw]


def test_find_raw_t1w_prefers_rec_norm_run01_over_other_variants(tmp_path: Path):
    anat = tmp_path / "sub-S002" / "ses-20260101" / "anat"
    anat.mkdir(parents=True)
    preferred = anat / "sub-S002_ses-20260101_rec-norm_run-01_T1w.nii"
    preferred.touch()
    (anat / "sub-S002_ses-20260101_acq-defaced_run-01_T1w.nii").touch()
    (anat / "sub-S002_ses-20260101_rec-norm_run-02_T1w.nii").touch()

    assert _find_raw_t1w(tmp_path) == [preferred]


def test_find_raw_t1w_skips_ambiguous_session(tmp_path: Path):
    anat = tmp_path / "sub-S003" / "ses-20260101" / "anat"
    anat.mkdir(parents=True)
    (anat / "sub-S003_ses-20260101_acq-defaced_run-01_T1w.nii").touch()
    (anat / "sub-S003_ses-20260101_run-02_T1w.nii").touch()

    assert _find_raw_t1w(tmp_path) == []


def test_find_raw_t1w_uses_single_file_when_unambiguous(tmp_path: Path):
    anat = tmp_path / "sub-S004" / "ses-20260101" / "anat"
    anat.mkdir(parents=True)
    only = anat / "sub-S004_ses-20260101_T1w.nii"
    only.touch()

    assert _find_raw_t1w(tmp_path) == [only]


def test_staged_input_path_mirrors_bids_structure(tmp_path: Path):
    bids_root = tmp_path / "BIDS"
    out_dir = tmp_path / "derivatives" / "CAT12.new"
    t1w = bids_root / "sub-S001" / "ses-20260101" / "anat" / "sub-S001_ses-20260101_T1w.nii"

    staged = _staged_input_path(t1w, bids_root, out_dir)

    assert staged == out_dir / "sub-S001" / "ses-20260101" / "anat" / t1w.name


def test_ensure_staged_creates_symlink_to_the_real_file(tmp_path: Path):
    bids_root = tmp_path / "BIDS"
    out_dir = tmp_path / "derivatives"
    anat = bids_root / "sub-S001" / "ses-20260101" / "anat"
    anat.mkdir(parents=True)
    t1w = anat / "sub-S001_ses-20260101_T1w.nii"
    t1w.write_text("fake nifti bytes")

    staged = _ensure_staged(t1w, bids_root, out_dir)

    assert staged.is_symlink()
    assert staged.resolve() == t1w.resolve()
    assert staged.read_text() == "fake nifti bytes"  # readable through the symlink

    # idempotent — calling again doesn't error or re-create
    staged_again = _ensure_staged(t1w, bids_root, out_dir)
    assert staged_again == staged


def test_chunks_splits_evenly_and_leaves_remainder():
    items = list(range(9))

    chunked = _chunks(items, 4)

    assert chunked == [[0, 1, 2, 3], [4, 5, 6, 7], [8]]


def _setup_ledger_fixture(tmp_path: Path):
    bids_root = tmp_path / "BIDS"
    out_dir = tmp_path / "derivatives"
    anat = bids_root / "sub-S001" / "ses-20260101" / "anat"
    anat.mkdir(parents=True)
    t1w = anat / "sub-S001_ses-20260101_T1w.nii"
    t1w.touch()
    ledger = _ledger_connect(tmp_path / "ledger.sqlite")
    return bids_root, out_dir, t1w, ledger


def test_succeeded_subject_never_resubmitted_after_resume(tmp_path: Path):
    bids_root, out_dir, t1w, conn = _setup_ledger_fixture(tmp_path)
    with closing(conn):
        _ledger_seed(conn, [t1w])
        _ledger_mark(conn, t1w, "succeeded", None)

        pending = _ledger_pending(conn, max_retries=2)

        assert pending == []


def test_ledger_reconciles_from_real_disk_output_even_if_history_lost(tmp_path: Path):
    """The core fail-safe guarantee: if the driver process died before
    recording a result, the real output file on disk — not ledger
    history — decides whether a subject counts as done."""
    bids_root, out_dir, t1w, conn = _setup_ledger_fixture(tmp_path)
    with closing(conn):
        _ledger_seed(conn, [t1w])  # still 'queued' — no result was ever recorded

        expected_xml = _expected_output_xml(t1w, bids_root, out_dir)
        expected_xml.parent.mkdir(parents=True)
        expected_xml.touch()  # CAT12 actually finished this one before the crash
        _touch_full_surface_output(t1w, bids_root, out_dir)

        reconciled = _ledger_reconcile_existing_outputs(conn, bids_root, out_dir)
        pending = _ledger_pending(conn, max_retries=2)

        assert reconciled == 1
        assert pending == []


def test_ledger_does_not_reconcile_subject_missing_surface_output(tmp_path: Path):
    """A subject can pass the core cat_*.xml check while surfextract failed
    independently (a real, separate failure mode, not just a config toggle)
    — such a subject must stay pending, not get marked succeeded missing
    the surface panel the cohort run is meant to produce."""
    bids_root, out_dir, t1w, conn = _setup_ledger_fixture(tmp_path)
    with closing(conn):
        _ledger_seed(conn, [t1w])

        expected_xml = _expected_output_xml(t1w, bids_root, out_dir)
        expected_xml.parent.mkdir(parents=True)
        expected_xml.touch()
        # no surface output touched — simulates a subject whose segmentation
        # succeeded but surfextract failed/never ran

        assert not _is_complete(t1w, bids_root, out_dir)
        assert not _has_full_surface_output(t1w, bids_root, out_dir)

        reconciled = _ledger_reconcile_existing_outputs(conn, bids_root, out_dir)
        pending = _ledger_pending(conn, max_retries=2)

        assert reconciled == 0
        assert pending == [t1w]


def test_failed_subject_retried_until_max_retries_then_left_alone(tmp_path: Path):
    bids_root, out_dir, t1w, conn = _setup_ledger_fixture(tmp_path)
    with closing(conn):
        _ledger_seed(conn, [t1w])
        _ledger_mark(conn, t1w, "failed", "boom")
        assert _ledger_pending(conn, max_retries=2) == [t1w]  # attempt 1 of 2, still eligible

        _ledger_mark(conn, t1w, "failed", "boom again")
        assert _ledger_pending(conn, max_retries=2) == []  # attempt 2 of 2, exhausted
