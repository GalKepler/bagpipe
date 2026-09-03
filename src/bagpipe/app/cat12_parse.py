"""Parse a single CAT12 XML report pair (`catROI_*.xml`, `cat_*.xml`) into the
same `atlas__region__metric` feature space `bagpipe.models.tabular` builds
from the ingested `features` table.

Ported from the maintainer's existing `update_tabular_cat12.py` (private,
outside this repo) — same XML shape, same tissue tags — but consumes a
single fresh CAT12 run's report directly instead of walking a derivatives
tree, since Pillar 4 predicts on one freshly-processed upload at a time.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

TISSUES = {"Vgm": "vol_gm", "Vwm": "vol_wm", "Vcsf": "vol_csf"}
GLOBAL_METRICS = ["TIV", "vol_csf", "vol_gm", "vol_wm", "vol_wmh"]

# catROIs_*.xml (surface, plural) holds per-region cortical thickness — a
# separate file/schema from catROI_*.xml (volume, singular): one <data>
# element per surface atlas tag, region labels in <names> (no LUT needed,
# unlike the volume atlases), medial-wall/non-cortical regions (unknown,
# corpuscallosum) reported as NaN and dropped here rather than propagated.
SURFACE_ATLASES = {"aparc_DK40": "surf_DK40", "aparc_a2009s": "surf_Destrieux"}

# XML <data> child tag per surface metric, for parse_surface_regional's
# `metric` param. "thickness" confirmed real (every catROIs_*.xml has it).
# The rest are a best-effort guess mirroring CAT12's per-vertex file-naming
# convention (bagpipe.app.surface_atlas.SURFACE_METRICS) for whenever
# `surfextract` output (container/cat12.def, 2026-08-24) starts populating
# them — NOT yet confirmed against a real XML with these tags present.
SURFACE_METRIC_TAGS = {
    "thickness": "thickness",
    "gyrification": "gyrification",
    "sulcal_depth": "depth",
    "fractal_dimension": "fractaldimension",
}

# Catlog text differs by CAT version — confirmed against real XML from both,
# 2026-08-23: CAT12.9/2577 (training cohort) says "Image Quality Rating
# (IQR): 79.50% (C+)", CAT26.0.rc3 (reprocessing cohort) says "Structural
# Image Quality Rating (SIQR): 79.86% (C+)" — the "Structural " prefix and
# "(SIQR)" are both new. An earlier fix here only matched the CAT26 wording
# and silently dropped siqr_pct for every CAT12.9 row (0% pass rate on the
# whole training cohort) — the "Structural " prefix must stay optional.
# Percent + grade only live in this human-readable line, not a dedicated
# XML tag.
SIQR_LINE_RE = re.compile(
    r"(?:Structural )?Image Quality Rating \(S?IQR\):\s*([\d.]+)%\s*\(([A-F][+-]?)\)"
)
GMV_TIV_LINE_RE = re.compile(r"Relative gray matter volume \(GMV/TIV\):\s*([\d.]+)%")


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


def parse_surface_regional(
    catrois_xml: Path, atlas_key: str, metric: str = "thickness"
) -> pd.DataFrame | None:
    """Returns a DataFrame with columns [label, <metric>] for one surface
    atlas tag (e.g. `aparc_DK40`) and one metric (see SURFACE_METRIC_TAGS),
    or None if that atlas/metric data is absent — a failed surface
    reconstruction, or a metric `surfextract` hasn't computed, shouldn't
    raise, since core ROI volumes (the model's actual input) can still be
    valid."""
    tag = SURFACE_METRIC_TAGS.get(metric, metric)
    root = ET.parse(catrois_xml).getroot()
    atlas = root.find(atlas_key)
    if atlas is None:
        return None
    names_el = atlas.find("names")
    data_el = atlas.find("data")
    if names_el is None or data_el is None:
        return None
    metric_el = data_el.find(tag)
    if metric_el is None or not metric_el.text:
        return None
    labels = [n.text for n in names_el]
    raw = metric_el.text.strip("[]").split(";")
    values = [float(v) if v != "NaN" else float("nan") for v in raw]
    df = pd.DataFrame({"label": labels, metric: values})
    return df.dropna(subset=[metric])


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


def parse_quality(cat_xml: Path) -> dict[str, float | str]:
    """QC profile from a `cat_*.xml` report: SIQR score/grade and GMV/TIV%
    (catlog text, `SIQR_LINE_RE`/`GMV_TIV_LINE_RE`), NCR/ICR/resolution/
    contrast (`qualitymeasures`), WMH burden (`subjectmeasures`), and CAT
    version/revision (`software`). Any field CAT12 didn't report is omitted
    rather than defaulted — a partial/older run shouldn't fabricate zeros.
    """
    root = ET.parse(cat_xml).getroot()
    quality: dict[str, float | str] = {}

    for item in root.iter("item"):
        text = item.text or ""
        m = SIQR_LINE_RE.search(text)
        if m:
            quality["siqr_pct"] = float(m.group(1))
            quality["siqr_grade"] = m.group(2)
        m = GMV_TIV_LINE_RE.search(text)
        if m:
            quality["gmv_tiv_pct"] = float(m.group(1))

    qm = root.find("qualitymeasures")
    if qm is not None:
        for tag, key in [("NCR", "ncr"), ("ICR", "icr"), ("contrast", "contrast")]:
            el = qm.find(tag)
            if el is not None and el.text:
                quality[key] = float(el.text)
        rms_el = qm.find("res_RMS")
        if rms_el is not None and rms_el.text:
            quality["res_rms_mm"] = float(rms_el.text)

    sm = root.find("subjectmeasures")
    if sm is not None:
        wmh_el = sm.find("vol_abs_WMH")
        if wmh_el is not None and wmh_el.text:
            quality["vol_abs_wmh"] = float(wmh_el.text)
        wmh_rel_el = sm.find("vol_rel_WMH")
        if wmh_rel_el is not None and wmh_rel_el.text:
            quality["vol_rel_wmh"] = float(wmh_rel_el.text)

    sw = root.find("software")
    if sw is not None:
        for tag, key in [("version_cat", "cat_version"), ("revision_cat", "cat_revision")]:
            el = sw.find(tag)
            if el is not None and el.text:
                quality[key] = el.text.strip()

    return quality


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
