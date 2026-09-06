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

# pydeface fits a registration to a template — never hangs on a well-formed
# T1w in practice, but a hung/killed process (see job 883377d8 on disk,
# real: "pydeface failed (rc=-15)" — SIGTERM after 144s from something
# external) would otherwise wedge the single worker forever. 15 min gives
# generous headroom over the real ~144s+success cases seen so far.
DEFAULT_TIMEOUT_S = 15 * 60


class AnonymizeStage:
    name = "anonymize"

    def __init__(self, timeout_s: int = DEFAULT_TIMEOUT_S):
        self.timeout_s = timeout_s

    def run(self, workspace: Path, manifest) -> StageResult:  # noqa: ARG002
        t1w = workspace / "ingest" / "T1w.nii.gz"
        if not t1w.exists():
            t1w = workspace / "ingest" / "T1w.nii"
        out_dir = workspace / "anon"
        out_dir.mkdir(exist_ok=True)
        dest = out_dir / "T1w.nii.gz"

        try:
            proc = subprocess.run(
                ["pydeface", "--outfile", str(dest), str(t1w)],
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as e:
            raise PipelineError(
                ErrorCode.INTERNAL,
                f"pydeface exceeded {self.timeout_s}s timeout",
                user_message="Processing your scan took too long. Please try again later.",
            ) from e
        if proc.returncode != 0 or not dest.exists():
            raise PipelineError(
                ErrorCode.INTERNAL,
                f"pydeface failed (rc={proc.returncode}): {proc.stderr[-2000:]}",
            )

        shutil.rmtree(workspace / "input", ignore_errors=True)
        return StageResult(outputs={"t1w": str(dest.relative_to(workspace))})
