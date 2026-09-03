"""Ingest the CAT26 reprocessing cohort (`bag preprocess cat12-cohort`'s
output, `config/cat12_cohort.yaml: output_derivatives_dir`) into `features`
and `cat12_quality` — a from-scratch reprocessing of the same subjects
already ingested via `ingest_cat12.ingest()` from the training-era CAT12.9
export, on a newer CAT version (26.0.rc3, confirmed real,
docs/cat12_container_spec.md). Written as `source="cat12_v26"` in `Feature`
(distinct from the existing `"cat12"` rows) so both versions stay queryable
side by side — e.g. to visualize CAT-version drift in region volumes/QC —
rather than one silently overwriting the other.

Classic-mode layout (`anat/report/cat_*.xml`, `anat/label/catROI_*.xml`),
confirmed 2026-08-21/22 real smoke tests — NOT the flat layout
`ingest_cat12.py`/`cat12_images_dir` assumes for the old CAT12.9 tree.

Real gotcha, confirmed against an actual cohort XML (2026-08-23): CAT26's
Schaefer atlas element is named plain `schaefer2018n400n7tian2020s2` in
`catROI_*.xml`, NOT `schaefer2018n400n7tian2020s2__toCAT12` like the old
CAT12.9 tree (`config/local.yaml`'s `app.atlas_key`) — a different custom-
atlas registration naming between CAT versions. `DEFAULT_ATLAS_KEY` below
reflects the CAT26 tag; don't reuse `app.atlas_key` for this ingest.

Only the production Schaefer+Tian atlas is ingested here, even though the
cohort config also computes neuromorphometrics/lpba40/cobra/thalamus/
thalamic_nuclei/suit (config/cat12_cohort.yaml `extra_batch_lines`) — those
aren't wired into any LUT/region-mapping path yet; a future addition, not
silently dropped forever.

A cohort mid-run has partial subjects (some without `report/`/`label`
output yet, some flagged unprocessed in the ledger) — skipped, not raised,
with a summary count so a partial-cohort ingest is visible, not silent.

Real bug, found 2026-08-25 (`surface_atlas_review.ipynb`'s session count
didn't match the throughput notebook's ledger-based count): a from-scratch
`bag preprocess cat12-cohort` run doesn't clear a subject's old output
directory before reprocessing it — `report/`/`label/` XMLs from a *previous*
run sit on disk, unflagged, until that subject's current-run job actually
finishes. `collect_rows` used to scan for any `report/`+`label` XML on disk
regardless of the ledger, so mid-run it silently re-ingested stale output
from before the ledger was last reset as if it were fresh. Fixed: only a
subject/session whose ledger row is `status="succeeded"` is ingested —
matches this docstring's original (unenforced) claim.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd
import yaml

from bagpipe.app.cat12_parse import (
    SURFACE_ATLASES,
    SURFACE_METRIC_TAGS,
    parse_globals,
    parse_quality,
    parse_regional,
    parse_surface_regional,
)
from bagpipe.app.surface_atlas import SURFACE_METRICS, custom_surface_regional
from bagpipe.core.config import get_path
from bagpipe.db.base import get_engine, init_db
from bagpipe.db.ingest_cat12 import _SES_RE, QUALITY_COLUMNS, _subject_ids
from bagpipe.db.models import Cat12Quality, Feature
from bagpipe.db.upsert import upsert_rows

SOURCE = "cat12_v26"
DEFAULT_ATLAS_NAME = "Schaefer2018N400n7Tian2020S2"
DEFAULT_ATLAS_KEY = "schaefer2018n400n7tian2020s2"  # no "__toCAT12" suffix on CAT26, see docstring
DEFAULT_METRICS = ["vol_gm", "vol_wm", "vol_csf"]
GLOBAL_METRICS = ["TIV", "vol_csf", "vol_gm", "vol_wm", "vol_wmh"]

# CAT12's own surface-ROI own-atlas batch field doesn't work in this build
# (docs/cat12_container_spec.md §4b) — computed post-hoc in Python instead
# from CAT12's own native thickness + sphere.reg output
# (bagpipe.app.surface_atlas), not from catROIs_*.xml like SURFACE_ATLASES.
CUSTOM_SURFACE_ATLAS_NAME = "surf_Schaefer2018N400n7"


def _custom_surface_rows(surf_dir: Path, base: dict) -> list[dict]:
    """Best-effort — a mid-processing or surface-failed subject just won't
    have these native files yet, same "optional" treatment as `catrois_xml`
    above. Loops every metric in SURFACE_METRICS (thickness always present;
    gyrification/sulcal_depth/fractal_dimension/area only once `surfextract`
    output exists for this subject — see surface_atlas.py's docstring on
    verification status)."""
    lh_thickness = sorted(surf_dir.glob("lh.thickness.*"))
    if not lh_thickness:
        return []
    name = lh_thickness[0].name.removeprefix("lh.thickness.")
    lh_sphere_reg = surf_dir / f"lh.sphere.reg.{name}.gii"
    rh_sphere_reg = surf_dir / f"rh.sphere.reg.{name}.gii"
    if not (lh_sphere_reg.exists() and rh_sphere_reg.exists()):
        return []

    rows = []
    for metric_name, file_prefix in SURFACE_METRICS.items():
        lh_value = surf_dir / f"lh.{file_prefix}.{name}"
        rh_value = surf_dir / f"rh.{file_prefix}.{name}"
        if not (lh_value.exists() and rh_value.exists()):
            continue
        df = custom_surface_regional(
            lh_value,
            rh_value,
            lh_sphere_reg,
            rh_sphere_reg,
            get_path("surface_atlas_lh_annot"),
            get_path("surface_atlas_rh_annot"),
            get_path("surface_atlas_lh_ref_sphere"),
            get_path("surface_atlas_rh_ref_sphere"),
            metric=metric_name,
        )
        rows.extend(
            {
                **base,
                "atlas": CUSTOM_SURFACE_ATLAS_NAME,
                "region": r["label"],
                "metric": metric_name,
                "value": float(r[metric_name]),
            }
            for _, r in df.iterrows()
        )
    return rows


def cohort_dir_from_config(config_path: str | Path = "config/cat12_cohort.yaml") -> Path:
    config = yaml.safe_load(Path(config_path).read_text())
    return Path(config["output_derivatives_dir"])


def succeeded_session_ids(cohort_dir: Path) -> set[str] | None:
    """Session IDs the ledger currently marks `succeeded` — `None` (skip
    filtering) if no ledger exists yet. `t1w_path` looks like
    `.../sub-X/ses-<session_id>/anat/...`."""
    ledger_path = cohort_dir / ".bagpipe_cat12_ledger.sqlite"
    if not ledger_path.exists():
        return None
    con = sqlite3.connect(ledger_path)
    try:
        paths = con.execute("select t1w_path from subjects where status='succeeded'").fetchall()
    finally:
        con.close()
    sessions = set()
    for (path,) in paths:
        m = re.search(r"ses-([^/]+)", path)
        if m:
            sessions.add(m.group(1))
    return sessions


def _feature_rows(
    catroi_xml: Path,
    cat_xml: Path,
    atlas_name: str,
    atlas_key: str,
    lut: pd.DataFrame,
    metrics: list[str],
    uid: str | None,
    legacy_id: str | None,
    session_id: str | None,
    catrois_xml: Path | None = None,
    surf_dir: Path | None = None,
) -> list[dict] | None:
    """Returns None (not []) when ROI output is missing/unparseable — lets
    the caller distinguish "no data yet" from "parsed, zero rows". Surface
    thickness (`catrois_xml`) is optional — a missing/failed surface run
    doesn't invalidate the (required) volume ROI rows."""
    subject_key = uid or legacy_id
    base = {
        "subject_key": subject_key,
        "uid": uid,
        "legacy_subject_id": legacy_id,
        "session_id": session_id,
        "source": SOURCE,
    }

    regional = parse_regional(catroi_xml, atlas_key, lut)
    if regional is None:
        return None
    rows = [
        {
            **base,
            "atlas": atlas_name,
            "region": r["label"],
            "metric": metric,
            "value": float(r[metric]),
        }
        for _, r in regional.iterrows()
        for metric in metrics
        if metric in r
    ]

    if catrois_xml is not None:
        for surf_key, surf_atlas_name in SURFACE_ATLASES.items():
            for metric_name in SURFACE_METRIC_TAGS:
                surf = parse_surface_regional(catrois_xml, surf_key, metric=metric_name)
                if surf is None:
                    continue
                rows.extend(
                    {
                        **base,
                        "atlas": surf_atlas_name,
                        "region": r["label"],
                        "metric": metric_name,
                        "value": float(r[metric_name]),
                    }
                    for _, r in surf.iterrows()
                )

    if surf_dir is not None:
        rows.extend(_custom_surface_rows(surf_dir, base))

    globals_ = parse_globals(cat_xml)
    rows.extend(
        {**base, "atlas": "", "region": "global", "metric": metric, "value": globals_[metric]}
        for metric in GLOBAL_METRICS
        if metric in globals_
    )
    return rows


