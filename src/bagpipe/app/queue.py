"""Job queue — docs/design_inference_pipeline.md § Worker execution model.

SQLite-backed via Huey (CLAUDE.md tech stack, decided). One task per job;
Huey's own `results` table is the "queue row" the design doc describes
(status/claim/heartbeat handled internally by Huey's consumer — we don't
hand-roll that part). `workspace_path` lives in the manifest, not a separate
queue row, per the design doc's "manifest is sole source of truth" rule.
"""

from __future__ import annotations

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

    manifest = run_manifest(
        Path(input_path),
        sex=sex,
        work_dir=Path(work_dir),
        model_name=model_name,
        job_id=job_id,
        retention_opt_in=retain_uploads,
        chronological_age=chronological_age,
    )

    if notify_email:
        _notify(notify_email, Path(work_dir), manifest)

    if not manifest.input.retention_opt_in:
        _delete_imaging(Path(work_dir))

    return manifest.status


def _delete_imaging(work_dir: Path) -> None:
    """Deletes the imaging derivatives (defaced T1w + raw CAT12 output) once
    a job is done — docs/design_inference_pipeline.md § Privacy by default:
    retention (opt-in) applies to `anon/`/`cat12/` only. `input/` is already
    gone by the end of the anonymize stage regardless of this setting.
    `features/`/`predict/`/`report/`/`manifest.json` are tabular/report
    outputs, not imaging, and stay so `GET /jobs/{job_id}` keeps working.
    """
    for sub in ("anon", "cat12"):
        shutil.rmtree(work_dir / sub, ignore_errors=True)


def _notify(notify_email: str, work_dir: Path, manifest) -> None:
    from bagpipe.app import email as email_mod

    cfg = load_config()["app"]
    from_addr = cfg["from_address"] or "noreply@bagpipe.local"

    if manifest.status == "succeeded":
        msg = email_mod.build_success_email(
            notify_email, from_addr, work_dir / "report" / "report.pdf"
        )
    else:
        msg = email_mod.build_failure_email(notify_email, from_addr, manifest.error.user_message)

    email_mod.send(
        msg,
        cfg["smtp_host"],
        cfg["smtp_port"],
        smtp_user=cfg.get("smtp_user"),
        smtp_password=cfg.get("smtp_password"),
    )
