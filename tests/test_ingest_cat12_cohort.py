"""collect_rows against a tiny synthetic CAT26-cohort layout (report/label
subdirs, plain atlas tag) — no real data, no DB."""

from __future__ import annotations

import sqlite3

import pandas as pd

from bagpipe.db.ingest_cat12_cohort import DEFAULT_ATLAS_KEY, DEFAULT_ATLAS_NAME, collect_rows

CATROI_XML = f"""<?xml version="1.0"?>
<S>
  <{DEFAULT_ATLAS_KEY}>
    <ids>[1;2]</ids>
    <data>
      <Vgm>[3.5;3.6]</Vgm>
      <Vwm>[1.1;1.2]</Vwm>
      <Vcsf>[0.5;0.6]</Vcsf>
    </data>
  </{DEFAULT_ATLAS_KEY}>
</S>
"""

CAT_XML = """<?xml version="1.0"?>
<S>
  <subjectmeasures>
    <vol_TIV>1500.0</vol_TIV>
    <vol_abs_CGW>[300.0 900.0 250.0 5.0 0.0]</vol_abs_CGW>
    <vol_abs_WMH>3.53</vol_abs_WMH>
    <vol_rel_WMH>0.0023</vol_rel_WMH>
  </subjectmeasures>
  <qualitymeasures><NCR>0.04</NCR></qualitymeasures>
  <catlog>
    <item>Structural Image Quality Rating (SIQR): 79.86% (C+)</item>
  </catlog>
</S>
"""


def _lut():
    return pd.DataFrame({"index": [1, 2], "label": ["RegionA", "RegionB"]})


CATROIS_XML = """<?xml version="1.0"?>
<S>
  <aparc_DK40>
    <names><item>lunknown</item><item>lbankssts</item><item>rbankssts</item></names>
    <data><thickness>[NaN;2.51;2.60]</thickness></data>
  </aparc_DK40>
</S>
"""


def _write_session(root, sub, ses, catroi=CATROI_XML, cat=CAT_XML, catrois=None):
    anat = root / sub / ses / "anat"
    (anat / "report").mkdir(parents=True)
    (anat / "label").mkdir(parents=True)
    (anat / "report" / f"cat_{sub}_{ses}_T1w.xml").write_text(cat)
    (anat / "label" / f"catROI_{sub}_{ses}_T1w.xml").write_text(catroi)
    if catrois is not None:
        (anat / "label" / f"catROIs_{sub}_{ses}_T1w.xml").write_text(catrois)


def test_collect_rows_parses_features_and_quality(tmp_path):
    _write_session(tmp_path, "sub-200109071247", "ses-200109071247")
    feature_rows, quality_rows, summary = collect_rows(tmp_path, lut=_lut())

    assert summary == {
        "sessions_found": 1,
        "sessions_ingested": 1,
        "skipped_no_report": 0,
        "skipped_no_roi": 0,
        "skipped_not_succeeded": 0,
    }

    region_rows = [r for r in feature_rows if r["region"] != "global"]
    assert len(region_rows) == 6  # 2 regions x 3 metrics
    assert all(r["source"] == "cat12_v26" for r in feature_rows)
    assert all(r["atlas"] == DEFAULT_ATLAS_NAME for r in region_rows)

    global_rows = {r["metric"]: r["value"] for r in feature_rows if r["region"] == "global"}
    assert global_rows["TIV"] == 1500.0
    assert global_rows["vol_gm"] == 900.0

    assert len(quality_rows) == 1
    assert quality_rows[0]["source"] == "cat12_v26"
    assert quality_rows[0]["siqr_pct"] == 79.86


def test_collect_rows_skips_session_missing_report(tmp_path):
    anat = tmp_path / "sub-200109071247" / "ses-200109071247" / "anat"
    anat.mkdir(parents=True)  # no report/ or label/ subdirs at all

    feature_rows, quality_rows, summary = collect_rows(tmp_path, lut=_lut())
    assert feature_rows == []
    assert quality_rows == []
    assert summary["skipped_no_report"] == 1
    assert summary["sessions_found"] == 0


def test_collect_rows_skips_session_with_unparseable_roi(tmp_path):
    _write_session(tmp_path, "sub-200109071247", "ses-200109071247", catroi="<S></S>")
    feature_rows, quality_rows, summary = collect_rows(tmp_path, lut=_lut())
    assert feature_rows == []
    assert quality_rows == []  # quality parse never reached — no-ROI skip happens first
    assert summary["skipped_no_roi"] == 1
    assert summary["sessions_ingested"] == 0


def test_collect_rows_includes_surface_thickness_when_present(tmp_path):
    _write_session(tmp_path, "sub-200109071247", "ses-200109071247", catrois=CATROIS_XML)
    feature_rows, _, summary = collect_rows(tmp_path, lut=_lut())
    assert summary["sessions_ingested"] == 1

    surf_rows = [r for r in feature_rows if r["atlas"] == "surf_DK40"]
    assert {r["region"] for r in surf_rows} == {"lbankssts", "rbankssts"}  # NaN region dropped
    assert all(r["metric"] == "thickness" for r in surf_rows)


def test_collect_rows_ok_without_surface_file(tmp_path):
    _write_session(tmp_path, "sub-200109071247", "ses-200109071247")  # no catrois
    feature_rows, _, summary = collect_rows(tmp_path, lut=_lut())
    assert summary["sessions_ingested"] == 1


def test_collect_rows_skips_sessions_not_ledger_succeeded(tmp_path):
    """Stale on-disk output from a prior run (not yet redone this run) must
    not be silently re-ingested as current."""
    _write_session(tmp_path, "sub-200109071247", "ses-200109071247")
    _write_session(tmp_path, "sub-200210081348", "ses-200210081348")

    con = sqlite3.connect(tmp_path / ".bagpipe_cat12_ledger.sqlite")
    con.execute("create table subjects (t1w_path text, status text)")
    con.execute(
        "insert into subjects values (?, 'succeeded')",
        (f"{tmp_path}/sub-200109071247/ses-200109071247/anat/sub-200109071247_ses-200109071247_T1w.nii",),
    )
    con.execute(
        "insert into subjects values (?, 'queued')",
        (f"{tmp_path}/sub-200210081348/ses-200210081348/anat/sub-200210081348_ses-200210081348_T1w.nii",),
    )
    con.commit()
    con.close()

    _, _, summary = collect_rows(tmp_path, lut=_lut())
    assert summary["sessions_ingested"] == 1
    assert summary["skipped_not_succeeded"] == 1