def collect_rows(
    cohort_dir: Path,
    atlas_name: str = DEFAULT_ATLAS_NAME,
    atlas_key: str = DEFAULT_ATLAS_KEY,
    lut: pd.DataFrame | None = None,
    metrics: list[str] = DEFAULT_METRICS,
) -> tuple[list[dict], list[dict], dict]:
    """Returns (feature_rows, quality_rows, summary). `summary` counts
    sessions found/ingested/skipped-no-roi/skipped-no-report, per the repo's
    ingestion-module convention (log rows added/updated/skipped)."""
    lut = lut if lut is not None else pd.read_csv(get_path("atlas_lut_file"), sep="\t")

    feature_rows: list[dict] = []
    quality_rows: list[dict] = []
    summary = {
        "sessions_found": 0,
        "sessions_ingested": 0,
        "skipped_no_report": 0,
        "skipped_no_roi": 0,
        "skipped_not_succeeded": 0,
    }
    succeeded = succeeded_session_ids(cohort_dir)

    for sub_dir in sorted(cohort_dir.glob("sub-*")):
        uid, legacy_id = _subject_ids(sub_dir.name)
        if uid is None and legacy_id is None:
            continue
        subject_key = uid or legacy_id
        for ses_dir in sorted(sub_dir.glob("ses-*")):
            m = _SES_RE.match(ses_dir.name)
            session_id = m.group(1) if m else None
            if succeeded is not None and session_id not in succeeded:
                summary["skipped_not_succeeded"] += 1
                continue
            anat_dir = ses_dir / "anat"
            report_xmls = sorted(anat_dir.glob("report/cat_*.xml"))
            catroi_xmls = sorted(anat_dir.glob("label/catROI_*.xml"))
            catrois_xmls = sorted(anat_dir.glob("label/catROIs_*.xml"))
            if not report_xmls or not catroi_xmls:
                if anat_dir.is_dir():
                    summary["skipped_no_report"] += 1
                continue
            summary["sessions_found"] += 1
            cat_xml, catroi_xml = report_xmls[0], catroi_xmls[0]
            catrois_xml = catrois_xmls[0] if catrois_xmls else None
            surf_dir = anat_dir / "surf"

            rows = _feature_rows(
                catroi_xml,
                cat_xml,
                atlas_name,
                atlas_key,
                lut,
                metrics,
                uid,
                legacy_id,
                session_id,
                catrois_xml=catrois_xml,
                surf_dir=surf_dir if surf_dir.is_dir() else None,
            )
            if rows is None:
                summary["skipped_no_roi"] += 1
                continue
            feature_rows.extend(rows)
            summary["sessions_ingested"] += 1

            quality = parse_quality(cat_xml)
            if quality:
                row = {"subject_key": subject_key, "session_id": session_id, "source": SOURCE}
                row.update({col: quality.get(col) for col in QUALITY_COLUMNS})
                quality_rows.append(row)

    return feature_rows, quality_rows, summary


