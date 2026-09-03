"""region_importance against a tiny real (fast) RegionalStackingRegressor fit —
no real data, no MLflow/config plumbing exercised here (see promote.py/CLI for
the full run() path)."""

from __future__ import annotations

import numpy as np
from regional_stacker import RegionalStackingRegressor
from sklearn.linear_model import LinearRegression, Ridge

from bagpipe.models.covariate_adjustment import TIVSexAdjustedRegressor
from bagpipe.models.stacked import region_importance


def test_region_importance_ranks_regions_by_meta_coef():
    rng = np.random.default_rng(0)
    n = 60
    region_a = rng.normal(size=(n, 1))  # strongly predictive of age
    region_b = rng.normal(size=(n, 1))  # noise
    age = 3 * region_a[:, 0] + rng.normal(scale=0.1, size=n) + 50
    tiv = rng.uniform(1200, 1700, n)
    sex = rng.integers(0, 2, n).astype(float)

    X = np.column_stack([region_a, region_b, tiv, sex])
    region_mapping = {"region_a": [0], "region_b": [1]}

    def stacker_fn():
        return RegionalStackingRegressor(
            region_mapping=region_mapping,
            base_estimator=LinearRegression(),
            meta_estimator=Ridge(alpha=1.0),
            outer_cv=3,
            inner_cv=2,
            random_state=0,
        )

    model = TIVSexAdjustedRegressor(stacker_fn)
    model.fit(X, age)

    importance = region_importance(model)
    assert set(importance) == {"region_a", "region_b"}
    assert importance["region_a"] > importance["region_b"]
