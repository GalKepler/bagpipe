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
import zipfile
from pathlib import Path

from bagpipe.app.pipeline.base import ErrorCode, PipelineError, StageResult

NIFTI_SUFFIXES = (".nii", ".nii.gz")

# dcm2niix on a single T1w DICOM series is a fast, bounded conversion — a
# hang here (bad/corrupt series, resource contention) must not wedge the
# single worker forever, same reasoning as segment.py's CAT12 timeout.
DEFAULT_DCM2NIIX_TIMEOUT_S = 10 * 60

# Uncapped `shutil.unpack_archive` on an arbitrary public upload is a zip-bomb
# vector — a small compressed file can expand to an unreasonable amount of
# disk/CPU. These caps are generous for a single T1w DICOM series (typically
# a few hundred MB uncompressed, a few hundred files) while still bounding
# the worst case.
MAX_ZIP_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
MAX_ZIP_MEMBERS = 20_000


def _is_nifti(path: Path) -> bool:
    return path.name.endswith(NIFTI_SUFFIXES)


def _check_zip_bounds(zip_path: Path) -> None:
    """Rejects an upload whose declared uncompressed size or member count is
    unreasonable, before `shutil.unpack_archive` ever extracts it. Zip-slip
    itself is mitigated by stdlib `zipfile.extractall`'s own path checks
    (Python >= 3.6), but that's a property of the stdlib, not something this
    guarded for — this only bounds resource exhaustion (zip bombs).
    """
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            total_uncompressed = sum(i.file_size for i in infos)
            member_count = len(infos)
    except zipfile.BadZipFile as e:
        raise PipelineError(
            ErrorCode.UNSUPPORTED_FORMAT,
            f"not a valid zip archive: {e}",
            user_message="Upload a DICOM zip or a NIfTI file (.nii/.nii.gz).",
        ) from e

    if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES or member_count > MAX_ZIP_MEMBERS:
        raise PipelineError(
            ErrorCode.UNSUPPORTED_FORMAT,
            f"zip too large: {total_uncompressed} bytes uncompressed, "
            f"{member_count} members (limits: {MAX_ZIP_UNCOMPRESSED_BYTES} bytes, "
            f"{MAX_ZIP_MEMBERS} members)",
            user_message="Your upload is too large or contains too many files.",
        )


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
            _check_zip_bounds(input_path)
            shutil.unpack_archive(input_path, dicom_dir)

        try:
            proc = subprocess.run(
                ["dcm2niix", "-z", "y", "-f", "t1w", "-o", str(out_dir), str(dicom_dir)],
                capture_output=True,
                text=True,
                timeout=DEFAULT_DCM2NIIX_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as e:
            raise PipelineError(
                ErrorCode.DICOM_CONVERSION_FAILED,
                f"dcm2niix exceeded {DEFAULT_DCM2NIIX_TIMEOUT_S}s timeout",
                user_message="Processing your scan took too long. Please try again later.",
            ) from e
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
