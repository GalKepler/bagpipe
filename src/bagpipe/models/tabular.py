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
    atlases: list[str] | None = None,
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

    `atlases` filters which atlas(es) contribute columns. Matters for a
    surface metric (thickness/gyrification/sulcal_depth/fractal_dimension):
    it exists on THREE surface atlases (surf_DK40, surf_Destrieux, and the
    custom surf_Schaefer2018N400n7 that actually matches the volume atlas'
    parcellation) — filtering by metric alone pulls in all three, which
    explodes per-region base-learner count. A surface-fusion config should
    still pass `atlases=["Schaefer2018N400n7Tian2020S2",
    "surf_Schaefer2018N400n7"]` to keep one consistent parcellation instead
    of `None` (every atlas).

    Rows missing individual region columns are kept (NaN passed through) —
    a session missing one metric/atlas no longer drops the whole row.
    `TIVSexAdjustedRegressor` median-imputes region NaNs fold-internally
    (fit on train only) before use, so this stays leakage-safe. Only rows
    missing `age`/`sex`/`TIV` (essential, rarely missing) are dropped.
    """
    datasets_dir = datasets_dir or get_path("datasets_dir")
    regional = pd.read_parquet(datasets_dir / "regional.parquet")
    globals_df = pd.read_parquet(datasets_dir / "globals.parquet")

    regional = regional.copy()
    if metrics is not None:
        regional = regional[regional["metric"].isin(metrics)]
    if atlases is not None:
        regional = regional[regional["atlas"].isin(atlases)]
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
    table = table.dropna(subset=["age", "sex", "TIV"])

    X = table[[*region_columns, "TIV", "sex"]].to_numpy(dtype=float)
    y = table["age"].to_numpy(dtype=float)
    groups = table["subject_key"].to_numpy()
    session_ids = table["session_id"].to_numpy()
    return X, y, groups, region_columns, session_ids


def region_columns_for(
    metrics: list[str] | None, datasets_dir: Path | None = None, atlases: list[str] | None = None
) -> list[str]:
    """The `atlas__region__metric` column order `build_region_matrix` would
    produce for `metrics`/`atlases` — i.e. what a promoted model's `X`
    columns are, without needing age/sex/TIV or a merge. Used at inference
    time (Pillar 4) to align a single freshly-parsed session onto the
    trained column space; `pivot_table`'s columns are alphabetically
    sorted, same as here.

    `metrics=None` means "every metric" — matches `build_region_matrix`'s
    `None` semantics (was previously required here, and `.isin(None)` would
    raise).
    """
    datasets_dir = datasets_dir or get_path("datasets_dir")
    regional = pd.read_parquet(
        datasets_dir / "regional.parquet", columns=["atlas", "region", "metric"]
    )
    if metrics is not None:
        regional = regional[regional["metric"].isin(metrics)]
    if atlases is not None:
        regional = regional[regional["atlas"].isin(atlases)]
    regional = regional.drop_duplicates()
    cols = regional["atlas"] + "__" + regional["region"] + "__" + regional["metric"]
    return sorted(cols.unique().tolist())


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


# Atlases that share one real parcellation but use different region-name
# conventions between CAT12's native volume ROI output and
# bagpipe.app.surface_atlas's custom surface resampling — e.g. the volume
# atlas calls a region "LH_Cont_Cing_1", the surface atlas calls the exact
# same region "7Networks_LH_Cont_Cing_1" (confirmed: stripping that prefix
# makes all 400 surface region names match volume region names exactly).
# Canonicalized so a region's volume AND its surface metrics land in ONE
# stacked-ensemble base learner, not two independent single-modality ones
# — the entire point of "per-region" stacking. Every other atlas keeps its
# own atlas-qualified key: names like `surf_DK40`'s FreeSurfer labels don't
# collide with Schaefer's, and fusing across genuinely different
# parcellations would silently mix unrelated anatomy.
_FUSIBLE_SCHAEFER_ATLASES = {"Schaefer2018N400n7Tian2020S2", "surf_Schaefer2018N400n7"}


def _region_key(atlas: str, region: str) -> str:
    if atlas in _FUSIBLE_SCHAEFER_ATLASES:
        return region.removeprefix("7Networks_")
    return f"{atlas}__{region}"


def build_region_mapping(region_columns: list[str]) -> dict[str, list[int]]:
    """Groups `region_columns` (format `atlas__region__metric`) into one
    base-learner block per anatomical region — see `_region_key`.

    The 32 Tian subcortical regions (part of
    `Schaefer2018N400n7Tian2020S2` but with no surface counterpart) still
    end up as their own singleton groups: canonicalizing a name nothing
    else matches is a no-op.

    Column indices are relative to `region_columns` only (i.e. before the
    trailing TIV/sex columns `build_region_matrix` appends) — pass straight
    to `RegionalStackingRegressor(region_mapping=...)` since
    `TIVSexAdjustedRegressor` strips TIV/sex before the base model sees `X`.
    """
    mapping: dict[str, list[int]] = {}
    for i, col in enumerate(region_columns):
        atlas, region, _metric = col.split("__", maxsplit=2)
        mapping.setdefault(_region_key(atlas, region), []).append(i)
    return mapping
