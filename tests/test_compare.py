"""Synthetic checks for the paired subject-bootstrap comparator."""

from __future__ import annotations

import numpy as np
import pandas as pd

from bagpipe.models.compare import paired_bootstrap
from bagpipe.models.evaluate import EvalResult


def _result(n_subjects: int, offset: float, seed: int) -> tuple[EvalResult, np.ndarray]:
    rng = np.random.default_rng(seed)
    y_true = rng.uniform(20, 80, size=n_subjects)
    y_pred = y_true + offset + rng.normal(0, 1, size=n_subjects)
    predictions = pd.DataFrame(
        {
            "repeat": 0,
            "fold": 0,
            "index": np.arange(n_subjects),
            "y_true": y_true,
            "y_pred_raw": y_pred,
            "y_pred_corrected": y_pred,
        }
    )
    return EvalResult(predictions=predictions, metrics={}), np.arange(n_subjects)


def test_known_constant_offset_excludes_zero():
    result_a, groups_a = _result(200, offset=3.0, seed=0)
    result_b, groups_b = _result(200, offset=0.0, seed=1)
    delta, lo, hi = paired_bootstrap(result_a, result_b, groups_a, groups_b, n=1000, random_state=0)
    assert delta > 0
    assert lo > 0, "a is genuinely worse (larger |error|) — CI should exclude 0"


def test_identical_distributions_include_zero():
    result_a, groups_a = _result(200, offset=0.0, seed=0)
    result_b, groups_b = _result(200, offset=0.0, seed=1)
    delta, lo, hi = paired_bootstrap(result_a, result_b, groups_a, groups_b, n=1000, random_state=0)
    assert lo < 0 < hi
