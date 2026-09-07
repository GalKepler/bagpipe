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
from bagpipe.core.config import ConfigError, load_config


def _results_url(job_id: str) -> str | None:
    """The interactive report's public link, printed in the PDF so a reader
    who only has the attachment can still reach the parts paper can't carry.
    Same `app.public_base_url` the result email uses (`bagpipe.app.queue`);
    unset (local dev) simply omits the note."""
    try:
        base = (load_config()["app"].get("public_base_url") or "").rstrip("/")
    except (ConfigError, KeyError):
        return None
    return f"{base}/jobs/{job_id}/view" if base else None


class ReportStage:
    name = "report"

    def run(self, workspace: Path, manifest) -> StageResult:
        out_dir = workspace / "report"
        out_dir.mkdir(exist_ok=True)

        prediction = json.loads((workspace / "predict" / "prediction.json").read_text())
        qc_metrics = next((s.metrics for s in manifest.stages if s.name == "qc_gate"), {})

        dest = out_dir / "prediction.json"
        shutil.copy(workspace / "predict" / "prediction.json", dest)

        html = render_success_html(
            prediction, qc_metrics, results_url=_results_url(manifest.job_id)
        )
        pdf_path = write_pdf(html, out_dir / "report.pdf")

        return StageResult(
            outputs={
                "prediction": str(dest.relative_to(workspace)),
                "report_pdf": str(pdf_path.relative_to(workspace)),
            }
        )
