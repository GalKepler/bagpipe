"""Subject-grouped CV evaluation harness (DESIGN.md §4.1 non-negotiable rules).

Every model type (tabular, stacked ensemble, CNN) runs through this same
engine so leaderboards are comparable on identical splits. Callers pull
X/y/groups from the Parquet exports produced by `bag export training-table`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold

from bagpipe.models.bias_correction import BiasCorrector, NoCorrection


class Regressor(Protocol):
    def fit(self, X, y) -> object: ...
    def predict(self, X) -> np.ndarray: ...


@dataclass
class EvalResult:
    predictions: pd.DataFrame  # one row/test sample: fold, index, y_true, y_pred_raw/corrected
    metrics: dict[str, float]  # mae_raw, mae_corrected, r2_raw, r2_corrected


def evaluate(
    model_fn: Callable[[], Regressor],
    X: np.ndarray | pd.DataFrame,
    y: np.ndarray | pd.Series,
    groups: np.ndarray | pd.Series,
    n_splits: int = 5,
    bias_corrector: BiasCorrector | None = None,
    bias_cv_splits: int = 5,
) -> EvalResult:
    """Subject-grouped CV: a subject's sessions never span train/test.

    `model_fn` returns a fresh, unfit regressor each call — avoids relying on
    sklearn's `clone()`, so non-sklearn models (the stacked ensemble, SFCN
    wrappers) work the same way.

    `bias_corrector` is fit on nested out-of-fold predictions from *within*
    the training fold, not on the fold model's in-sample training
    predictions. In-sample predictions from a flexible model (e.g. a
    boosted-tree ensemble that nearly memorizes the training set) look
    almost unbiased regardless of the model's real out-of-sample bias, so
    fitting the corrector on them barely corrects anything on the test
    fold. The nested CV gives a held-out estimate of the model's actual
    age-bias instead. Defaults to no correction (skips the nested CV).
    """
    bias_corrector = bias_corrector or NoCorrection()
    y = np.asarray(y)
    groups = np.asarray(groups)
    X_arr = X.values if isinstance(X, pd.DataFrame) else np.asarray(X)

    gkf = GroupKFold(n_splits=n_splits)
    rows = []
    for fold_i, (train_idx, test_idx) in enumerate(gkf.split(X_arr, y, groups)):
        model = model_fn()
        model.fit(X_arr[train_idx], y[train_idx])
        pred_test = np.asarray(model.predict(X_arr[test_idx]))

        if not isinstance(bias_corrector, NoCorrection):
            train_groups = groups[train_idx]
            inner_splits = min(bias_cv_splits, len(np.unique(train_groups)))
            inner_gkf = GroupKFold(n_splits=inner_splits)
            oof_pred = np.empty(len(train_idx))
            for inner_train_rel, inner_val_rel in inner_gkf.split(
                X_arr[train_idx], y[train_idx], train_groups
            ):
                inner_model = model_fn()
                inner_model.fit(X_arr[train_idx][inner_train_rel], y[train_idx][inner_train_rel])
                oof_pred[inner_val_rel] = inner_model.predict(X_arr[train_idx][inner_val_rel])
            bias_corrector.fit(y[train_idx], oof_pred)

        pred_test_corrected = bias_corrector.transform(pred_test, y[test_idx])

        rows.append(
            pd.DataFrame(
                {
                    "fold": fold_i,
                    "index": test_idx,
                    "y_true": y[test_idx],
                    "y_pred_raw": pred_test,
                    "y_pred_corrected": pred_test_corrected,
                }
            )
        )

    predictions = pd.concat(rows, ignore_index=True)
    metrics = {
        "mae_raw": mean_absolute_error(predictions["y_true"], predictions["y_pred_raw"]),
        "mae_corrected": mean_absolute_error(
            predictions["y_true"], predictions["y_pred_corrected"]
        ),
        "r2_raw": r2_score(predictions["y_true"], predictions["y_pred_raw"]),
        "r2_corrected": r2_score(predictions["y_true"], predictions["y_pred_corrected"]),
    }
    return EvalResult(predictions=predictions, metrics=metrics)
