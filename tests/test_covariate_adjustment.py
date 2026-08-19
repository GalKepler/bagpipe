"""Synthetic-data checks for TIV/sex region adjustment — no real data involved."""

from __future__ import annotations

import numpy as np
from sklearn.linear_model import LinearRegression

from bagpipe.models.covariate_adjustment import RegionAdjuster, TIVSexAdjustedRegressor
from bagpipe.models.evaluate import evaluate


def _synthetic(n=200, seed=0):
    rng = np.random.default_rng(seed)
    tiv = rng.uniform(1200, 1700, n)
    sex = rng.integers(0, 2, n).astype(float)
    age = rng.uniform(20, 80, n)
    # region volume driven by TIV + sex + a true age signal + noise
    region = 0.4 * tiv - 30 * sex - 2 * age + rng.normal(0, 5, n)
    X = np.column_stack([region, tiv, sex])
    return X, age, tiv, sex


def test_region_adjuster_removes_tiv_sex_correlation():
    X, age, tiv, sex = _synthetic()
    region = X[:, 0]
    adjuster = RegionAdjuster().fit(region.reshape(-1, 1), tiv, sex)
    residual = adjuster.transform(region.reshape(-1, 1), tiv, sex).ravel()
    assert abs(np.corrcoef(residual, tiv)[0, 1]) < 0.05
    assert abs(np.corrcoef(residual, sex)[0, 1]) < 0.05
    # age signal should survive adjustment
    assert abs(np.corrcoef(residual, age)[0, 1]) > 0.3


def test_tiv_sex_adjusted_regressor_fits_and_predicts():
    X, age, _, _ = _synthetic()
    groups = np.arange(len(age)) % 40  # fake subjects, no repeated sessions needed here
    model_fn = lambda: TIVSexAdjustedRegressor(lambda: LinearRegression())  # noqa: E731
    result = evaluate(model_fn, X, age, groups, n_splits=5)
    assert np.isfinite(result.metrics["mae_raw"])
    # adjusted model should beat a naive TIV/sex-blind fit by a wide margin
    assert result.metrics["mae_raw"] < 15
