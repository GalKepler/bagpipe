"""TIV/sex adjustment for region-wise volumes.

Per-region linear regression against TIV + sex, fit on the training fold
only and applied as residuals — same leakage-safe fit-on-train pattern as
`bias_correction`. `TIVSexAdjustedRegressor` wraps a base regressor so it
plugs straight into `bagpipe.models.evaluate.evaluate`'s `model_fn` factory.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np


class RegionAdjuster:
    """Fits region_volume ~ TIV + sex + 1 per region column; transforms to residuals."""

    def fit(self, region_x: np.ndarray, tiv: np.ndarray, sex: np.ndarray) -> RegionAdjuster:
        design = np.column_stack([tiv, sex, np.ones(len(tiv))])
        self.coefs_, *_ = np.linalg.lstsq(design, region_x, rcond=None)
        return self

    def transform(self, region_x: np.ndarray, tiv: np.ndarray, sex: np.ndarray) -> np.ndarray:
        design = np.column_stack([tiv, sex, np.ones(len(tiv))])
        return region_x - design @ self.coefs_


def _fillna(region_x: np.ndarray, medians: np.ndarray) -> np.ndarray:
    mask = np.isnan(region_x)
    if not mask.any():
        return region_x
    region_x = region_x.copy()
    region_x[mask] = np.take(medians, np.where(mask)[1])
    return region_x


class TIVSexAdjustedRegressor:
    """X columns must be `[region_1, ..., region_k, TIV, sex]` (see
    `bagpipe.models.tabular.build_region_matrix`). Region columns may
    contain NaN (a session missing that metric/atlas) — median-imputed
    here, fit on train only, before TIV+sex adjustment, so a session
    missing some regions no longer has to be dropped entirely at
    `build_region_matrix` time. Then adjusts regions for TIV+sex — also fit
    on train only — and hands residuals to `base_model_fn()`.
    """

    def __init__(self, base_model_fn: Callable[[], object]):
        self.base_model_fn = base_model_fn

    def fit(self, X: np.ndarray, y: np.ndarray) -> TIVSexAdjustedRegressor:
        region_x, tiv, sex = X[:, :-2], X[:, -2], X[:, -1]
        medians = np.nanmedian(region_x, axis=0)
        self.region_medians_ = np.where(np.isnan(medians), 0.0, medians)
        region_x = _fillna(region_x, self.region_medians_)
        self.adjuster_ = RegionAdjuster().fit(region_x, tiv, sex)
        residuals = self.adjuster_.transform(region_x, tiv, sex)
        self.model_ = self.base_model_fn()
        self.model_.fit(residuals, y)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        region_x, tiv, sex = X[:, :-2], X[:, -2], X[:, -1]
        region_x = _fillna(region_x, self.region_medians_)
        residuals = self.adjuster_.transform(region_x, tiv, sex)
        return np.asarray(self.model_.predict(residuals))
