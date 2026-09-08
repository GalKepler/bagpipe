"""FastAPI app for Pillar 4 (DESIGN.md §6): upload a T1w scan, get predicted
BAG + regional norm comparison back.

Async job queue (Huey/SQLite, `bagpipe.app.queue`) — CAT12 takes tens of
minutes per scan, too long to hold an HTTP request open. `POST /predict`
enqueues and returns a `job_id` immediately; poll `GET /jobs/{job_id}` for
status and, once succeeded, the result. Run a worker with `bag app worker`.

Uploaded imaging data (defaced T1w + raw CAT12 output) is deleted once the
job finishes unless the uploader explicitly opts into retention via
`retain_uploads=true` on `/predict` — `bagpipe.app.queue._delete_imaging`.

Public-abuse protection (deploy/README.md § Public-abuse protection): each
accepted job costs ~an hour of the single GPU this app runs on. `/predict`
requires a solved Cloudflare Turnstile challenge (skipped, with a warning,
if `app.turnstile_secret_key` isn't configured — local/dev use) and rejects
new jobs with 503 once `app.max_queue_depth` jobs are already pending. It
also enforces an upload size cap (`app.max_upload_size_mb`, default 500),
an upload-extension allowlist, and self-reported `sex`/`age` range checks —
this is an unauthenticated public endpoint sitting directly on the open
internet (no reverse proxy in front of it), so every input is untrusted.

This module has no reverse proxy in front of it in production (Cloudflare
Tunnel -> uvicorn directly), so it also owns a catch-all exception handler
that logs the traceback server-side and never leaks one to the client.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from bagpipe.app import turnstile
from bagpipe.app.pages import (
    render_landing,
    render_privacy,
    render_science,
    render_team,
    render_upload,
)
from bagpipe.app.queue import huey, process_job
from bagpipe.app.results_page import render as render_results_page
from bagpipe.core.config import get_path, load_config

logger = logging.getLogger(__name__)

app = FastAPI(title="bagpipe — Brain Age Gap report")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.middleware("http")
async def _no_cache_static(request: Request, call_next):
    """This app has no build step and no content-hashed filenames, so a JS/CSS
    edit at the same URL needs every viewer to actually re-fetch it. Without
    an explicit Cache-Control, Cloudflare fills the gap with its own ~4h
    default for static extensions — both at its edge and via the header it
    forwards to the browser — so a deploy silently doesn't show up for
    anyone with a warm cache. `no-cache` still lets browsers/Cloudflare keep
    a cached copy, it just forces a conditional revalidate (cheap, ETag-
    based) before trusting it, rather than a real cache-busting scheme.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# Lowercase-normalized `uuid.uuid4()` hex form — every route takes `job_id`
# straight from the URL and uses it to build a filesystem path, so this is
# the one gate that keeps a malformed/adversarial path segment out of all of
# them (Starlette already blocks literal "/" in a `{job_id}` path param, but
# validating the whole shape is cheap and closes the sink outright).
_JOB_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)

# filename -> fixed on-disk extension. The client-supplied filename is never
# used for anything except picking one of these; the actual bytes always
# land at a fixed path (`input/upload<ext>`), so a traversal payload in the
# filename (e.g. "../../../etc/passwd") has nothing to act on.
_ALLOWED_UPLOAD_EXTENSIONS = (".nii.gz", ".nii", ".zip")

_VALID_SEX = {"M", "F"}
_MIN_AGE = 18
_MAX_AGE = 90
_UPLOAD_CHUNK_BYTES = 1024 * 1024  # 1 MiB, streamed to avoid buffering a huge upload in memory


@app.get("/", response_class=HTMLResponse)
async def landing_page() -> str:
    return render_landing()


@app.get("/science", response_class=HTMLResponse)
async def science_page() -> str:
    return render_science()


@app.get("/team", response_class=HTMLResponse)
async def team_page() -> str:
    return render_team()


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page() -> str:
    return render_privacy()


