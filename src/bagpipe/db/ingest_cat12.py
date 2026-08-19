"""Ingest CAT12 T1w-derived tabular outputs into bagpipe's `features` table.

Walks paths.cat12_dir only (not qsiprep/qsirecon — dMRI is a later phase).
Two file kinds per session, both long-format after parsing:
  - *_desc-globals_morphometry.tsv   -> global scalars (TIV, vol_csf, vol_gm, vol_wm, vol_wmh)
  - atlas-*/*_param-{csf,gm,wm}_volmap.tsv -> per-ROI volume_ml, one row per region

Idempotent: upserts on (uid, legacy_subject_id, session_id, source, atlas, region, metric).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from sqlalchemy.dialects.sqlite import insert

from bagpipe.core.config import get_path
from bagpipe.db.base import get_engine, init_db
from bagpipe.db.models import Feature

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


def ingest(cat12_dir: Path | None = None) -> dict:
    cat12_dir = cat12_dir or get_path("cat12_dir")
    rows = collect_rows(cat12_dir)
    init_db()
    engine = get_engine()
    conflict_cols = ["subject_key", "session_id", "source", "atlas", "region", "metric"]
    with engine.begin() as conn:
        for i in range(0, len(rows), 500):
            batch = rows[i : i + 500]
            stmt = insert(Feature).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=conflict_cols,
                set_={"value": stmt.excluded.value},
            )
            conn.execute(stmt)
    return {"rows_ingested": len(rows)}


if __name__ == "__main__":
    summary = ingest()
    print(f"CAT12 ingest: {summary['rows_ingested']} rows")
