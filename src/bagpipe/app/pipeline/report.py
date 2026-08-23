"""report stage — docs/design_inference_pipeline.md § Stage specifications: report.

Renders the HTML/PDF report (WeasyPrint, DESIGN.md §6). Email delivery is
not a stage — it happens at the queue layer (`bagpipe.app.queue`) after the
stage graph finishes, since a failed job (no `report` stage run at all) also
needs to notify the user.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from bagpipe.app.pipeline.base import StageResult
from bagpipe.app.report import render_success_html, write_pdf


class ReportStage:
    name = "report"

    def run(self, workspace: Path, manifest) -> StageResult:  # noqa: ARG002
        out_dir = workspace / "report"
        out_dir.mkdir(exist_ok=True)

        prediction = json.loads((workspace / "predict" / "prediction.json").read_text())
        qc_metrics = next((s.metrics for s in manifest.stages if s.name == "qc_gate"), {})

        dest = out_dir / "prediction.json"
        shutil.copy(workspace / "predict" / "prediction.json", dest)

        html = render_success_html(prediction, qc_metrics)
        pdf_path = write_pdf(html, out_dir / "report.pdf")

        return StageResult(
            outputs={
                "prediction": str(dest.relative_to(workspace)),
                "report_pdf": str(pdf_path.relative_to(workspace)),
            }
        )
