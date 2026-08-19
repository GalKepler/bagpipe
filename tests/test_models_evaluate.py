"""Synthetic-data checks for the CV harness — no real subject data involved."""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.linear_model import LinearRegression

from bagpipe.models.bias_correction import BeheshtiCorrection, ColeCorrection, get_corrector
from bagpipe.models.evaluate import evaluate


def _synthetic(n_subjects=40, sessions_per_subject=3, seed=0):
    rng = np.random.default_rng(seed)
    subject_age = rng.uniform(20, 80, size=n_subjects)
    groups, age, noise = [], [], []
    for sid, base_age in enumerate(subject_age):
        for _ in range(sessions_per_subject):
            groups.append(sid)
            age.append(base_age + rng.normal(0, 0.5))
            noise.append(rng.normal(0, 3))
    age = np.array(age)
    noise = np.array(noise)
    X = age.reshape(-1, 1) + rng.normal(0, 1, size=(len(age), 1))
    y = age  # true chronological age
    return X, y, np.array(groups), noise


def test_groups_never_span_train_test():
    X, y, groups, _ = _synthetic()
    seen_test_groups = set()
    from sklearn.model_selection import GroupKFold

    for train_idx, test_idx in GroupKFold(n_splits=5).split(X, y, groups):
        train_groups = set(groups[train_idx])
        test_groups = set(groups[test_idx])
        assert train_groups.isdisjoint(test_groups)
        seen_test_groups |= test_groups
    assert seen_test_groups == set(groups)


def test_evaluate_returns_metrics_and_predictions():
    X, y, groups, _ = _synthetic()
    result = evaluate(lambda: LinearRegression(), X, y, groups, n_splits=5)
    assert len(result.predictions) == len(y)
    for key in ("mae_raw", "mae_corrected", "r2_raw", "r2_corrected"):
        assert key in result.metrics
        assert np.isfinite(result.metrics[key])


def test_cole_correction_no_leakage_needs_no_true_age_at_apply():
    corrector = ColeCorrection()
    y_true = np.linspace(20, 80, 50)
    y_pred = 0.8 * y_true + 5  # simulated regression-to-the-mean bias
    corrector.fit(y_true, y_pred)
    corrected = corrector.transform(y_pred)  # no y_true passed — must work
    assert np.allclose(corrected, y_true, atol=1e-8)


def test_beheshti_correction_requires_true_age():
    corrector = BeheshtiCorrection()
    y_true = np.linspace(20, 80, 50)
    y_pred = y_true + 0.1 * (y_true - 50)
    corrector.fit(y_true, y_pred)
    with pytest.raises(ValueError):
        corrector.transform(y_pred)
    corrected = corrector.transform(y_pred, y_true)
    assert np.allclose(corrected, y_true, atol=1e-8)


def test_get_corrector_rejects_unknown_name():
    with pytest.raises(ValueError):
        get_corrector("not-a-real-method")


class _ShrinkToMean:
    """Deliberately biased model: regresses toward the training mean age,
    the classic brain-age regression-to-the-mean artifact Cole correction
    targets."""

    def fit(self, X, y):
        self._mean = y.mean()
        self._reg = LinearRegression().fit(X, y)
        return self

    def predict(self, X):
        return self._mean + 0.5 * (self._reg.predict(X) - self._mean)


def test_evaluate_with_bias_correction_improves_mae_on_biased_model():
    X, y, groups, _ = _synthetic()
    result = evaluate(_ShrinkToMean, X, y, groups, n_splits=5, bias_corrector=get_corrector("cole"))
    assert result.metrics["mae_corrected"] < result.metrics["mae_raw"]
