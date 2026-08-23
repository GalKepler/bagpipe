"""Executes the stage sequence for one job, owns the manifest —
docs/design_inference_pipeline.md § Stage interface / § Worker execution.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path

from bagpipe.app.pipeline.base import ErrorCode, PipelineError, Stage
from bagpipe.app.pipeline.models import Manifest, ManifestError, StageRecord

STAGE_ORDER = ["ingest", "anonymize", "segment", "qc_gate", "extract_features", "predict", "report"]


def _write_manifest(workspace: Path, manifest: Manifest) -> None:
    tmp = workspace / "manifest.json.tmp"
    tmp.write_text(manifest.model_dump_json(indent=2))
    os.replace(tmp, workspace / "manifest.json")


def run_stages(workspace: Path, manifest: Manifest, stages: list[Stage]) -> Manifest:
    """Runs `stages` in order against `workspace`, updating and persisting
    `manifest` after every stage (atomic write: `.tmp` then `os.replace`).
    Stops at the first failure — jobs are not resumable in v1.
    """
    for stage in stages:
        started = datetime.now(UTC)
        t0 = time.monotonic()
        try:
            result = stage.run(workspace, manifest)
        except PipelineError as e:
            manifest.stages.append(
                StageRecord(
                    name=stage.name,
                    status="failed",
                    started_at=started,
                    ended_at=datetime.now(UTC),
                    duration_s=time.monotonic() - t0,
                )
            )
            manifest.status = "failed"
            manifest.error = ManifestError(
                stage=stage.name, code=e.code.value, message=e.message, user_message=e.user_message
            )
            _write_manifest(workspace, manifest)
            return manifest
        except Exception as e:  # noqa: BLE001 — any non-PipelineError maps to INTERNAL, per design doc
            manifest.stages.append(
                StageRecord(
                    name=stage.name,
                    status="failed",
                    started_at=started,
                    ended_at=datetime.now(UTC),
                    duration_s=time.monotonic() - t0,
                )
            )
            manifest.status = "failed"
            manifest.error = ManifestError(
                stage=stage.name,
                code=ErrorCode.INTERNAL.value,
                message=str(e),
                user_message="Something went wrong on our end. Please try again later.",
            )
            _write_manifest(workspace, manifest)
            return manifest

        manifest.stages.append(
            StageRecord(
                name=stage.name,
                status="succeeded",
                started_at=started,
                ended_at=datetime.now(UTC),
                duration_s=time.monotonic() - t0,
                outputs=result.outputs,
                metrics=result.metrics,
                warnings=result.warnings,
            )
        )
        _write_manifest(workspace, manifest)

    manifest.status = "succeeded"
    _write_manifest(workspace, manifest)
    return manifest
