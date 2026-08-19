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
    metrics: list[str] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str], np.ndarray]:
    """Returns (X, y, groups, region_columns, session_ids).

    X columns: region volumes (one per atlas/region/metric) followed by
    TIV, sex. Rows with missing age, sex, or TIV are dropped.

    `metrics` filters which per-region measures are included (e.g.
    `["vol_gm"]` for a GM-volume-only flat tabular model). `None` includes
    every metric in `regional.parquet` — the flat feature vector then mixes
    GM/WM/CSF columns for the *same* region, which single-model tabular
    regressors (linear/ridge/lightgbm) can't distinguish from noise, so
    callers building a flat model should pass an explicit single-metric
    list. The stacked ensemble (`build_region_mapping`) is the one consumer
    that legitimately wants all metrics — grouped per region, not flattened.
    """
    datasets_dir = datasets_dir or get_path("datasets_dir")
    regional = pd.read_parquet(datasets_dir / "regional.parquet")
    globals_df = pd.read_parquet(datasets_dir / "globals.parquet")

    regional = regional.copy()
    if metrics is not None:
        regional = regional[regional["metric"].isin(metrics)]
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
    session_ids = table["session_id"].to_numpy()
    return X, y, groups, region_columns, session_ids


def build_image_matrix(
    datasets_dir: Path | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (paths, y, groups) for CNN input: `image_path_mwp1` (CAT12 GM
    density map, MNI space) per session, joined against `globals.parquet` for
    age. Rows with missing age or image path are dropped.
    """
    datasets_dir = datasets_dir or get_path("datasets_dir")
    images = pd.read_parquet(datasets_dir / "image_paths.parquet")
    globals_df = pd.read_parquet(datasets_dir / "globals.parquet")

    table = images.merge(
        globals_df[["subject_key", "session_id", "age"]],
        on=["subject_key", "session_id"],
        how="inner",
    )
    table = table.dropna(subset=["age", "image_path_mwp1"])

    paths = table["image_path_mwp1"].to_numpy(dtype=object)
    y = table["age"].to_numpy(dtype=float)
    groups = table["subject_key"].to_numpy()
    return paths, y, groups


def build_region_mapping(region_columns: list[str]) -> dict[str, list[int]]:
    """Groups `region_columns` (format `atlas__region__metric`) by `atlas__region`.

    Column indices are relative to `region_columns` only (i.e. before the
    trailing TIV/sex columns `build_region_matrix` appends) — pass straight
    to `RegionalStackingRegressor(region_mapping=...)` since
    `TIVSexAdjustedRegressor` strips TIV/sex before the base model sees `X`.
    """
    mapping: dict[str, list[int]] = {}
    for i, col in enumerate(region_columns):
        atlas, region, _metric = col.split("__", maxsplit=2)
        mapping.setdefault(f"{atlas}__{region}", []).append(i)
    return mapping
