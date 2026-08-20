"""cat12_parse against tiny synthetic CAT12 XML reports — no real data."""

from __future__ import annotations

import pandas as pd

from bagpipe.app.cat12_parse import extract_features, parse_globals, parse_regional

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
