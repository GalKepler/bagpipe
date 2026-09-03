"""Materialize model-ready Parquet tables from the long `features` store.

Three tables, all keyed by (subject_key, session_id) — the subject-grouping
key CV must split on. Regenerated fully on each run — these are a cache, not
a store.

  - globals.parquet:      wide, one row per session — age/sex/lab + global
                           CAT12 scalars (TIV, vol_gm/wm/csf/wmh). Tabular
                           model input.
  - regional.parquet:     long, one row per (session, atlas, region, metric)
                           ROI value. Per-region base-learner input for the
                           stacked ensemble; join globals for age/cohort.
  - image_paths.parquet:  one row per session — mwp1/wm NIfTI paths. CNN
                           input.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from bagpipe.app.pipeline.qc import DEFAULT_IQR_THRESHOLD
from bagpipe.core.config import get_path
from bagpipe.db.base import get_engine
from bagpipe.db.ingest_cat12_cohort import cohort_dir_from_config, succeeded_session_ids

GLOBAL_METRICS = ["TIV", "vol_gm", "vol_wm", "vol_csf", "vol_wmh"]

# source="cat12_v26" is a from-scratch reprocessing run still in progress —
# `features` rows for that source can include stale pre-reset output not yet
# redone this run (see ingest_cat12_cohort.py's ledger-scoping fix,
# 2026-08-25). Exporting must apply the same ledger filter, or a session
# ingested before the fix (and not yet reprocessed) leaks into training.
LEDGER_SCOPED_SOURCES = {"cat12_v26"}


def _cohorts(engine) -> pd.DataFrame:
    """subject_key, session_id, cohort, lab, age, sex — one row per session."""
    snbb = pd.read_sql(
        """
        select s.uid as subject_key, s.session_id, s.lab, d.age_at_scan as age, d.sex
        from session s
        left join demographics d on d.session_id = s.session_id
        where s.uid is not null
        """,
        engine,
    )
    snbb["cohort"] = "snbb"
    legacy = pd.read_sql(
        """
        select subject_id as subject_key, subject_id as session_id,
               lab, age_at_scan as age, gender as sex
        from legacy_participant
        """,
        engine,
    )
    legacy["cohort"] = "legacy"
    return pd.concat([snbb, legacy], ignore_index=True)


def _globals(engine, cohorts: pd.DataFrame, source: str | None) -> pd.DataFrame:
    query = "select subject_key, session_id, metric, value from features where region = 'global'"
    params = {}
    if source is not None:
        query += " and source = :source"
        params["source"] = source
    long_df = pd.read_sql(query, engine, params=params)
    wide = long_df.pivot_table(
        index=["subject_key", "session_id"], columns="metric", values="value"
    ).reset_index()
    table = cohorts.merge(wide, on=["subject_key", "session_id"], how="inner")
    return table[["subject_key", "session_id", "cohort", "lab", "age", "sex"] + GLOBAL_METRICS]


def _regional(engine, cohorts: pd.DataFrame, source: str | None) -> pd.DataFrame:
    query = (
        "select subject_key, session_id, atlas, region, metric, value "
        "from features where region != 'global'"
    )
    params = {}
    if source is not None:
        query += " and source = :source"
        params["source"] = source
    long_df = pd.read_sql(query, engine, params=params)
    cohort_key = cohorts[["subject_key", "session_id", "cohort"]]
    return long_df.merge(cohort_key, on=["subject_key", "session_id"], how="inner")


def _image_paths(engine, cohorts: pd.DataFrame) -> pd.DataFrame:
    snbb = pd.read_sql(
        "select uid as subject_key, session_id, processing_stream, filepath from imaging_path",
        engine,
    )
    legacy = pd.read_sql(
        "select subject_id as subject_key, session_id, processing_stream, filepath "
        "from legacy_imaging_path",
        engine,
    )
    paths = pd.concat([snbb, legacy], ignore_index=True)
    wide = paths.pivot_table(
        index=["subject_key", "session_id"], columns="processing_stream", values="filepath",
        aggfunc="first",
    ).reset_index()
    wide = wide.rename(columns={"mwp1": "image_path_mwp1", "wm": "image_path_wm"})
    cohort_key = cohorts[["subject_key", "session_id", "cohort"]]
    return cohort_key.merge(wide, on=["subject_key", "session_id"], how="inner")


def _qc_failed_session_ids(engine, source: str | None) -> set[str]:
    """Session IDs with a recorded SIQR below the same QC threshold the app's
    upload pipeline gates on (`qc.DEFAULT_IQR_THRESHOLD`) — e.g. subject
    200707270944 (SIQR 65.71%, grade D), which had no filter keeping it out
    of training data before this. Sessions with no recorded quality row are
    left alone (unknown, not gated)."""
    query = "select session_id from cat12_quality where siqr_pct < :threshold"
    params: dict = {"threshold": DEFAULT_IQR_THRESHOLD}
    if source is not None:
        query += " and source = :source"
        params["source"] = source
    return set(pd.read_sql(query, engine, params=params)["session_id"])


def export(out_dir: Path | None = None, source: str | None = None) -> dict:
    """`source` filters `features` rows (e.g. "cat12_v26" for the CAT26
    reprocessing cohort only) — `None` keeps the old behavior of pooling every
    CAT version together, which double-counts sessions reprocessed under both.
    """
    out_dir = out_dir or get_path("datasets_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    engine = get_engine()
    cohorts = _cohorts(engine)

    tables = {
        "globals": _globals(engine, cohorts, source),
        "regional": _regional(engine, cohorts, source),
        "image_paths": _image_paths(engine, cohorts),
    }

    if source in LEDGER_SCOPED_SOURCES:
        succeeded = succeeded_session_ids(cohort_dir_from_config())
        if succeeded is not None:
            tables = {name: t[t["session_id"].isin(succeeded)] for name, t in tables.items()}

    qc_failed = _qc_failed_session_ids(engine, source)
    tables = {name: t[~t["session_id"].isin(qc_failed)] for name, t in tables.items()}

    summary = {}
    for name, table in tables.items():
        out_path = out_dir / f"{name}.parquet"
        table.to_parquet(out_path, index=False)
        summary[name] = {"rows": len(table), "out_path": str(out_path)}
    return summary


if __name__ == "__main__":
    for name, s in export().items():
        print(f"{name}: {s['rows']} rows -> {s['out_path']}")