def ingest(
    cohort_dir: Path | None = None,
    config_path: str | Path = "config/cat12_cohort.yaml",
    atlas_name: str = DEFAULT_ATLAS_NAME,
    atlas_key: str = DEFAULT_ATLAS_KEY,
    metrics: list[str] = DEFAULT_METRICS,
) -> dict:
    cohort_dir = cohort_dir or cohort_dir_from_config(config_path)
    feature_rows, quality_rows, summary = collect_rows(
        cohort_dir, atlas_name=atlas_name, atlas_key=atlas_key, metrics=metrics
    )
    init_db()
    engine = get_engine()
    with engine.begin() as conn:
        upsert_rows(
            conn,
            Feature,
            feature_rows,
            ["subject_key", "session_id", "source", "atlas", "region", "metric"],
        )
        upsert_rows(conn, Cat12Quality, quality_rows, ["subject_key", "session_id", "source"])
    return {
        "rows_ingested": len(feature_rows),
        "quality_rows_ingested": len(quality_rows),
        **summary,
    }


if __name__ == "__main__":
    result = ingest()
    print(
        f"CAT12 cohort ingest: {result['sessions_ingested']}/{result['sessions_found']} sessions, "
        f"{result['rows_ingested']} feature rows, {result['quality_rows_ingested']} QC rows, "
        f"skipped {result['skipped_no_report']} (no report yet), "
        f"{result['skipped_no_roi']} (no ROI output), "
        f"{result['skipped_not_succeeded']} (ledger not succeeded)"
    )
