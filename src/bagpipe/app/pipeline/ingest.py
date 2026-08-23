"""ingest stage — docs/design_inference_pipeline.md § Stage specifications: ingest.

v1 scope: format detection + DICOM->NIfTI conversion. Series selection
heuristics (SeriesDescription regex, 3D check, contrast heuristic) and
geometry-bounds validation are flagged as not-yet-implemented in the design
doc's stage spec and are still open here — this only covers what the old
flat `pipeline.py` already did (dcm2niix conversion, NIfTI passthrough).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from bagpipe.app.pipeline.base import ErrorCode, PipelineError, StageResult

NIFTI_SUFFIXES = (".nii", ".nii.gz")


def _is_nifti(path: Path) -> bool:
    return path.name.endswith(NIFTI_SUFFIXES)


class IngestStage:
    name = "ingest"

    def run(self, workspace: Path, manifest) -> StageResult:  # noqa: ARG002 — manifest unused, first stage
        out_dir = workspace / "ingest"
        out_dir.mkdir(exist_ok=True)
        input_path = next((workspace / "input").iterdir(), None)
        if input_path is None:
            raise PipelineError(ErrorCode.UNSUPPORTED_FORMAT, "input/ is empty")

        if _is_nifti(input_path):
            dest = (
                out_dir / "T1w.nii.gz" if input_path.name.endswith(".gz") else out_dir / "T1w.nii"
            )
            shutil.copy(input_path, dest)
            return StageResult(outputs={"t1w": str(dest.relative_to(workspace))})

        if input_path.suffix not in (".zip", ".dcm"):
            raise PipelineError(
                ErrorCode.UNSUPPORTED_FORMAT,
                f"unrecognized upload extension {input_path.suffix!r}",
                user_message="Upload a DICOM zip or a NIfTI file (.nii/.nii.gz).",
            )

        dicom_dir = input_path
        if input_path.suffix == ".zip":
            dicom_dir = out_dir / "dicom"
            dicom_dir.mkdir(exist_ok=True)
            shutil.unpack_archive(input_path, dicom_dir)

        proc = subprocess.run(
            ["dcm2niix", "-z", "y", "-f", "t1w", "-o", str(out_dir), str(dicom_dir)],
            capture_output=True,
            text=True,
        )
        produced = sorted(out_dir.glob("t1w*.nii.gz"))
        if proc.returncode != 0 or not produced:
            raise PipelineError(
                ErrorCode.DICOM_CONVERSION_FAILED,
                f"dcm2niix failed (rc={proc.returncode}): {proc.stderr[-2000:]}",
                user_message="We couldn't read your DICOM upload — is it a valid series?",
            )
        if len(produced) > 1:
            raise PipelineError(
                ErrorCode.MULTIPLE_SERIES_AMBIGUOUS,
                f"dcm2niix produced {len(produced)} series: {[p.name for p in produced]}",
                user_message="Your upload has multiple series — please upload a single T1w series.",
            )

        dest = out_dir / "T1w.nii.gz"
        produced[0].rename(dest)
        return StageResult(outputs={"t1w": str(dest.relative_to(workspace))})
