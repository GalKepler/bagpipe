"""Age-bias correction for brain-age predictions (DESIGN.md §4.1).

Two variants, selected by config: `cole` (default) corrects the prediction
alone — no true age needed at apply-time, so it works in Pillar 4 deployment
where chronological age of an uploaded scan may be unknown. `beheshti`
corrects the raw BAG using true age, which requires chronological age at
apply-time (fine for offline eval; for deployment only if age is collected).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from sklearn.linear_model import LinearRegression


class BiasCorrector(Protocol):
    def fit(self, y_true: np.ndarray, y_pred: np.ndarray) -> BiasCorrector: ...
    def transform(self, y_pred: np.ndarray, y_true: np.ndarray | None = None) -> np.ndarray: ...


class NoCorrection:
    def fit(self, y_true: np.ndarray, y_pred: np.ndarray) -> NoCorrection:
        return self

    def transform(self, y_pred: np.ndarray, y_true: np.ndarray | None = None) -> np.ndarray:
        return np.asarray(y_pred)


@dataclass
class ColeCorrection:
    """de Lange & Cole (2017): corrected = (pred - intercept) / slope.

    Fits predicted ~ a*true + b on training folds; inverts it on test
    predictions. Needs only the prediction at apply-time.
    """

    slope_: float = 1.0
    intercept_: float = 0.0

    def fit(self, y_true: np.ndarray, y_pred: np.ndarray) -> ColeCorrection:
        y_true = np.asarray(y_true)
        reg = LinearRegression().fit(y_true.reshape(-1, 1), np.asarray(y_pred))
        self.slope_ = float(reg.coef_[0])
        self.intercept_ = float(reg.intercept_)
        return self

    def transform(self, y_pred: np.ndarray, y_true: np.ndarray | None = None) -> np.ndarray:
        return (np.asarray(y_pred) - self.intercept_) / self.slope_


@dataclass
class BeheshtiCorrection:
    """Beheshti et al. (2019): fit BAG = a*true + b on training folds,
    subtract the fitted trend from test BAG. Requires true age at apply-time.
    """

    slope_: float = 0.0
    intercept_: float = 0.0

    def fit(self, y_true: np.ndarray, y_pred: np.ndarray) -> BeheshtiCorrection:
        y_true = np.asarray(y_true)
        bag = np.asarray(y_pred) - y_true
        reg = LinearRegression().fit(y_true.reshape(-1, 1), bag)
        self.slope_ = float(reg.coef_[0])
        self.intercept_ = float(reg.intercept_)
        return self

    def transform(self, y_pred: np.ndarray, y_true: np.ndarray | None = None) -> np.ndarray:
        if y_true is None:
            raise ValueError("BeheshtiCorrection needs true age at apply-time")
        y_true = np.asarray(y_true)
        bag = np.asarray(y_pred) - y_true
        trend = self.slope_ * y_true + self.intercept_
        return y_true + (bag - trend)


def fit_region_correctors(model, X: np.ndarray, y: np.ndarray) -> dict[str, ColeCorrection]:
    """Fits one `ColeCorrection` per region on a `TIVSexAdjustedRegressor`-wrapped
    `RegionalStackingRegressor`'s own per-region age predictions, and stores the
    result as `model.model_.region_correctors_`.

    Called at promotion time (see `bagpipe.models.promote`), on the same
    full-data `X`/`y` the final artifact is refit on — in-sample, same caveat
    as `region_estimators_` itself: real out-of-sample for any session added
    to the cohort since promotion, in-sample for sessions the model trained
    on. Raw (`region_estimators_`) is untouched and still feeds the
    meta-learner; these correctors are for region-level analysis only.
    """
    region_x, tiv, sex = X[:, :-2], X[:, -2], X[:, -1]
    residuals = model.adjuster_.transform(region_x, tiv, sex)
    stacker = model.model_
    correctors = {
        rname: ColeCorrection().fit(
            y, stacker.region_estimators_[rname].predict(residuals[:, stacker.region_columns_[rname]])
        )
        for rname in stacker.region_names_
    }
    stacker.region_correctors_ = correctors
    return correctors


CORRECTORS = {
    "none": NoCorrection,
    "cole": ColeCorrection,
    "beheshti": BeheshtiCorrection,
}


def get_corrector(name: str) -> BiasCorrector:
    try:
        return CORRECTORS[name]()
    except KeyError as e:
        raise ValueError(f"unknown bias correction {name!r}, choose from {list(CORRECTORS)}") from e
