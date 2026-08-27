"""Bias correctors against synthetic data — no real subjects."""

from __future__ import annotations

import numpy as np
from regional_stacker import RegionalStackingRegressor
from sklearn.linear_model import Ridge

from bagpipe.models.bias_correction import ColeCorrection, fit_region_correctors
from bagpipe.models.covariate_adjustment import TIVSexAdjustedRegressor


def test_cole_correction_flattens_bias():
    rng = np.random.default_rng(0)
    y_true = rng.uniform(20, 80, size=200)
    y_pred = 0.5 * y_true + 20 + rng.normal(0, 1, size=200)  # attenuated, biased predictor

    corrected = ColeCorrection().fit(y_true, y_pred).transform(y_pred)
    raw_slope = np.polyfit(y_true, y_pred, 1)[0]
    corrected_slope = np.polyfit(y_true, corrected, 1)[0]
    assert abs(corrected_slope - 1.0) < abs(raw_slope - 1.0)


def test_fit_region_correctors_stores_one_per_region_and_flattens_bias():
    rng = np.random.default_rng(0)
    n = 120
    region_x = rng.normal(0, 1, size=(n, 4))  # 2 regions x 2 metrics each
    tiv = rng.uniform(1400, 1600, size=n)
    sex = rng.integers(0, 2, size=n)
    y = rng.uniform(20, 80, size=n)
    # attenuated per-region signal, same shape as a real biased regional predictor
    region_x[:, :2] += (0.3 * y)[:, None]
    region_x[:, 2:] += (0.3 * y)[:, None]
    X = np.column_stack([region_x, tiv, sex])

    region_mapping = {"atlasA__r1": [0, 1], "atlasA__r2": [2, 3]}
    model = TIVSexAdjustedRegressor(
        lambda: RegionalStackingRegressor(
            region_mapping=region_mapping, base_estimator=Ridge(), meta_estimator=Ridge(), outer_cv=3
        )
    )
    model.fit(X, y)

    correctors = fit_region_correctors(model, X, y)

    assert set(correctors) == {"atlasA__r1", "atlasA__r2"}
    assert correctors is model.model_.region_correctors_
    for rname, corrector in correctors.items():
        assert isinstance(corrector, ColeCorrection)
        raw_pred = model.model_.region_estimators_[rname].predict(
            model.adjuster_.transform(X[:, :-2], tiv, sex)[:, model.model_.region_columns_[rname]]
        )
        corrected_pred = corrector.transform(raw_pred)
        raw_slope = np.polyfit(y, raw_pred, 1)[0]
        corrected_slope = np.polyfit(y, corrected_pred, 1)[0]
        assert abs(corrected_slope - 1.0) < abs(raw_slope - 1.0)
