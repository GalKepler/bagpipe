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
