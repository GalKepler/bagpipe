"""Bulk-reprocess the SNBB BIDS tree through container/cat12.sif — the same
image bagpipe.app.pipeline.segment uses for inference — so segmentation
params can't silently drift between training and serving (DESIGN.md §6).

Fail-safe by design: a SQLite ledger (one row per T1w file) tracks
queued/succeeded/failed status, updated incrementally as each job
completes — not just at the end. Re-running `run()` after any interruption
(crash, OOM, Ctrl+C, reboot) picks up exactly where it left off: already-
succeeded subjects are never resubmitted, and — as a second, independent
safety net — every subject's real output on disk is checked before
deciding whether to (re)run it, so even a corrupted/deleted ledger can't
cause already-completed work to be silently lost or redone. One subject
failing (hang, OOM, corrupt scan) never takes down its neighbors: batches
are small, jobs run with a hard wall-clock timeout and get killed cleanly,
and failures/timeouts are retried up to `max_retries` before being left
for manual triage — they never block the rest of the cohort.

`bag preprocess cat12-cohort --config config/cat12_cohort.yaml`
`bag preprocess cat12-cohort-status --config config/cat12_cohort.yaml`
"""

from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import yaml

from bagpipe.core.config import get_path

LEDGER_FILENAME = ".bagpipe_cat12_ledger.sqlite"
DEFAULT_TIMEOUT_MINUTES = 90  # matches docs/design_inference_pipeline.md's segment-stage default
DEFAULT_MAX_RETRIES = 2


def _resolve_bids_root(config: dict) -> Path:
    return Path(config["bids_root"]) if config.get("bids_root") else get_path("bids_root")


def _resolve_apptainer_image(config: dict) -> Path:
    return (
        Path(config["apptainer_image"])
        if config.get("apptainer_image")
        else get_path("cat12_apptainer_image")
    )


def _select_best_t1w(files: list[Path], anat_dir: Path) -> Path | None:
    """One T1w per session, matching the maintainer's prior
    find_t1w_for_cat12.py selection: prefer rec-norm/non-defaced/run-01;
    else the only file if unambiguous; else skip (ambiguous — multi-run or
    defaced variants with no clear winner, needs a human to disambiguate).
    """
    preferred = [
        f
        for f in files
        if "rec-norm" in f.name and "acq-defaced" not in f.name and "run-01" in f.name
    ]
    if preferred:
        return preferred[0]
    if len(files) == 1:
        return files[0]
    print(f"skip (ambiguous, {len(files)} T1w): {anat_dir}")
    return None


def _find_raw_t1w(bids_root: Path) -> list[Path]:
    """Raw BIDS T1w files only, one per session — every CAT12 output
    prefixes the filename (mwp1sub-..., cat_sub-..., catROI_sub-..., ...),
    so a bare "sub-*_T1w" match (via the glob pattern itself) already
    excludes them, verified against a real derivatives tree, 2026-08-21.
    A session can have multiple raw T1w files (multi-run, defaced variant)
    — queuing all of them double-processes the session and leaves
    ingest_cat12_cohort.collect_rows picking an arbitrary one
    (`report_xmls[0]`); `_select_best_t1w` disambiguates instead.
    """
    selected = []
    for anat_dir in sorted({p.parent for p in bids_root.glob("sub-*/ses-*/anat/sub-*_T1w.nii*")}):
        files = sorted(anat_dir.glob("sub-*_T1w.nii*"))
        best = _select_best_t1w(files, anat_dir)
        if best is not None:
            selected.append(best)
    return selected


def _stem(t1w_path: Path) -> str:
    name = t1w_path.name
    return name[: -len(".nii.gz")] if name.endswith(".nii.gz") else name[: -len(".nii")]


def _staged_input_path(t1w_path: Path, bids_root: Path, output_derivatives_dir: Path) -> Path:
    """Mirrors the input's sub-X/ses-Y/anat position under output_derivatives_dir.
    CAT12's own BIDS-redirect field (BIDS.BIDSyes.BIDSfolder) doesn't exist in
    this CAT26 build's batch schema at all — confirmed via a real run,
    2026-08-21 ("Item BIDS: No field(s) named BIDSyes"), the same field an
    older CAT12/SPM12 build's cat12_runner_new.m relied on. Rather than chase
    another moving-target field name, this reuses the same trick
    bagpipe.app.pipeline.segment already uses for inference: stage the input
    at its desired output location and let classic mode (BIDSno=0) write
    mri/report/label right there — no redirect field needed at all.
    """
    rel = t1w_path.parent.relative_to(bids_root)  # sub-X/ses-Y/anat
    return output_derivatives_dir / rel / t1w_path.name


