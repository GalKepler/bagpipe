"""Job queue — docs/design_inference_pipeline.md § Worker execution model.

SQLite-backed via Huey (CLAUDE.md tech stack, decided). One task per job;
Huey's own `results` table is the "queue row" the design doc describes
(status/claim/heartbeat handled internally by Huey's consumer — we don't
hand-roll that part). `workspace_path` lives in the manifest, not a separate
queue row, per the design doc's "manifest is sole source of truth" rule.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from huey import SqliteHuey

from bagpipe.core.config import get_path, load_config

huey = SqliteHuey("bagpipe", filename=str(get_path("jobs_db")))


@huey.task()
def process_job(
    job_id: str,
    input_path: str,
    sex: str,
    work_dir: str,
    model_name: str = "stacked",
    notify_email: str | None = None,
    retain_uploads: bool = False,
    chronological_age: float | None = None,
) -> str:
    """Runs the full stage graph for one job, then emails the result if
    `notify_email` was given. Returns the job's status string; full detail is
    read back from the manifest (`GET /jobs/{job_id}`), not the task result,
    so a worker restart never loses job state. `retain_uploads` is the
    uploader's own explicit opt-in (docs/design_inference_pipeline.md §
    Privacy by default) — defaults to False, deleting imaging data after
    the job finishes.
    """
    from bagpipe.app.pipeline import run_manifest

    # run_manifest() normally catches PipelineError internally and returns a
    # "failed" manifest rather than raising (docs/design_inference_pipeline.md
    # § Worker execution model), so `manifest` is essentially always bound
    # after this call. It's still wrapped in try/finally: an unconsenting
    # upload's raw imaging must never survive a bug in that contract, or a
    # crash in the notify/cleanup steps below, either — see the CRITICAL
    # audit finding in the task brief (retained imaging found on disk for
    # jobs with retention_opt_in=false).
    manifest = None
    try:
        manifest = run_manifest(
            Path(input_path),
            sex=sex,
            work_dir=Path(work_dir),
            model_name=model_name,
            job_id=job_id,
            retention_opt_in=retain_uploads,
            chronological_age=chronological_age,
        )

        if manifest.status == "failed":
            from bagpipe.app.failure_log import log_failure

            log_failure(
                job_id, manifest.error.stage, manifest.error.code, manifest.error.message
            )

        if notify_email:
            try:
                _notify(notify_email, Path(work_dir), manifest)
            except Exception:
                # A missing PDF / unreachable SMTP relay must never prevent
                # cleanup from running — log and continue.
                logging.getLogger(__name__).exception(
                    "job %s: notification failed, continuing to cleanup", job_id
                )
    finally:
        if manifest is None or not manifest.input.retention_opt_in:
            _delete_imaging(Path(work_dir))

    return manifest.status


def _delete_imaging(work_dir: Path) -> None:
    """Deletes every imaging artifact for a non-consenting job —
    docs/design_inference_pipeline.md § Privacy by default.

    `work_dir` is the job's `run/` directory (`{uploads_dir}/{job_id}/run`);
    its parent is the job root, which also holds the raw pre-deface upload
    under `input/` (written directly by `bagpipe.app.api`, before the
    pipeline's own `run/input/` copy exists). Both must be removed:

    - `work_dir/anon`    — defaced T1w
    - `work_dir/cat12`   — raw CAT12 output (derived from the defaced T1w,
                            but CAT12's own report/label XMLs can still
                            carry enough detail to be sensitive)
    - `work_dir/ingest`  — **raw, pre-deface** T1w (dcm2niix/NIfTI
                            passthrough output) — previously never deleted;
                            this was the actual bug (audit: 5 real
                            pre-deface volumes retained despite
                            retention_opt_in=false)
    - job_root/input     — the **raw upload as received**, copied by
                            `bagpipe.app.api` before the pipeline ever ran —
                            also never deleted before this fix

    `features/`, `predict/`, `report/`, `manifest.json` (all under
    `work_dir`) are tabular/report outputs, not imaging, and are kept so
    `GET /jobs/{job_id}` and the PDF-report route keep working after
    cleanup.

    Every path removed is verified to resolve under `get_path("uploads_dir")`
    before deletion — a bad `work_dir` (wrong type, symlink, relative-path
    surprise) must never let this walk `rmtree` above the uploads root.
    """
    from bagpipe.core.config import get_path

    uploads_root = get_path("uploads_dir").resolve()
    job_root = work_dir.resolve().parent

    def _safe_rmtree(path: Path) -> None:
        resolved = path.resolve()
        if uploads_root not in resolved.parents:
            # Refuses to delete anything that isn't strictly inside
            # uploads_dir — see docstring above. Never silently no-op past
            # this guard; a broken contract here is worse than leaving
            # imaging on disk, so it's loud in the logs.
            logging.getLogger(__name__).error(
                "refusing to delete %s — not inside uploads_dir (%s)",
                resolved,
                uploads_root,
            )
            return
        shutil.rmtree(resolved, ignore_errors=True)

    for sub in ("anon", "cat12", "ingest"):
        _safe_rmtree(work_dir / sub)
    _safe_rmtree(job_root / "input")


def _notify(notify_email: str, work_dir: Path, manifest) -> None:
    from bagpipe.app import email as email_mod

    cfg = load_config()["app"]
    from_addr = cfg.get("from_address") or "noreply@bagpipe.local"

    # app.public_base_url is the externally reachable origin (the Cloudflare
    # Tunnel hostname in production). Unset in local dev -> the email just
    # omits the link rather than emitting a localhost URL nobody can open.
    base_url = (cfg.get("public_base_url") or "").rstrip("/")
    results_url = f"{base_url}/jobs/{manifest.job_id}/view" if base_url else None

    if manifest.status == "succeeded":
        msg = email_mod.build_success_email(
            notify_email,
            from_addr,
            work_dir / "report" / "report.pdf",
            results_url=results_url,
        )
    else:
        msg = email_mod.build_failure_email(
            notify_email,
            from_addr,
            manifest.error.user_message,
            retained=manifest.input.retention_opt_in,
        )

    email_mod.send(
        msg,
        cfg.get("smtp_host"),
        cfg.get("smtp_port", 25),
        smtp_user=cfg.get("smtp_user"),
        smtp_password=cfg.get("smtp_password"),
    )
