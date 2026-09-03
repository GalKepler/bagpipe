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
new jobs with 503 once `app.max_queue_depth` jobs are already pending.
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from bagpipe.app import turnstile
from bagpipe.app.queue import huey, process_job
from bagpipe.app.results_page import render as render_results_page
from bagpipe.app.upload_page import render as render_upload_page
from bagpipe.core.config import get_path, load_config

app = FastAPI(title="bagpipe — Brain Age Gap report")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def upload_page() -> str:
    site_key = load_config()["app"].get("turnstile_site_key")
    return render_upload_page(site_key)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "favicon.ico")


@app.post("/predict", status_code=202)
async def predict(
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
    Age Gap; not verified against any ID). Queues the job and returns its
    `job_id` — poll
    `GET /jobs/{job_id}` for status and the result, or pass `email` to also
    get the PDF report emailed once the job finishes. Imaging data is
    deleted after the job finishes unless `retain_uploads=true`.
    """
    app_cfg = load_config()["app"]

    secret_key = app_cfg.get("turnstile_secret_key")
    if secret_key:
        remote_ip = request.client.host if request.client else None
        if not turnstile_token or not turnstile.verify(turnstile_token, secret_key, remote_ip):
            raise HTTPException(status_code=400, detail="anti-abuse challenge failed")

    max_queue_depth = app_cfg.get("max_queue_depth", 5)
    if huey.pending_count() >= max_queue_depth:
        raise HTTPException(
            status_code=503,
            detail="Too many scans are already queued for processing. Please try again later.",
        )

    job_id = str(uuid.uuid4())
    job_dir = _uploads_root() / job_id
    job_dir.mkdir(parents=True)
    upload_path = job_dir / "input" / (file.filename or "upload")
    upload_path.parent.mkdir(parents=True)
    with upload_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    work_dir = job_dir / "run"
    process_job(
        job_id,
        str(upload_path),
        sex,
        str(work_dir),
        notify_email=email,
        retain_uploads=retain_uploads,
        chronological_age=age,
    )

    return JSONResponse({"job_id": job_id}, status_code=202)


@app.get("/jobs/{job_id}")
async def job_status(job_id: str) -> JSONResponse:
    """Returns the job's manifest: `status` (`running`/`succeeded`/`failed`),
    stage history, and — once succeeded — the prediction.
    """
    manifest_path = _uploads_root() / job_id / "run" / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="unknown or not-yet-started job")

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
    t1_path = _job_t1_path(job_id)
    if not t1_path.exists():
        raise HTTPException(status_code=404, detail="volume not available for this job")
    return FileResponse(t1_path, media_type="application/octet-stream")


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