def _ensure_staged(t1w_path: Path, bids_root: Path, output_derivatives_dir: Path) -> Path:
    staged = _staged_input_path(t1w_path, bids_root, output_derivatives_dir)
    if not staged.exists():
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.symlink_to(t1w_path)
    return staged


def _expected_output_xml(t1w_path: Path, bids_root: Path, output_derivatives_dir: Path) -> Path:
    """CAT12 writes report/cat_<stem>.xml on successful completion (classic
    mode, mri/report/label subdirs next to the input) — the same completion
    signal bagpipe.app.pipeline.segment checks for a single inference run,
    confirmed via a real smoke test 2026-08-21.
    """
    staged = _staged_input_path(t1w_path, bids_root, output_derivatives_dir)
    return staged.parent / "report" / f"cat_{_stem(t1w_path)}.xml"


# The surfextract per-vertex metrics (job 2, container/cat12.def, 2026-08-24
# — see docs/cat12_container_spec.md §4d) — the file-prefix half of
# bagpipe.app.surface_atlas.SURFACE_METRICS, minus thickness (already
# required transitively: surfextract needs a central surface, which only
# exists once thickness estimation already succeeded).
_REQUIRED_SURFACE_FILE_PREFIXES = ("gyrification", "depth", "fractaldimension", "area")


def _has_full_surface_output(t1w_path: Path, bids_root: Path, output_derivatives_dir: Path) -> bool:
    """A subject can pass `_expected_output_xml` (core segmentation/ROI
    succeeded) while surfextract failed independently for that subject
    (surface reconstruction is its own real failure mode, not just a
    config toggle) — checked separately so a subject only counts as fully
    done once every feature this cohort run is actually meant to produce
    is present, not just the core cat_*.xml. lh-only check (like the
    notebook's own scan) — surfextract always produces both hemispheres
    together or neither."""
    staged = _staged_input_path(t1w_path, bids_root, output_derivatives_dir)
    surf_dir = staged.parent / "surf"
    stem = _stem(t1w_path)
    return surf_dir.is_dir() and all(
        (surf_dir / f"lh.{prefix}.{stem}").exists() for prefix in _REQUIRED_SURFACE_FILE_PREFIXES
    )


def _is_complete(t1w_path: Path, bids_root: Path, output_derivatives_dir: Path) -> bool:
    """The real "done" check this cohort driver uses to mark a subject
    succeeded/reconciled — core CAT12 output plus the full surfextract
    panel, not just the former (see `_has_full_surface_output`)."""
    return _expected_output_xml(
        t1w_path, bids_root, output_derivatives_dir
    ).exists() and _has_full_surface_output(t1w_path, bids_root, output_derivatives_dir)


