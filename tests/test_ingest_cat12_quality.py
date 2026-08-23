"""collect_quality_rows against a tiny synthetic cat12_images_dir layout —
no real data, no DB (matches collect_rows: no existing test touches the
DB-writing half of ingest_cat12, engine is a real-config singleton)."""

from __future__ import annotations

from bagpipe.db.ingest_cat12 import QUALITY_COLUMNS, collect_quality_rows

CAT_XML = """<?xml version="1.0"?>
<S>
  <qualitymeasures><NCR>0.04</NCR></qualitymeasures>
  <catlog>
    <item>Structural Image Quality Rating (SIQR): 79.86% (C+)</item>
  </catlog>
</S>
"""


def _write_report(root, sub, ses, xml=CAT_XML):
    anat = root / sub / ses / "anat"
    anat.mkdir(parents=True)
    (anat / f"cat_{sub}_{ses}_T1w.xml").write_text(xml)


def test_collect_quality_rows_parses_and_pads_missing_fields(tmp_path):
    _write_report(tmp_path, "sub-200109071247", "ses-200109071247")
    rows = collect_quality_rows(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["subject_key"] == "200109071247"
    assert row["session_id"] == "200109071247"
    assert row["source"] == "cat12"
    assert row["siqr_pct"] == 79.86
    assert row["ncr"] == 0.04
    assert set(row) == {"subject_key", "session_id", "source", *QUALITY_COLUMNS}
    assert row["cat_version"] is None  # not present in this XML


def test_collect_quality_rows_skips_run_with_no_quality_data(tmp_path):
    _write_report(tmp_path, "sub-200109071247", "ses-200109071247", xml="<S></S>")
    assert collect_quality_rows(tmp_path) == []


def test_collect_quality_rows_skips_unrecognized_subject_dirname(tmp_path):
    _write_report(tmp_path, "sub-notarealid", "ses-x")
    assert collect_quality_rows(tmp_path) == []
