"""Synthetic checks for the promotion-gating decision (no DB involved —
`_check_promotable` is the pure comparison logic `promote()` wraps)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from bagpipe.models.evaluate import EvalResult
from bagpipe.models.promote import _check_promotable


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


def test_no_incumbent_returns_none():
    result, groups = _result(50, offset=0.0, seed=0)
    assert _check_promotable(result, groups, incumbent=None) is None


def test_confidently_better_challenger_gets_negative_hi():
    challenger, groups_c = _result(200, offset=0.0, seed=0)  # near-zero error
    incumbent = _result(200, offset=3.0, seed=1)  # systematically worse
    delta, lo, hi = _check_promotable(challenger, groups_c, incumbent)
    assert delta < 0
    assert hi < 0  # promote() would accept this


def test_indistinguishable_challenger_ci_includes_zero():
    challenger, groups_c = _result(200, offset=0.0, seed=0)
    incumbent = _result(200, offset=0.0, seed=1)
    _delta, lo, hi = _check_promotable(challenger, groups_c, incumbent)
    assert lo < 0 < hi  # promote() would reject this (unless force=True)
