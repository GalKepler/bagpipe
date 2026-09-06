"""Paired subject-bootstrap comparison between two `evaluate()` runs.

`EvalResult.metrics` is a point estimate off one (possibly seed-varying,
`repeats>1`) CV run — not enough to tell a 0.31y leaderboard gap from noise.
Resampling *subjects* (not rows: a subject can have multiple sessions, and
those must resample together to keep the bootstrap's independence assumption
honest) gives the gap a confidence interval.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bagpipe.models.evaluate import EvalResult


def paired_bootstrap(
    result_a: EvalResult,
    result_b: EvalResult,
    groups_a: np.ndarray,
    groups_b: np.ndarray,
    metric: str = "mae_corrected",
    n: int = 2000,
    random_state: int = 0,
) -> tuple[float, float, float]:
    """Returns `(delta, lo, hi)` for `metric(a) - metric(b)` — the observed
    difference and a 95% CI over subject resampling. `delta < 0` means `a`
    beats `b`. `groups_a`/`groups_b` are the `groups` array `evaluate()` was
    called with — same length/order as `result.predictions["index"]` was
    drawn from, so `groups_a[result_a.predictions["index"]]` recovers each
    prediction row's subject.

    A challenger should only be promoted over an incumbent when this CI
    excludes 0.
    """
    col = "y_pred_corrected" if metric == "mae_corrected" else "y_pred_raw"

    def _subject_means(result: EvalResult, groups: np.ndarray) -> np.ndarray:
        df = result.predictions.copy()
        df["subject"] = np.asarray(groups)[df["index"].to_numpy()]
        df["abs_err"] = (df[col] - df["y_true"]).abs()
        # one mean per subject (their sessions collapse to one unit) — the
        # resampling unit, so a multi-session subject isn't double-weighted
        # and repeated draws of the same subject in a bootstrap sample
        # actually change that sample's mean, unlike an `isin`-filtered mean
        # (which is insensitive to how many times a subject was drawn).
        return df.groupby("subject")["abs_err"].mean().to_numpy()

    means_a = _subject_means(result_a, groups_a)
    means_b = _subject_means(result_b, groups_b)
    observed = float(means_a.mean() - means_b.mean())

    rng = np.random.default_rng(random_state)
    deltas = np.empty(n)
    for i in range(n):
        sample_a = rng.choice(means_a, size=len(means_a), replace=True)
        sample_b = rng.choice(means_b, size=len(means_b), replace=True)
        deltas[i] = sample_a.mean() - sample_b.mean()

    lo, hi = np.percentile(deltas, [2.5, 97.5])
    return observed, float(lo), float(hi)


if __name__ == "__main__":
    # ponytail: smoke-check only, the real check is tests/test_compare.py
    a = pd.DataFrame({"index": range(10), "y_true": 30.0, "y_pred_corrected": 32.0})
    b = pd.DataFrame({"index": range(10), "y_true": 30.0, "y_pred_corrected": 30.5})
    groups = np.arange(10)
    delta, lo, hi = paired_bootstrap(
        EvalResult(a, {}), EvalResult(b, {}), groups, groups, n=200
    )
    print(f"delta={delta:.2f} ci=({lo:.2f}, {hi:.2f})")
