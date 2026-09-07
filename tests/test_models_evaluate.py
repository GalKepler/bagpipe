"""Synthetic-data checks for the CV harness — no real subject data involved."""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.linear_model import LinearRegression

from bagpipe.models.bias_correction import BeheshtiCorrection, ColeCorrection, get_corrector
from bagpipe.models.evaluate import evaluate, inverse_age_density_weights


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
    result = evaluate(lambda fold_groups: LinearRegression(), X, y, groups, n_splits=5)
    assert len(result.predictions) == len(y)
    for key in ("mae_raw", "mae_corrected", "r2_raw", "r2_corrected", "mae_balanced_raw"):
        assert key in result.metrics
        assert np.isfinite(result.metrics[key])


def test_model_fn_receives_training_fold_groups():
    """model_fn(groups) — groups must be the training fold's own subject
    array, same length as the X/y that fold's fit() sees."""
    X, y, groups, _ = _synthetic()
    seen = []

    def model_fn(fold_groups):
        seen.append(fold_groups)
        return LinearRegression()

    evaluate(model_fn, X, y, groups, n_splits=5)
    assert len(seen) == 5  # one call per outer fold
    for fold_groups in seen:
        assert set(fold_groups) <= set(groups)
        assert len(fold_groups) < len(y)  # a training fold, not the whole set


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
    result = evaluate(
        lambda fold_groups: _ShrinkToMean(),
        X,
        y,
        groups,
        n_splits=5,
        bias_corrector=get_corrector("cole"),
    )
    assert result.metrics["mae_corrected"] < result.metrics["mae_raw"]


@pytest.mark.parametrize("method", ["lofo", "nested"])
def test_evaluate_with_bias_correction_improves_mae_on_biased_model_both_methods(method):
    X, y, groups, _ = _synthetic()
    result = evaluate(
        lambda fold_groups: _ShrinkToMean(),
        X,
        y,
        groups,
        n_splits=5,
        bias_corrector=get_corrector("cole"),
        bias_correction_method=method,
    )
    assert result.metrics["mae_corrected"] < result.metrics["mae_raw"]
    assert "cole_slope" in result.metrics


def test_lofo_and_nested_bias_correction_agree_within_noise():
    """Both methods estimate the same held-out bias — the cheap LOFO
    estimator (Phase 2) should land close to the 6x-more-expensive nested
    one (kept for exactly this validation) on a stable synthetic model."""
    X, y, groups, _ = _synthetic(n_subjects=80, sessions_per_subject=3)
    kwargs = dict(X=X, y=y, groups=groups, n_splits=5, bias_corrector=get_corrector("cole"))
    lofo = evaluate(lambda fold_groups: _ShrinkToMean(), bias_correction_method="lofo", **kwargs)
    nested = evaluate(
        lambda fold_groups: _ShrinkToMean(), bias_correction_method="nested", **kwargs
    )
    assert abs(lofo.metrics["cole_slope"] - nested.metrics["cole_slope"]) < 0.05
    assert abs(lofo.metrics["mae_corrected"] - nested.metrics["mae_corrected"]) < 0.5


def test_inverse_age_density_weights_upweights_sparse_ages():
    """Skewed synthetic cohort: 200 young (20-30), 10 old (70-80) — mirrors
    the real 82%-under-40 skew. Sparse old-age samples must get materially
    higher weight than dense young ones, and the cap must actually bind."""
    young = np.random.default_rng(0).uniform(20, 30, size=200)
    old = np.random.default_rng(1).uniform(70, 80, size=10)
    y = np.concatenate([young, old])
    weights = inverse_age_density_weights(y, n_bins=10, max_ratio=10.0)
    assert weights[:200].mean() < weights[200:].mean()
    assert weights.max() <= 10.0 + 1e-9
    assert np.isclose(weights.mean(), 1.0, atol=0.5)  # roughly mean-1 before capping


def test_unknown_sample_weighting_raises():
    X, y, groups, _ = _synthetic()
    with pytest.raises(ValueError):
        evaluate(lambda fold_groups: LinearRegression(), X, y, groups, sample_weighting="bogus")


def test_sample_weight_forwarded_only_when_requested():
    """A model that records what sample_weight it was called with — confirm
    evaluate() forwards weights on "inverse_age_density" and omits the
    kwarg entirely (not even sample_weight=None) on "none", so a model
    whose .fit() has no such parameter is unaffected either way."""
    X, y, groups, _ = _synthetic()
    calls = []

    class _RecordingModel:
        def fit(self, X, y, **kwargs):
            calls.append(kwargs)
            self._mean = y.mean()
            return self

        def predict(self, X):
            return np.full(len(X), self._mean)

    evaluate(lambda fold_groups: _RecordingModel(), X, y, groups, n_splits=5)
    assert all(c == {} for c in calls)

    calls.clear()
    evaluate(
        lambda fold_groups: _RecordingModel(),
        X,
        y,
        groups,
        n_splits=5,
        sample_weighting="inverse_age_density",
    )
    assert all("sample_weight" in c for c in calls)