def _chunks(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _ledger_connect(ledger_path: Path) -> sqlite3.Connection:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        ledger_path, isolation_level=None
    )  # autocommit — every write durable immediately
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subjects (
            t1w_path TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            updated_at TEXT
        )
        """
    )
    return conn


def _ledger_seed(conn: sqlite3.Connection, files: list[Path]) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO subjects (t1w_path, status, updated_at) VALUES (?, 'queued', ?)",
        [(str(f), datetime.now(UTC).isoformat()) for f in files],
    )


def _ledger_reconcile_existing_outputs(
    conn: sqlite3.Connection, bids_root: Path, output_derivatives_dir: Path
) -> int:
    """Independent of ledger history: for anything not already marked
    succeeded, check the real filesystem. Covers the case where CAT12
    finished a subject but the driver process died before recording it —
    real output on disk is always the ground truth, the ledger is a
    cache over it for speed.
    """
    rows = conn.execute("SELECT t1w_path FROM subjects WHERE status != 'succeeded'").fetchall()
    reconciled = 0
    for (path_str,) in rows:
        t1w_path = Path(path_str)
        if _is_complete(t1w_path, bids_root, output_derivatives_dir):
            conn.execute(
                "UPDATE subjects SET status='succeeded', updated_at=? WHERE t1w_path=?",
                (datetime.now(UTC).isoformat(), path_str),
            )
            reconciled += 1
    return reconciled


def _ledger_pending(conn: sqlite3.Connection, max_retries: int) -> list[Path]:
    rows = conn.execute(
        "SELECT t1w_path FROM subjects WHERE status != 'succeeded' AND attempts < ?",
        (max_retries,),
    ).fetchall()
    return [Path(r[0]) for r in rows]


def _ledger_mark(conn: sqlite3.Connection, path: Path, status: str, error: str | None) -> None:
    conn.execute(
        "UPDATE subjects SET status=?, attempts=attempts+1, last_error=?, updated_at=? "
        "WHERE t1w_path=?",
        (status, error, datetime.now(UTC).isoformat(), str(path)),
    )


def _build_combined_add(config: dict) -> str:
    nproc_per_job = config.get("nproc_per_job", 1)
    skip_existing = config.get("skip_existing", True)
    extra_lines = list(config.get("extra_batch_lines", []))

    extra_lines.append(f"matlabbatch{{1}}.spm.tools.cat.estwrite.nproc = {nproc_per_job};")
    # Classic mode, same as inference (bagpipe.app.pipeline.segment) — no
    # BIDS redirect field exists in this CAT26 build's batch schema at all
    # (see _staged_input_path). Explicit even though it's already the
    # shipped default, so a future CAT12 upgrade can't silently flip it.
    extra_lines.append("matlabbatch{1}.spm.tools.cat.estwrite.output.BIDS.BIDSno = 0;")
    if skip_existing:
        extra_lines.append("matlabbatch{1}.spm.tools.cat.estwrite.extopts.admin.lazy = 1;")
    # cat_standalone.sh's -a flag overwrites, it doesn't accumulate across
    # multiple -a invocations (verified against its real parse_args()
    # implementation, 2026-08-21) — every line must go in ONE -a argument.
    return "\n".join(extra_lines)


def _run_job(
    image: Path,
    bids_root: Path,
    output_derivatives_dir: Path,
    combined_add: str,
    files: list[Path],
    timeout_s: int,
) -> tuple[int, str]:
    """Runs one batch. Own process group (start_new_session) so a timeout
    kill takes the whole apptainer/MCR process tree with it, not just the
    top-level apptainer process — a hung MCR runtime is a known real
    failure mode (docs/cat12_container_spec.md §7).
    """
    staged = [_ensure_staged(f, bids_root, output_derivatives_dir) for f in files]
    cmd = [
        "apptainer",
        "run",
        "--writable-tmpfs",  # required — the container still needs a writable
        # overlay for CAT12's own scratch/report files, even though the CTF is
        # now pre-extracted into the image itself (cat12.def %post) rather than
        # self-extracted at runtime.
        "--env",
        # Apptainer leaks the host's $SHELL into the container by default;
        # MATLAB's compiled runtime uses $SHELL to spawn every external
        # system() call — every CAT_* surface/thickness binary among them.
        # The host runs zsh, which doesn't exist in the Ubuntu 22.04
        # container, so every such call failed with execve ENOENT, surfaced
        # by CAT12 as a misleading generic "File permissions/binary
        # compat/antivirus" error — this is the actual root cause of the
        # surface-reconstruction failure noted in config/cat12_cohort.yaml.
        # Root-caused via strace 2026-08-23, verified fixed end-to-end
        # (real subject, full surf+thickness output, no errors).
        "SHELL=/bin/bash",
        "--bind",
        f"{bids_root}:{bids_root}:ro",  # read-only — real T1w files are only ever
        # read through their staged symlinks in output_derivatives_dir now
        "--bind",
        f"{output_derivatives_dir}:{output_derivatives_dir}",
        str(image),
        "-a",
        combined_add,
    ] + [str(s) for s in staged]

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True
    )
    try:
        stdout, _ = proc.communicate(timeout=timeout_s)
        return proc.returncode, stdout
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        stdout, _ = proc.communicate()
        return -1, f"TIMEOUT after {timeout_s}s\n{stdout}"


def run(config_path: str | Path) -> dict:
    config = yaml.safe_load(Path(config_path).read_text())

    if not config.get("output_derivatives_dir"):
        raise ValueError("output_derivatives_dir is required in config/cat12_cohort.yaml")
    output_derivatives_dir = Path(config["output_derivatives_dir"])
    output_derivatives_dir.mkdir(parents=True, exist_ok=True)

    bids_root = _resolve_bids_root(config)
    image = _resolve_apptainer_image(config)
    if not image.exists():
        raise FileNotFoundError(f"apptainer image not found: {image}")

    concurrency = config.get("concurrency", 2)
    subjects_per_job = config.get("subjects_per_job", 4)  # small: bounds blast radius of a bad job
    max_retries = config.get("max_retries", DEFAULT_MAX_RETRIES)
    timeout_s = config.get("timeout_minutes", DEFAULT_TIMEOUT_MINUTES) * 60
    combined_add = _build_combined_add(config)

    ledger_path = (
        Path(config["ledger_path"])
        if config.get("ledger_path")
        else output_derivatives_dir / LEDGER_FILENAME
    )

    with closing(_ledger_connect(ledger_path)) as conn:
        t1w_files = _find_raw_t1w(bids_root)
        _ledger_seed(conn, t1w_files)
        reconciled = _ledger_reconcile_existing_outputs(conn, bids_root, output_derivatives_dir)
        pending = _ledger_pending(conn, max_retries)
        limit = config.get("limit")  # cap how many subjects THIS invocation launches —
        # for validating a config change (e.g. BIDS-redirect output path assumptions)
        # against a couple of real subjects before committing to the full cohort.
        # Doesn't affect the ledger seeding above — the rest stay 'queued' for next time.
        if limit is not None:
            pending = pending[:limit]
        jobs = _chunks(pending, subjects_per_job)

        succeeded_this_run = 0
        failed_this_run = 0
        pool = ThreadPoolExecutor(max_workers=concurrency)
        futures = {
            pool.submit(
                _run_job,
                image,
                bids_root,
                output_derivatives_dir,
                combined_add,
                chunk,
                timeout_s,
            ): chunk
            for chunk in jobs
        }
        try:
            for future in as_completed(futures):
                chunk = futures[future]
                _returncode, output_tail = future.result()
                for f in chunk:
                    if _is_complete(f, bids_root, output_derivatives_dir):
                        _ledger_mark(conn, f, "succeeded", None)
                        succeeded_this_run += 1
                    else:
                        _ledger_mark(conn, f, "failed", output_tail[-2000:])
                        failed_this_run += 1
        except KeyboardInterrupt:
            # Ledger already reflects every job that finished before the
            # interrupt — safe to Ctrl+C and resume later. cancel_futures
            # drops anything not yet started; jobs already running are
            # left to finish or hit their own timeout naturally rather
            # than being killed mid-write (avoids corrupting a subject's
            # output file partway through) — the process may take a
            # moment to fully exit while those finish in the background.
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            pool.shutdown(wait=True)

        counts = dict(
            conn.execute("SELECT status, COUNT(*) FROM subjects GROUP BY status").fetchall()
        )
        exhausted = conn.execute(
            "SELECT t1w_path, last_error FROM subjects WHERE status='failed' AND attempts >= ?",
            (max_retries,),
        ).fetchall()

    return {
        "n_files": len(t1w_files),
        "reconciled_from_disk": reconciled,
        "succeeded_this_run": succeeded_this_run,
        "failed_this_run": failed_this_run,
        "status_counts": counts,
        "permanently_failed": [{"t1w_path": p, "last_error": e} for p, e in exhausted],
    }


def status(config_path: str | Path) -> dict:
    """Read-only progress check — no jobs launched. `bag preprocess cat12-cohort-status`."""
    config = yaml.safe_load(Path(config_path).read_text())
    if not config.get("output_derivatives_dir"):
        raise ValueError("output_derivatives_dir is required in config/cat12_cohort.yaml")
    output_derivatives_dir = Path(config["output_derivatives_dir"])
    ledger_path = (
        Path(config["ledger_path"])
        if config.get("ledger_path")
        else output_derivatives_dir / LEDGER_FILENAME
    )
    if not ledger_path.exists():
        return {"status_counts": {}, "failed": []}

    with closing(_ledger_connect(ledger_path)) as conn:
        counts = dict(
            conn.execute("SELECT status, COUNT(*) FROM subjects GROUP BY status").fetchall()
        )
        max_retries = config.get("max_retries", DEFAULT_MAX_RETRIES)
        failed = conn.execute(
            "SELECT t1w_path, attempts, last_error FROM subjects WHERE status='failed' "
            "ORDER BY attempts >= ? DESC, updated_at DESC",
            (max_retries,),
        ).fetchall()

    return {
        "status_counts": counts,
        "failed": [{"t1w_path": p, "attempts": a, "last_error": e} for p, a, e in failed],
    }
