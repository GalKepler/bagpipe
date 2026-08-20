"""Population norms for regional/global CAT12 measures (Pillar 4 report
content, DESIGN.md §6) — the `normative` project's approach (age/sex/TIV-
adjusted z-score, not a raw-mean comparison), ported in-line since Pillar 4
needs it as a library call, not a separate service.

`age` here is the model's own predicted (corrected) age, not chronological —
a fresh upload has no chronological age to condition on.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from bagpipe.core.config import get_path

SEX_MAP = {"M": 0.0, "F": 1.0, "m": 0.0, "f": 1.0, "Male": 0.0, "Female": 1.0}


@dataclass
class RegionNorm:
    coefs: np.ndarray  # [age, sex, TIV, intercept]
    resid_std: float


def fit_norms(
    region_columns: list[str], datasets_dir: Path | None = None
) -> dict[str, RegionNorm]:
    """Fits `value ~ age + sex + TIV` per region column on the full
    population, returning each column's coefficients and residual std (the
    denominator for a z-score). Cheap enough (OLS via lstsq) to refit per
    process rather than persist — call once per server lifetime and cache
    the result.
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

    covariates = globals_df[["subject_key", "session_id", "age", "sex", "TIV"]].copy()
    covariates["sex"] = covariates["sex"].map(SEX_MAP)
    table = wide.merge(covariates, on=["subject_key", "session_id"], how="inner")
    table = table.dropna(subset=["age", "sex", "TIV"])

    design = np.column_stack(
        [table["age"], table["sex"], table["TIV"], np.ones(len(table))]
    )
    norms: dict[str, RegionNorm] = {}
    for col in region_columns:
        if col not in table.columns:
            continue
        y = table[col].to_numpy(dtype=float)
        mask = ~np.isnan(y)
        if mask.sum() < 10:
            continue
        coefs, *_ = np.linalg.lstsq(design[mask], y[mask], rcond=None)
        resid = y[mask] - design[mask] @ coefs
        norms[col] = RegionNorm(coefs=coefs, resid_std=float(resid.std(ddof=1)) or 1.0)
    return norms


def regional_zscores(
    features: dict[str, float],
    norms: dict[str, RegionNorm],
    age: float,
    sex: float,
    tiv: float,
) -> dict[str, float]:
    """z = (observed - population-expected-at-this-age/sex/TIV) / resid_std."""
    x = np.array([age, sex, tiv, 1.0])
    zscores = {}
    for col, norm in norms.items():
        if col not in features:
            continue
        expected = float(x @ norm.coefs)
        zscores[col] = (features[col] - expected) / norm.resid_std
    return zscores