@app.get("/upload", response_class=HTMLResponse)
async def upload_page() -> str:
    app_cfg = load_config()["app"]
    return render_upload(
        app_cfg.get("turnstile_site_key"), app_cfg.get("max_upload_size_mb", 100)
    )


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "favicon.ico")


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never let a raw traceback reach the public internet — log it
    server-side and return a clean, generic 500 instead. `HTTPException`s
    (the normal 4xx/503 flow above) never reach here; Starlette handles
    those separately with their own `detail`.
    """
    logger.exception("unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


def _validate_job_id(job_id: str) -> None:
    """Every route below interpolates `job_id` into a filesystem path (and
    `results_page.py` renders it into an HTML attribute) — reject anything
    that isn't a `uuid.uuid4()` shape before it gets near either sink.
    """
    if not _JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=404, detail="unknown job")


def _upload_extension(filename: str | None) -> str:
    """Map an (untrusted) client filename to one of the allowed on-disk
    extensions. Never returns any part of the filename itself — only which
    fixed extension to use — so it can't be used for a path-traversal write.
    """
    name = (filename or "").lower()
    for ext in _ALLOWED_UPLOAD_EXTENSIONS:
        if name.endswith(ext):
            return ext
    raise HTTPException(
        status_code=400,
        detail="Unsupported file type — upload a NIfTI (.nii/.nii.gz) or a DICOM .zip.",
    )


@app.post("/predict", status_code=202)
def predict(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008 — FastAPI's documented Depends-style default
    sex: str = Form(...),  # noqa: B008
    age: float = Form(...),  # noqa: B008 — self-reported, unverified
    email: str | None = Form(None),  # noqa: B008
    retain_uploads: bool = Form(False),  # noqa: B008
    turnstile_token: str | None = Form(None, alias="cf-turnstile-response"),  # noqa: B008
) -> JSONResponse:
    """Upload a T1w NIfTI (`.nii`/`.nii.gz`) or DICOM (`.zip` of a series);
    `sex` is `M` or `F`, `age` is self-reported (used to compute the Brain
    Age Gap; not verified against any ID) and must be 18-90 inclusive.
    Queues the job and returns its `job_id` — poll
    `GET /jobs/{job_id}` for status and the result, or pass `email` to also
    get the PDF report emailed once the job finishes. Imaging data is
    deleted after the job finishes unless `retain_uploads=true`.

    A plain `def` (not `async def`) handler on purpose: FastAPI runs sync
    endpoints in a worker thread, so the blocking upload-stream-to-disk
    below doesn't stall the event loop (and, with it, every other request —
    including `GET /jobs/{id}` status polls — for the duration of the copy).
    """
    app_cfg = load_config()["app"]

    secret_key = app_cfg.get("turnstile_secret_key")
    if secret_key:
        remote_ip = request.client.host if request.client else None
        if not turnstile_token or not turnstile.verify(turnstile_token, secret_key, remote_ip):
            raise HTTPException(status_code=400, detail="anti-abuse challenge failed")
    else:
        logger.warning(
            "app.turnstile_secret_key is not configured — /predict is accepting uploads "
            "with no anti-abuse challenge. Fine for local/dev use only."
        )

    max_queue_depth = app_cfg.get("max_queue_depth", 5)
    if huey.pending_count() >= max_queue_depth:
        raise HTTPException(
            status_code=503,
            detail="Too many scans are already queued for processing. Please try again later.",
        )

    sex = sex.strip().upper()
    if sex not in _VALID_SEX:
        raise HTTPException(status_code=400, detail="sex must be 'M' or 'F'.")
    if not (_MIN_AGE <= age <= _MAX_AGE):
        raise HTTPException(
            status_code=400, detail=f"age must be between {_MIN_AGE} and {_MAX_AGE} (inclusive)."
        )
    extension = _upload_extension(file.filename)

    max_upload_mb = app_cfg.get("max_upload_size_mb", 500)
    max_upload_bytes = int(max_upload_mb) * 1024 * 1024

    job_id = str(uuid.uuid4())
    job_dir = _uploads_root() / job_id
    job_dir.mkdir(parents=True)
    # Fixed filename — the client-supplied name is used only to pick `extension`
    # above, never as (or as part of) a path, so a traversal payload in it does
    # nothing.
    upload_path = job_dir / "input" / f"upload{extension}"
    upload_path.parent.mkdir(parents=True)
    try:
        written = 0
        with upload_path.open("wb") as out:
            while chunk := file.file.read(_UPLOAD_CHUNK_BYTES):
                written += len(chunk)
                if written > max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload exceeds the {max_upload_mb} MB size limit.",
                    )
                out.write(chunk)
    except HTTPException:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise

    work_dir = job_dir / "run"
    result = process_job(
        job_id,
        str(upload_path),
        sex,
        str(work_dir),
        notify_email=email,
        retain_uploads=retain_uploads,
        chronological_age=age,
    )
    # ponytail: huey's task table has occasionally lost a job between enqueue
    # and execution under heavy host CPU load (observed 2026-09-06/07), with
    # no error anywhere — leaves the job stuck "queued" forever. Recording
    # the task id here lets job_status() tell "still queued" apart from
    # "silently dropped" instead of polling blind. Root cause not found; if
    # it recurs once host load is normal, revisit huey's Sqlite consumer.
    (job_dir / "task_id").write_text(result.id)

    return JSONResponse({"job_id": job_id}, status_code=202)


_ORPHAN_GRACE_SECONDS = 300


def _job_task_lost(job_dir: Path) -> bool:
    """True if this job's huey task is no longer queued (dequeued or gone)
    and enough time has passed since submission that it should have written
    a manifest by now if it were actually executing — `run_manifest`'s first
    action is a `mkdir`, so a real in-flight job leaves a trace almost
    instantly. `task_id` missing (jobs created before this check existed)
    always reads as "still queued" — no way to check those retroactively.
    """
    task_id_path = job_dir / "task_id"
    if not task_id_path.exists():
        return False
    if time.time() - task_id_path.stat().st_mtime < _ORPHAN_GRACE_SECONDS:
        return False
    task_id = task_id_path.read_text().strip()
    still_pending = any(t.id == task_id for t in huey.pending())
    return not still_pending


@app.get("/jobs/{job_id}")
async def job_status(job_id: str) -> JSONResponse:
    """Returns the job's manifest: `status` (`queued`/`running`/`succeeded`/
    `failed`), stage history, and — once succeeded — the prediction.

    `queued` (200, `stages: []`) covers the normal window between the job
    dir being created and the worker picking it up and writing the first
    manifest — with one worker and ~an hour per job, that's the common case
    for anyone queued behind another upload, not an edge case. Only a
    `job_id` with no directory at all is a real 404.
    """
    _validate_job_id(job_id)
    job_dir = _uploads_root() / job_id
    manifest_path = job_dir / "run" / "manifest.json"
    if not manifest_path.exists():
        if not job_dir.is_dir():
            raise HTTPException(status_code=404, detail="unknown or not-yet-started job")
        if _job_task_lost(job_dir):
            orphan_logged = job_dir / "orphan_logged"
            if not orphan_logged.exists():
                from bagpipe.app.failure_log import log_failure

                log_failure(job_id, "queue", "task_lost", "huey task dequeued but never executed")
                orphan_logged.touch()
            return JSONResponse(
                {
                    "job_id": job_id,
                    "status": "failed",
                    "stages": [],
                    "error": {
                        "user_message": (
                            "Job was lost before processing could start. Please try again."
                        )
                    },
                }
            )
        return JSONResponse({"job_id": job_id, "status": "queued", "stages": []})

    manifest = json.loads(manifest_path.read_text())
    response: dict = {"job_id": job_id, "status": manifest["status"], "stages": manifest["stages"]}
    if manifest["status"] == "failed":
        response["error"] = manifest["error"]
    elif manifest["status"] == "succeeded":
        prediction_path = manifest_path.parent / "predict" / "prediction.json"
        response["result"] = json.loads(prediction_path.read_text())

    return JSONResponse(response)


@app.get("/jobs/{job_id}/view", response_class=HTMLResponse)
async def job_results_page(job_id: str) -> str:
    """The interactive results page — clickable brain map + z-scores, browser
    only (the emailed PDF stays static). 404 until the job succeeds.
    """
    _validate_job_id(job_id)
    manifest_path = _uploads_root() / job_id / "run" / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="unknown or not-yet-started job")

    manifest = json.loads(manifest_path.read_text())
    if manifest["status"] != "succeeded":
        raise HTTPException(status_code=404, detail="job hasn't succeeded (yet)")

    prediction = json.loads((manifest_path.parent / "predict" / "prediction.json").read_text())
    qc_metrics = next((s["metrics"] for s in manifest["stages"] if s["name"] == "qc_gate"), {})
    volume_available = _job_t1_path(job_id).exists()
    return render_results_page(prediction, qc_metrics, job_id, volume_available)


@app.get("/jobs/{job_id}/volume/t1.nii")
async def job_volume(job_id: str) -> FileResponse:
    """The MNI-normalized whole-head T1 (CAT12's `mri/wm*.nii`) for the
    results page's NiiVue viewer — same space as `atlas_volume_file`, so the
    two load as one scene. Only exists if the uploader opted into retention
    (`retain_uploads=true`); imaging data is deleted after the job finishes
    otherwise (`bagpipe.app.queue._delete_imaging`).
    """
    _validate_job_id(job_id)
    t1_path = _job_t1_path(job_id)
    if not t1_path.exists():
        raise HTTPException(status_code=404, detail="volume not available for this job")
    return FileResponse(t1_path, media_type="application/octet-stream")


@app.get("/jobs/{job_id}/report.pdf")
async def job_report_pdf(job_id: str) -> FileResponse:
    """The same PDF report emailed on completion — the only way to fetch it
    for an uploader who left `email` blank. Generated by the `report` stage
    (`bagpipe.app.report`, outside this module) at `run/report/report.pdf`.
    """
    _validate_job_id(job_id)
    report_path = _uploads_root() / job_id / "run" / "report" / "report.pdf"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="report not available for this job")
    return FileResponse(report_path, media_type="application/pdf")


@app.get("/atlas/volume.nii")
async def atlas_volume() -> FileResponse:
    """The Schaefer+Tian regional atlas volume (same file baked into
    `container/cat12.sif` and read by `bagpipe.app.pipeline.features`) —
    shared, not per-job, served for the results page's NiiVue overlay layer.
    """
    return FileResponse(
        get_path("atlas_volume_file"),
        media_type="application/octet-stream",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


def _job_t1_path(job_id: str) -> Path:
    return _uploads_root() / job_id / "run" / "cat12" / "mri" / "wmT1w.nii"


def _uploads_root() -> Path:
    uploads_dir = get_path("uploads_dir")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    return uploads_dir
