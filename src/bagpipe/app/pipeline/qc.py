"""qc_gate stage — docs/design_inference_pipeline.md § Stage specifications: qc_gate.

CAT12's raw `<IQR>` tag in cat_*.xml is a 1-6 "mark" scale, not the 0-100
percent grade this stage's threshold is defined against (verified against
a real SNBB cat_*.xml, 2026-08-21) — the percent + letter grade live in the
human-readable report text instead, worded differently by CAT version
("Image Quality Rating (IQR): 79.50% (C+)" on CAT12.9/2577, "Structural
Image Quality Rating (SIQR): 79.86% (C+)" on CAT26.0.rc3 — both real,
confirmed against real XML from each, 2026-08-23). `cat12_parse.
SIQR_LINE_RE` matches both; an earlier version of that regex matched only
the CAT26 wording, so every real CAT12.9-era run raised QC_BELOW_THRESHOLD
with "could not parse IQR" (found + fixed same day). Full QC profile
(NCR/ICR/resolution/contrast/WMH/CAT version) now parsed via
`cat12_parse.parse_quality` too, surfaced in this stage's metrics for the
report — none of it gated on, only `siqr_pct`/`tiv_ml` are.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from bagpipe.app.cat12_parse import parse_quality
from bagpipe.app.pipeline.base import ErrorCode, PipelineError, StageResult

DEFAULT_IQR_THRESHOLD = 70.0
TIV_BOUNDS_ML = (1000.0, 2100.0)


class QcGateStage:
    name = "qc_gate"

    def __init__(self, iqr_threshold: float = DEFAULT_IQR_THRESHOLD):
        self.iqr_threshold = iqr_threshold

    def run(self, workspace: Path, manifest) -> StageResult:  # noqa: ARG002
        cat_xml = workspace / "cat12" / "report" / "cat_T1w.xml"
        root = ET.parse(cat_xml).getroot()

        quality = parse_quality(cat_xml)
        iqr_pct = quality.get("siqr_pct")
        if iqr_pct is None:
            raise PipelineError(
                ErrorCode.QC_BELOW_THRESHOLD, "could not parse SIQR from cat_*.xml report"
            )

        tiv_el = root.find("subjectmeasures/vol_TIV")
        tiv = float(tiv_el.text) if tiv_el is not None and tiv_el.text else None

        metrics: dict[str, float | int | str] = {**quality, "threshold": self.iqr_threshold}
        if tiv is not None:
            metrics["tiv_ml"] = tiv

        if iqr_pct < self.iqr_threshold:
            raise PipelineError(
                ErrorCode.QC_BELOW_THRESHOLD,
                f"SIQR {iqr_pct:.1f}% below threshold {self.iqr_threshold}",
                user_message="Your scan's image quality was too low for a reliable estimate.",
            )
        if tiv is not None and not (TIV_BOUNDS_ML[0] <= tiv <= TIV_BOUNDS_ML[1]):
            raise PipelineError(
                ErrorCode.QC_BELOW_THRESHOLD,
                f"TIV {tiv:.1f}ml outside plausible bounds {TIV_BOUNDS_ML}",
                user_message="Your scan's segmentation looked implausible — try a different image.",
            )

        return StageResult(metrics=metrics)
