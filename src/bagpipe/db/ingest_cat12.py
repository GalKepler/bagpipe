"""Ingest CAT12 T1w-derived tabular outputs into bagpipe's `features` table,
plus per-session QC profiles into `cat12_quality`.

Features: walks paths.cat12_dir only (not qsiprep/qsirecon — dMRI is a later
phase). Two file kinds per session, both long-format after parsing:
  - *_desc-globals_morphometry.tsv   -> global scalars (TIV, vol_csf, vol_gm, vol_wm, vol_wmh)
  - atlas-*/*_param-{csf,gm,wm}_volmap.tsv -> per-ROI volume_ml, one row per region

QC: walks paths.cat12_images_dir separately — the tabular export above never
carried CAT12's raw `cat_*.xml` reports (confirmed against a real export,
2026-08-23; its `_desc-globals_morphometry.json` sidecar's `source_file`
points back at `cat12_images_dir` instead), so SIQR/NCR/ICR/resolution/
WMH/CAT-version only exist there. Flat `sub-*/ses-*/anat/cat_*.xml` layout
(this dir predates CAT12.9's BIDS-folder split into report/label subdirs).

Idempotent: upserts on (uid, legacy_subject_id, session_id, source, atlas, region, metric)
for features, (subject_key, session_id) for QC.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from bagpipe.app.cat12_parse import parse_quality
from bagpipe.core.config import get_path
from bagpipe.db.base import get_engine, init_db
from bagpipe.db.models import Cat12Quality, Feature
from bagpipe.db.upsert import upsert_rows

_SUB_RE = re.compile(r"sub-(S\d+|\d{12})$")
_SES_RE = re.compile(r"ses-(\S+)$")
_ATLAS_PARAM_RE = re.compile(r"atlas-(?P<atlas>[^_]+).*param-(?P<param>csf|gm|wm)_volmap\.tsv$")

GLOBAL_METRICS = ["TIV", "vol_csf", "vol_gm", "vol_wm", "vol_wmh"]


def _subject_ids(sub_dirname: str) -> tuple[str | None, str | None]:
    """Return (uid, legacy_subject_id) from a `sub-...` dirname."""
    m = _SUB_RE.match(sub_dirname)
    if not m:
        return None, None
    token = m.group(1)
    return (token, None) if token.startswith("S") else (None, token)


def _global_rows(
    tsv_path: Path, uid: str | None, legacy_id: str | None, session_id: str
) -> list[dict]:
    df = pd.read_csv(tsv_path, sep="\t")
    row = df.iloc[0]
    return [
        {
            "subject_key": uid or legacy_id,
            "uid": uid,
            "legacy_subject_id": legacy_id,
            "session_id": session_id,
            "source": "cat12",
            "atlas": "",
            "region": "global",
            "metric": metric,
            "value": float(row[metric]),
        }
        for metric in GLOBAL_METRICS
        if metric in row
    ]


def _atlas_rows(
    tsv_path: Path, uid: str | None, legacy_id: str | None, session_id: str
) -> list[dict]:
    m = _ATLAS_PARAM_RE.search(tsv_path.name)
    if not m:
        return []
    atlas, param = m.group("atlas"), m.group("param")
    df = pd.read_csv(tsv_path, sep="\t")
    return [
        {
            "subject_key": uid or legacy_id,
            "uid": uid,
            "legacy_subject_id": legacy_id,
            "session_id": session_id,
            "source": "cat12",
            "atlas": atlas,
            "region": r["label"],
            "metric": f"vol_{param}",
            "value": float(r["volume_ml"]),
        }
        for _, r in df.iterrows()
    ]


def collect_rows(cat12_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for sub_dir in sorted(cat12_dir.glob("sub-*")):
        uid, legacy_id = _subject_ids(sub_dir.name)
        if uid is None and legacy_id is None:
            continue
        for ses_dir in sorted(sub_dir.glob("ses-*")):
            m = _SES_RE.match(ses_dir.name)
            session_id = m.group(1) if m else None
            anat_dir = ses_dir / "anat"
            if not anat_dir.is_dir():
                continue
            for tsv in anat_dir.glob("*_desc-globals_morphometry.tsv"):
                rows.extend(_global_rows(tsv, uid, legacy_id, session_id))
            for tsv in anat_dir.glob("atlas-*/*_volmap.tsv"):
                rows.extend(_atlas_rows(tsv, uid, legacy_id, session_id))
    return rows


QUALITY_COLUMNS = [
    "siqr_pct",
    "siqr_grade",
    "ncr",
    "icr",
    "res_rms_mm",
    "contrast",
    "gmv_tiv_pct",
    "vol_abs_wmh",
    "vol_rel_wmh",
    "cat_version",
    "cat_revision",
]


def collect_quality_rows(images_dir: Path) -> list[dict]:
    """Each returned dict has every `QUALITY_COLUMNS` key (missing fields set
    to `None`) so the batch insert below sees uniform columns across rows —
    `parse_quality` itself omits fields a given run didn't report."""
    rows: list[dict] = []
    for sub_dir in sorted(images_dir.glob("sub-*")):
        uid, legacy_id = _subject_ids(sub_dir.name)
        if uid is None and legacy_id is None:
            continue
        subject_key = uid or legacy_id
        for ses_dir in sorted(sub_dir.glob("ses-*")):
            m = _SES_RE.match(ses_dir.name)
            session_id = m.group(1) if m else None
            anat_dir = ses_dir / "anat"
            if not anat_dir.is_dir():
                continue
            for cat_xml in anat_dir.glob("cat_*.xml"):
                quality = parse_quality(cat_xml)
                if not quality:
                    continue
                row = {"subject_key": subject_key, "session_id": session_id, "source": "cat12"}
                row.update({col: quality.get(col) for col in QUALITY_COLUMNS})
                rows.append(row)
    return rows


def ingest(cat12_dir: Path | None = None, cat12_images_dir: Path | None = None) -> dict:
    cat12_dir = cat12_dir or get_path("cat12_dir")
    cat12_images_dir = cat12_images_dir or get_path("cat12_images_dir")
    rows = collect_rows(cat12_dir)
    quality_rows = collect_quality_rows(cat12_images_dir)
    init_db()
    engine = get_engine()
    feature_conflict_cols = ["subject_key", "session_id", "source", "atlas", "region", "metric"]
    with engine.begin() as conn:
        upsert_rows(conn, Feature, rows, feature_conflict_cols)
        upsert_rows(conn, Cat12Quality, quality_rows, ["subject_key", "session_id", "source"])
    return {"rows_ingested": len(rows), "quality_rows_ingested": len(quality_rows)}


if __name__ == "__main__":
    summary = ingest()
    print(
        f"CAT12 ingest: {summary['rows_ingested']} feature rows, "
        f"{summary['quality_rows_ingested']} QC rows"
    )
