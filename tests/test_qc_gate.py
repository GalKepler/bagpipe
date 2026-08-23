"""qc_gate stage against a tiny synthetic cat_*.xml — no real data.

Regression coverage for the 2026-08-23 bug: the stage's threshold check used
to key off a regex ("Image Quality Rating (IQR)") that never matches real
CAT12.9+ catlog text ("Structural Image Quality Rating (SIQR)"), so every
real run raised QC_BELOW_THRESHOLD before the threshold was ever compared.
"""

from __future__ import annotations

import pytest

from bagpipe.app.pipeline.base import PipelineError
from bagpipe.app.pipeline.qc import QcGateStage

CAT_XML = """<?xml version="1.0"?>
<S>
  <subjectmeasures>
    <vol_TIV>1549.67</vol_TIV>
  </subjectmeasures>
  <qualitymeasures>
    <NCR>0.04</NCR>
  </qualitymeasures>
  <catlog>
    <item>Structural Image Quality Rating (SIQR): 79.86% (C+)</item>
  </catlog>
</S>
"""


def _write_report(tmp_path, xml=CAT_XML):
    report_dir = tmp_path / "cat12" / "report"
    report_dir.mkdir(parents=True)
    (report_dir / "cat_T1w.xml").write_text(xml)


def test_qc_gate_passes_and_surfaces_full_profile(tmp_path):
    _write_report(tmp_path)
    result = QcGateStage().run(tmp_path, manifest=None)
    assert result.metrics["siqr_pct"] == 79.86
    assert result.metrics["siqr_grade"] == "C+"
    assert result.metrics["ncr"] == 0.04
    assert result.metrics["tiv_ml"] == pytest.approx(1549.67)


def test_qc_gate_raises_below_threshold(tmp_path):
    low_xml = CAT_XML.replace("79.86% (C+)", "40.00% (F)")
    _write_report(tmp_path, low_xml)
    with pytest.raises(PipelineError, match="SIQR"):
        QcGateStage(iqr_threshold=70.0).run(tmp_path, manifest=None)


def test_qc_gate_raises_when_siqr_unparseable(tmp_path):
    _write_report(tmp_path, "<S><subjectmeasures><vol_TIV>1500</vol_TIV></subjectmeasures></S>")
    with pytest.raises(PipelineError, match="could not parse SIQR"):
        QcGateStage().run(tmp_path, manifest=None)
