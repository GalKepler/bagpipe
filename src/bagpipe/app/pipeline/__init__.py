"""Pillar 4 inference pipeline — stage-graph implementation of
docs/design_inference_pipeline.md. Supersedes the old flat `pipeline.py`
(DESIGN.md §6 first working version); `run()` keeps the flat module's
call signature so `bagpipe.app.api` didn't need to change shape.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from bagpipe.app.pipeline.anonymize import AnonymizeStage
from bagpipe.app.pipeline.base import PipelineError
from bagpipe.app.pipeline.features import FeaturesStage
from bagpipe.app.pipeline.ingest import IngestStage
from bagpipe.app.pipeline.models import Environment, JobInput, Manifest
from bagpipe.app.pipeline.predict import PredictStage, _load_production_model
from bagpipe.app.pipeline.qc import QcGateStage
from bagpipe.app.pipeline.report import ReportStage
from bagpipe.app.pipeline.runner import run_stages
from bagpipe.app.pipeline.segment import SegmentStage
from bagpipe.core.config import get_path, load_config

__all__ = ["BAGResult", "PipelineError", "run", "run_manifest"]


@dataclass
class BAGResult:
    predicted_age_raw: float
    predicted_age_corrected: float
    regional_zscores: dict[str, float]
    n_regions_scored: int


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def run_manifest(
    input_path: Path,
    sex: str,
    work_dir: Path,
    model_name: str = "stacked",
    chronological_age: float | None = None,
    job_id: str | None = None,
    retention_opt_in: bool = False,
) -> Manifest:
    """Runs the full stage graph for one job against a fresh workspace under
    `work_dir`. Returns the completed Manifest (check `.status`/`.error`).
    """
    workspace = work_dir
    (workspace / "input").mkdir(parents=True, exist_ok=True)
    upload_dest = workspace / "input" / input_path.name
    shutil.copy(input_path, upload_dest)

    cfg = load_config()
    _model, config, _model_id = _load_production_model(model_name)
    metrics_spec = config.get("features", {}).get("metrics", ["vol_gm"])
    atlas_name = cfg["app"]["atlas_name"]

    manifest = Manifest(
        job_id=job_id or str(uuid.uuid4()),
        created_at=datetime.now(UTC),
        input=JobInput(
            upload_format="nifti"
            if upload_dest.name.endswith((".nii", ".nii.gz"))
            else "dicom_zip",
            upload_sha256=_sha256(upload_dest),
            upload_size_bytes=upload_dest.stat().st_size,
            chronological_age=chronological_age,
            sex=sex,
            retention_opt_in=retention_opt_in,
        ),
        environment=Environment(
            bagpipe_version="0.1.0",
            cat12_image=str(get_path("cat12_apptainer_image")),
            model_id=model_name,
            feature_schema_id=f"{atlas_name}__{'-'.join(sorted(metrics_spec))}",
        ),
    )

    stages = [
        IngestStage(),
        AnonymizeStage(),
        SegmentStage(),
        QcGateStage(),
        FeaturesStage(model_metrics=metrics_spec),
        PredictStage(model_name=model_name),
        ReportStage(),
    ]
    return run_stages(workspace, manifest, stages)


def run(input_path: Path, sex: str, work_dir: Path, model_name: str = "stacked") -> BAGResult:
    """Back-compat entry point matching the old flat pipeline.py's `run()`
    signature, used by `bagpipe.app.api`. Raises PipelineError on failure
    (translated from the manifest's recorded error).
    """
    manifest = run_manifest(input_path, sex, work_dir, model_name)
    if manifest.status == "failed":
        from bagpipe.app.pipeline.base import ErrorCode

        err = manifest.error
        raise PipelineError(ErrorCode(err.code), err.message, err.user_message)

    prediction = json.loads((work_dir / "predict" / "prediction.json").read_text())
    return BAGResult(
        predicted_age_raw=prediction["predicted_age_raw"],
        predicted_age_corrected=prediction["predicted_age"],
        regional_zscores=prediction["regional_zscores"],
        n_regions_scored=len(prediction["regional_zscores"]),
    )
