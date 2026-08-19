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

from bagpipe.core.config import get_path
from bagpipe.db.base import get_engine

GLOBAL_METRICS = ["TIV", "vol_gm", "vol_wm", "vol_csf", "vol_wmh"]


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


def _globals(engine, cohorts: pd.DataFrame) -> pd.DataFrame:
    long_df = pd.read_sql(
        "select subject_key, session_id, metric, value from features where region = 'global'",
        engine,
    )
    wide = long_df.pivot_table(
        index=["subject_key", "session_id"], columns="metric", values="value"
    ).reset_index()
    table = cohorts.merge(wide, on=["subject_key", "session_id"], how="inner")
    return table[["subject_key", "session_id", "cohort", "lab", "age", "sex"] + GLOBAL_METRICS]


def _regional(engine, cohorts: pd.DataFrame) -> pd.DataFrame:
    long_df = pd.read_sql(
        "select subject_key, session_id, atlas, region, metric, value "
        "from features where region != 'global'",
        engine,
    )
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


def export(out_dir: Path | None = None) -> dict:
    out_dir = out_dir or get_path("datasets_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    engine = get_engine()
    cohorts = _cohorts(engine)

    tables = {
        "globals": _globals(engine, cohorts),
        "regional": _regional(engine, cohorts),
        "image_paths": _image_paths(engine, cohorts),
    }
    summary = {}
    for name, table in tables.items():
        out_path = out_dir / f"{name}.parquet"
        table.to_parquet(out_path, index=False)
        summary[name] = {"rows": len(table), "out_path": str(out_path)}
    return summary


if __name__ == "__main__":
    for name, s in export().items():
        print(f"{name}: {s['rows']} rows -> {s['out_path']}")
