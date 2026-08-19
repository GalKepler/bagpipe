"""Region-wise tabular model input, built from the `regional`/`globals` Parquet exports.

Wide matrix: one column per (atlas, region, metric) region volume, plus TIV
and sex as the last two columns — the layout `TIVSexAdjustedRegressor`
expects. Age is the target, subject_key the CV group.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from bagpipe.core.config import get_path

SEX_MAP = {
    "M": 0.0,
    "F": 1.0,
    "m": 0.0,
    "f": 1.0,
    "Male": 0.0,
    "Female": 1.0,
    "male": 0.0,
    "female": 1.0,
}


def build_region_matrix(
    datasets_dir: Path | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Returns (X, y, groups, region_columns).

    X columns: region volumes (one per atlas/region/metric) followed by
    TIV, sex. Rows with missing age, sex, or TIV are dropped.
    """
    datasets_dir = datasets_dir or get_path("datasets_dir")
    regional = pd.read_parquet(datasets_dir / "regional.parquet")
    globals_df = pd.read_parquet(datasets_dir / "globals.parquet")

    regional = regional.copy()
    regional["region_col"] = (
        regional["atlas"] + "__" + regional["region"] + "__" + regional["metric"]
    )
    wide = regional.pivot_table(
        index=["subject_key", "session_id"], columns="region_col", values="value"
    ).reset_index()
    region_columns = [c for c in wide.columns if c not in ("subject_key", "session_id")]

    covariates = globals_df[["subject_key", "session_id", "age", "sex", "TIV"]].copy()
    covariates["sex"] = covariates["sex"].map(SEX_MAP)

    table = wide.merge(covariates, on=["subject_key", "session_id"], how="inner")
    table = table.dropna(subset=["age", "sex", "TIV", *region_columns])

    X = table[[*region_columns, "TIV", "sex"]].to_numpy(dtype=float)
    y = table["age"].to_numpy(dtype=float)
    groups = table["subject_key"].to_numpy()
    return X, y, groups, region_columns
