"""FastAPI app for Pillar 4 (DESIGN.md §6): upload a T1w scan, get predicted
BAG + regional norm comparison back.

Async job queue (Huey/SQLite, `bagpipe.app.queue`) — CAT12 takes tens of
minutes per scan, too long to hold an HTTP request open. `POST /predict`
enqueues and returns a `job_id` immediately; poll `GET /jobs/{job_id}` for
status and, once succeeded, the result. Run a worker with `bag app worker`.

ponytail: retention/deletion of the workspace after a client has fetched the
result isn't wired yet — Phase 4's consent/deletion logic is its own task.
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from bagpipe.app.queue import process_job
from bagpipe.core.config import get_path

app = FastAPI(title="bagpipe — Brain Age Gap report")


@app.post("/predict", status_code=202)
async def predict(
    file: UploadFile = File(...),  # noqa: B008 — FastAPI's documented Depends-style default
    sex: str = Form(...),  # noqa: B008
    email: str | None = Form(None),  # noqa: B008
) -> JSONResponse:
    """Upload a T1w NIfTI (`.nii`/`.nii.gz`) or DICOM (`.zip` of a series);
    `sex` is `M` or `F`. Queues the job and returns its `job_id` — poll
    `GET /jobs/{job_id}` for status and the result, or pass `email` to also
    get the PDF report emailed once the job finishes.
    """
    job_id = str(uuid.uuid4())
    job_dir = _uploads_root() / job_id
    job_dir.mkdir(parents=True)
    upload_path = job_dir / "input" / (file.filename or "upload")
    upload_path.parent.mkdir(parents=True)
    with upload_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    work_dir = job_dir / "run"
    process_job(job_id, str(upload_path), sex, str(work_dir), notify_email=email)

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


def _uploads_root() -> Path:
    uploads_dir = get_path("uploads_dir")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    return uploads_dir
