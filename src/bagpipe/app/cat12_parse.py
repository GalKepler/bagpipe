"""Parse a single CAT12 XML report pair (`catROI_*.xml`, `cat_*.xml`) into the
same `atlas__region__metric` feature space `bagpipe.models.tabular` builds
from the ingested `features` table.

Ported from the maintainer's existing `update_tabular_cat12.py` (private,
outside this repo) — same XML shape, same tissue tags — but consumes a
single fresh CAT12 run's report directly instead of walking a derivatives
tree, since Pillar 4 predicts on one freshly-processed upload at a time.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

TISSUES = {"Vgm": "vol_gm", "Vwm": "vol_wm", "Vcsf": "vol_csf"}
GLOBAL_METRICS = ["TIV", "vol_csf", "vol_gm", "vol_wm", "vol_wmh"]


def parse_regional(catroi_xml: Path, atlas_key: str, lut: pd.DataFrame) -> pd.DataFrame | None:
    """Returns a DataFrame with columns [label, vol_gm, vol_wm, vol_csf] (only
    the tissues CAT12 reported), or None if ROI estimation failed/is absent.
    """
    root = ET.parse(catroi_xml).getroot()
    atlas = root.find(atlas_key)
    if atlas is None:
        return None
    ids_el = atlas.find("ids")
    if ids_el is None or not ids_el.text:
        return None
    ids = [int(v) for v in ids_el.text.strip("[]").split(";")]
    data_el = atlas.find("data")
    values = {}
    for tag, metric in TISSUES.items():
        el = data_el.find(tag) if data_el is not None else None
        if el is not None and el.text:
            values[metric] = [float(v) for v in el.text.strip("[]").split(";")]
    if not values:
        return None
    df = pd.DataFrame({"index": ids, **values}).merge(
        lut[["index", "label"]], on="index", how="left"
    )
    return df.drop(columns="index")


def parse_globals(cat_xml: Path) -> dict[str, float]:
    root = ET.parse(cat_xml).getroot()
    sm = root.find("subjectmeasures")
    if sm is None:
        return {}
    csf, gm, wm, wmh, _ = (float(v) for v in sm.find("vol_abs_CGW").text.strip("[]").split())
    return {
        "TIV": float(sm.find("vol_TIV").text),
        "vol_csf": csf,
        "vol_gm": gm,
        "vol_wm": wm,
        "vol_wmh": wmh,
    }


def extract_features(
    catroi_xml: Path,
    cat_xml: Path,
    atlas_name: str,
    atlas_key: str,
    lut: pd.DataFrame,
    metrics: list[str],
) -> dict[str, float]:
    """Returns `{"<atlas>__<region>__<metric>": value, ...}` for regional
    volumes in `metrics`, plus every `GLOBAL_METRICS` key unprefixed (`TIV`,
    `vol_gm`, ...). Raises if the CAT12 run produced no ROI output — a
    prediction can't proceed on a partial run.
    """
    regional = parse_regional(catroi_xml, atlas_key, lut)
    if regional is None:
        raise ValueError(f"no ROI output in {catroi_xml} for atlas key {atlas_key!r}")

    features = {}
    for _, row in regional.iterrows():
        for metric in metrics:
            if metric in row:
                features[f"{atlas_name}__{row['label']}__{metric}"] = float(row[metric])

    features.update(parse_globals(cat_xml))
    return features
