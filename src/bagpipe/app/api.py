"""FastAPI app for Pillar 4 (DESIGN.md §6): upload a T1w scan, get predicted
BAG + regional norm comparison back.

ponytail: synchronous request handling, no job queue/email/PDF report yet —
CAT12 takes tens of minutes per scan, which will time out an HTTP request.
Fine for local testing of the pipeline end-to-end; wire in the Huey queue +
report template + email delivery (DESIGN.md §6) before this is public-facing.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from bagpipe.app.pipeline import BAGResult, PipelineError
from bagpipe.app.pipeline import run as run_pipeline
from bagpipe.core.config import load_config

app = FastAPI(title="bagpipe — Brain Age Gap report")


@app.post("/predict")
async def predict(
    file: UploadFile = File(...),  # noqa: B008 — FastAPI's documented Depends-style default
    sex: str = Form(...),  # noqa: B008
) -> JSONResponse:
    """Upload a T1w NIfTI (`.nii`/`.nii.gz`) or DICOM (`.zip` of a series);
    `sex` is `M` or `F`. Returns predicted age, corrected BAG, and per-region
    z-scores against the SNBB population.
    """
    cfg = load_config()
    retain = cfg["app"]["retain_uploads"]

    with tempfile.TemporaryDirectory(dir=_uploads_root()) as tmp:
        work_dir = Path(tmp)
        upload_path = work_dir / (file.filename or "upload")
        with upload_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)

        try:
            result: BAGResult = run_pipeline(upload_path, sex=sex, work_dir=work_dir / "run")
        except PipelineError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        finally:
            if not retain:
                shutil.rmtree(work_dir, ignore_errors=True)

    return JSONResponse(
        {
            "predicted_age_raw": result.predicted_age_raw,
            "predicted_age_corrected": result.predicted_age_corrected,
            "n_regions_scored": result.n_regions_scored,
            "regional_zscores": result.regional_zscores,
        }
    )


def _uploads_root() -> Path:
    from bagpipe.core.config import get_path

    uploads_dir = get_path("uploads_dir")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    return uploads_dir
