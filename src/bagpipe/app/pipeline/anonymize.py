"""anonymize stage — docs/design_inference_pipeline.md § Stage specifications: anonymize.

Defaces (pydeface) always — the design doc's "deface only if retention
opted in" is a privacy trade against runtime; v1 keeps it simple and always
defaces, since pydeface cost is small relative to the CAT12 stage that
follows. Deletes input/ after success either way.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from bagpipe.app.pipeline.base import ErrorCode, PipelineError, StageResult


class AnonymizeStage:
    name = "anonymize"

    def run(self, workspace: Path, manifest) -> StageResult:  # noqa: ARG002
        t1w = workspace / "ingest" / "T1w.nii.gz"
        if not t1w.exists():
            t1w = workspace / "ingest" / "T1w.nii"
        out_dir = workspace / "anon"
        out_dir.mkdir(exist_ok=True)
        dest = out_dir / "T1w.nii.gz"

        proc = subprocess.run(
            ["pydeface", "--outfile", str(dest), str(t1w)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not dest.exists():
            raise PipelineError(
                ErrorCode.INTERNAL,
                f"pydeface failed (rc={proc.returncode}): {proc.stderr[-2000:]}",
            )

        shutil.rmtree(workspace / "input", ignore_errors=True)
        return StageResult(outputs={"t1w": str(dest.relative_to(workspace))})
