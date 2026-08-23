"""cat12_parse against tiny synthetic CAT12 XML reports — no real data."""

from __future__ import annotations

import pandas as pd

from bagpipe.app.cat12_parse import (
    extract_features,
    parse_globals,
    parse_quality,
    parse_regional,
    parse_surface_regional,
)

ATLAS_KEY = "myatlas__toCAT12"

CATROI_XML = f"""<?xml version="1.0"?>
<S>
  <{ATLAS_KEY}>
    <ids>[1;2]</ids>
    <data>
      <Vgm>[3.5;3.6]</Vgm>
      <Vwm>[1.1;1.2]</Vwm>
      <Vcsf>[0.5;0.6]</Vcsf>
    </data>
  </{ATLAS_KEY}>
</S>
"""

CAT_XML = """<?xml version="1.0"?>
<S>
  <subjectmeasures>
    <vol_TIV>1500.0</vol_TIV>
    <vol_abs_CGW>[300.0 900.0 250.0 5.0 0.0]</vol_abs_CGW>
  </subjectmeasures>
</S>
"""


def _lut():
    return pd.DataFrame({"index": [1, 2], "label": ["RegionA", "RegionB"]})


def test_parse_regional(tmp_path):
    xml_path = tmp_path / "catROI_t1w.xml"
    xml_path.write_text(CATROI_XML)
    df = parse_regional(xml_path, ATLAS_KEY, _lut())
    assert list(df["label"]) == ["RegionA", "RegionB"]
    assert list(df["vol_gm"]) == [3.5, 3.6]


def test_parse_regional_missing_atlas(tmp_path):
    xml_path = tmp_path / "catROI_t1w.xml"
    xml_path.write_text(CATROI_XML)
    assert parse_regional(xml_path, "wrong_key", _lut()) is None


def test_parse_globals(tmp_path):
    xml_path = tmp_path / "cat_t1w.xml"
    xml_path.write_text(CAT_XML)
    globals_ = parse_globals(xml_path)
    assert globals_ == {
        "TIV": 1500.0,
        "vol_csf": 300.0,
        "vol_gm": 900.0,
        "vol_wm": 250.0,
        "vol_wmh": 5.0,
    }


QUALITY_XML = """<?xml version="1.0"?>
<S>
  <qualitymeasures>
    <NCR>0.04</NCR>
    <ICR>0.13</ICR>
    <res_RMS>1.38</res_RMS>
    <contrast>28.72</contrast>
  </qualitymeasures>
  <subjectmeasures>
    <vol_abs_WMH>3.53</vol_abs_WMH>
    <vol_rel_WMH>0.0023</vol_rel_WMH>
  </subjectmeasures>
  <software>
    <version_cat>26.0.rc3</version_cat>
    <revision_cat>2874</revision_cat>
  </software>
  <catlog>
    <item>Structural Image Quality Rating (SIQR): 79.86% (C+)</item>
    <item>Relative gray matter volume (GMV/TIV): 37.636% (583.237 / 1549.669 ml)</item>
  </catlog>
</S>
"""


def test_parse_quality(tmp_path):
    xml_path = tmp_path / "cat_t1w.xml"
    xml_path.write_text(QUALITY_XML)
    quality = parse_quality(xml_path)
    assert quality == {
        "siqr_pct": 79.86,
        "siqr_grade": "C+",
        "gmv_tiv_pct": 37.636,
        "ncr": 0.04,
        "icr": 0.13,
        "res_rms_mm": 1.38,
        "contrast": 28.72,
        "vol_abs_wmh": 3.53,
        "vol_rel_wmh": 0.0023,
        "cat_version": "26.0.rc3",
        "cat_revision": "2874",
    }


def test_parse_quality_old_iqr_wording(tmp_path):
    """CAT12.9/2577 (training cohort) uses "Image Quality Rating (IQR)",
    not CAT26's "Structural Image Quality Rating (SIQR)" — both real,
    confirmed against real XML from each version, 2026-08-23."""
    xml_path = tmp_path / "cat_t1w.xml"
    xml_path.write_text(
        "<S><catlog><item>Image Quality Rating (IQR): 79.50% (C+)</item></catlog></S>"
    )
    quality = parse_quality(xml_path)
    assert quality == {"siqr_pct": 79.50, "siqr_grade": "C+"}


def test_parse_quality_missing_fields_omitted(tmp_path):
    xml_path = tmp_path / "cat_t1w.xml"
    xml_path.write_text(CAT_XML)  # no qualitymeasures/software/catlog
    assert parse_quality(xml_path) == {}


CATROIS_XML = """<?xml version="1.0"?>
<S>
  <aparc_DK40>
    <names><item>lunknown</item><item>lbankssts</item><item>rbankssts</item></names>
    <data><thickness>[NaN;2.51;2.60]</thickness></data>
  </aparc_DK40>
</S>
"""


def test_parse_surface_regional(tmp_path):
    xml_path = tmp_path / "catROIs_t1w.xml"
    xml_path.write_text(CATROIS_XML)
    df = parse_surface_regional(xml_path, "aparc_DK40")
    assert list(df["label"]) == ["lbankssts", "rbankssts"]  # NaN (medial wall) dropped
    assert list(df["thickness"]) == [2.51, 2.60]


def test_parse_surface_regional_missing_atlas(tmp_path):
    xml_path = tmp_path / "catROIs_t1w.xml"
    xml_path.write_text(CATROIS_XML)
    assert parse_surface_regional(xml_path, "aparc_a2009s") is None


def test_extract_features(tmp_path):
    catroi = tmp_path / "catROI_t1w.xml"
    catroi.write_text(CATROI_XML)
    cat = tmp_path / "cat_t1w.xml"
    cat.write_text(CAT_XML)

    features = extract_features(catroi, cat, "myatlas", ATLAS_KEY, _lut(), ["vol_gm", "vol_wm"])

    assert features["myatlas__RegionA__vol_gm"] == 3.5
    assert features["myatlas__RegionB__vol_wm"] == 1.2
    assert "myatlas__RegionA__vol_csf" not in features  # not in requested metrics
    assert features["TIV"] == 1500.0
