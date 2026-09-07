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
from sklearn.model_selection import StratifiedGroupKFold

from bagpipe.models.bias_correction import BiasCorrector, NoCorrection

# Age bands the per-band accuracy is reported in. Open-ended tails so a
# corrected prediction outside the model's own training support still lands
# somewhere. Canonical home for this constant — `bagpipe.app.pipeline.predict`
# imports it from here rather than redefining it, so the app-facing
# uncertainty text and the training-time leaderboard always agree.
AGE_BANDS: tuple[tuple[float, float], ...] = (
    (-float("inf"), 30.0),
    (30.0, 40.0),
    (40.0, 50.0),
    (50.0, 60.0),
    (60.0, 70.0),
    (70.0, float("inf")),
)


def band_label(lo: float, hi: float) -> str:
    lo_s = "<18" if lo == -float("inf") else f"{lo:.0f}"
    hi_s = "90+" if hi == float("inf") else f"{hi:.0f}"
    return f"{lo_s}-{hi_s}"


def _metric_key_band_label(lo: float, hi: float) -> str:
    """`band_label` output (e.g. `<18-30`, `70+`) isn't a legal MLflow metric
    name (no `<`/`+`) — a separate ASCII-only label for `metrics` dict keys."""
    lo_s = "under18" if lo == -float("inf") else f"{lo:.0f}"
    hi_s = "90plus" if hi == float("inf") else f"{hi:.0f}"
    return f"{lo_s}-{hi_s}"


def mae_by_band(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    bands: tuple[tuple[float, float], ...] = AGE_BANDS,
    label_fn: Callable[[float, float], str] = band_label,
) -> dict[str, float]:
    """Per-band MAE, keyed by `label_fn(lo, hi)` (default `band_label`, the
    human-readable form). A band with no samples is omitted (not zero — that
    would misleadingly claim perfect accuracy)."""
    y_true = np.asarray(y_true)
    err = np.abs(np.asarray(y_pred) - y_true)
    out = {}
    for lo, hi in bands:
        mask = (y_true >= lo) & (y_true < hi)
        if mask.any():
            out[label_fn(lo, hi)] = float(err[mask].mean())
    return out


class Regressor(Protocol):
    def fit(self, X, y) -> object: ...
    def predict(self, X) -> np.ndarray: ...


# `model_fn(groups)` — `groups` is the *training fold's own* subject-group
# array (same row order/length as the X/y that fold's `.fit()` will see).
# Most callers (baseline.py, sfcn.py) ignore it; `stacked.py` uses it to
# build a subject-grouped CV split for `RegionalStackingRegressor`'s
# internal OOF stage, which otherwise silently uses a plain (non-grouped)
# `KFold` — see evaluate()'s docstring.
ModelFactory = Callable[[np.ndarray], Regressor]


@dataclass
class EvalResult:
    predictions: pd.DataFrame  # per test sample: repeat, fold, index, y_true, y_pred_raw/corrected
    metrics: dict[str, float]  # mae_raw, mae_corrected, r2_raw, r2_corrected, mae_balanced, ...


def _age_strata(y: np.ndarray, n_bins: int) -> np.ndarray:
    """Age deciles (or fewer, if there aren't enough distinct ages)."""
    n_bins = min(n_bins, len(np.unique(y)))
    if n_bins < 2:
        return np.zeros(len(y), dtype=int)
    return pd.qcut(y, n_bins, labels=False, duplicates="drop").astype(int)


def _make_strata(y: np.ndarray, n_splits: int, max_bins: int) -> np.ndarray:
    """Age strata for `StratifiedGroupKFold`, guaranteed compatible with
    `n_splits` (every stratum has >= n_splits members) — keeps the old tail
    from landing lopsidedly in one fold, which plain `GroupKFold` has no way
    to prevent. Shrinks the bin count rather than `n_splits` when the data is
    small (a small/synthetic dataset's caller-requested fold count should be
    honored exactly; losing stratification resolution is the acceptable
    tradeoff), falling back to one bin (no stratification) in the limit.
    """
    for n_bins in range(min(max_bins, len(np.unique(y))), 0, -1):
        strata = _age_strata(y, n_bins)
        if int(np.min(np.bincount(strata))) >= n_splits:
            return strata
    return np.zeros(len(y), dtype=int)


def inverse_age_density_weights(
    y: np.ndarray, n_bins: int = 20, max_ratio: float = 10.0
) -> np.ndarray:
    """Per-sample weight = 1 / (age-histogram density at that sample),
    normalized to mean 1 and capped at `max_ratio` — so the training loss
    stops being dominated by the 18-40 mass (82% of this cohort) at the
    cost of the old tail, without letting a handful of subjects over 70
    swing the fit unboundedly. Computed on whatever `y` is passed in — the
    caller (`evaluate()`) must pass the training fold's own ages only, same
    leakage discipline as everything else fit "on train only" here.
    """
    counts, edges = np.histogram(y, bins=n_bins)
    bin_idx = np.clip(np.digitize(y, edges[1:-1]), 0, n_bins - 1)
    density = counts[bin_idx].astype(float)
    weights = 1.0 / density
    weights /= weights.mean()
    return np.minimum(weights, max_ratio)


SAMPLE_WEIGHTING = {
    "none": None,
    "inverse_age_density": inverse_age_density_weights,
}


def evaluate(
    model_fn: ModelFactory,
    X: np.ndarray | pd.DataFrame,
    y: np.ndarray | pd.Series,
    groups: np.ndarray | pd.Series,
    n_splits: int = 5,
    bias_corrector: BiasCorrector | None = None,
    bias_cv_splits: int = 5,
    bias_correction_method: str = "lofo",
    repeats: int = 1,
    random_state: int = 0,
    stratify_bins: int = 5,
    sample_weighting: str = "none",
) -> EvalResult:
    """Subject-grouped CV: a subject's sessions never span train/test.

    `model_fn(groups)` returns a fresh, unfit regressor each call — avoids
    relying on sklearn's `clone()`, so non-sklearn models (the stacked
    ensemble, SFCN wrappers) work the same way. `groups` is the training
    fold's own subject array, for models (the stacked ensemble) with their
    own internal grouped-CV needs; most callers ignore it.

    `bias_corrector` needs a held-out estimate of the model's raw
    prediction bias — fitting it on the fold model's in-sample training
    predictions barely corrects a flexible model (e.g. a boosted-tree
    ensemble that nearly memorizes the training set looks almost unbiased
    in-sample regardless of its real out-of-sample bias). Two ways to get
    that held-out estimate, chosen by `bias_correction_method`:

    - `"lofo"` (default): a leave-one-outer-fold-out estimator. All outer
      folds are fit once (as they would be anyway); fold k's corrector is
      then fit on the pooled *out-of-fold* test predictions of every OTHER
      outer fold — never fold k's own subjects, so it's exactly as
      leakage-free as the nested version, at `n_splits` model fits total
      instead of `n_splits * (1 + bias_cv_splits)`.
    - `"nested"`: refits the model on an inner grouped split *within* each
      training fold to generate the OOF predictions the corrector needs.
      ~6x the cost at the defaults; kept for validating "lofo" agrees with
      it (see `tests/test_models_evaluate.py`), not for routine use.

    `repeats > 1` reruns the whole grouped CV with a different seed each
    time (`StratifiedGroupKFold(shuffle=True, random_state=random_state +
    repeat)`, stratified on `stratify_bins` age deciles so the ~1% of
    subjects over 70 don't land disproportionately in one fold) — gives a
    leaderboard comparison something to compute a confidence interval from
    (see `bagpipe.models.compare.paired_bootstrap`) instead of a single
    deterministic split's point estimate.

    `sample_weighting` (`"none"` default, or `"inverse_age_density"`) is
    forwarded to `model.fit(X, y, sample_weight=...)` on the training fold's
    own ages (see `inverse_age_density_weights`) when not `"none"` — only
    meaningful for a `model_fn` whose `.fit()` accepts `sample_weight`
    (`TIVSexAdjustedRegressor` does; `SFCNRegressor` doesn't, so leave this
    `"none"` there). Not passed at all when `"none"`, so a model without
    `sample_weight` support is unaffected by this parameter existing.
    """
    if bias_correction_method not in ("lofo", "nested"):
        raise ValueError(f"unknown bias_correction_method {bias_correction_method!r}")
    if sample_weighting not in SAMPLE_WEIGHTING:
        raise ValueError(f"unknown sample_weighting {sample_weighting!r}")
    weight_fn = SAMPLE_WEIGHTING[sample_weighting]
    bias_corrector = bias_corrector or NoCorrection()
    correcting = not isinstance(bias_corrector, NoCorrection)
    y = np.asarray(y)
    groups = np.asarray(groups)
    X_arr = X.values if isinstance(X, pd.DataFrame) else np.asarray(X)
    strata = _make_strata(y, n_splits, stratify_bins)

    rows = []
    fold_slopes: list[float] = []
    for repeat_i in range(repeats):
        seed = random_state + repeat_i
        skf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
        fold_indices = list(skf.split(X_arr, strata, groups))

        fold_raw: list[np.ndarray] = []
        for train_idx, test_idx in fold_indices:
            model = model_fn(groups[train_idx])
            if weight_fn is not None:
                model.fit(X_arr[train_idx], y[train_idx], sample_weight=weight_fn(y[train_idx]))
            else:
                model.fit(X_arr[train_idx], y[train_idx])
            fold_raw.append(np.asarray(model.predict(X_arr[test_idx])))

        zipped = zip(fold_indices, fold_raw, strict=True)
        for fold_i, ((train_idx, test_idx), pred_test) in enumerate(zipped):
            if correcting:
                if bias_correction_method == "lofo":
                    other_true = np.concatenate(
                        [y[fold_indices[j][1]] for j in range(n_splits) if j != fold_i]
                    )
                    other_pred = np.concatenate(
                        [fold_raw[j] for j in range(n_splits) if j != fold_i]
                    )
                    bias_corrector.fit(other_true, other_pred)
                else:  # nested
                    train_groups = groups[train_idx]
                    inner_splits = min(bias_cv_splits, len(np.unique(train_groups)))
                    inner_strata = _make_strata(y[train_idx], inner_splits, stratify_bins)
                    inner_gkf = StratifiedGroupKFold(
                        n_splits=inner_splits, shuffle=True, random_state=seed
                    )
                    oof_pred = np.empty(len(train_idx))
                    for inner_train_rel, inner_val_rel in inner_gkf.split(
                        X_arr[train_idx], inner_strata, train_groups
                    ):
                        inner_model = model_fn(train_groups[inner_train_rel])
                        inner_y = y[train_idx][inner_train_rel]
                        inner_X = X_arr[train_idx][inner_train_rel]
                        if weight_fn is not None:
                            inner_model.fit(inner_X, inner_y, sample_weight=weight_fn(inner_y))
                        else:
                            inner_model.fit(inner_X, inner_y)
                        oof_pred[inner_val_rel] = inner_model.predict(
                            X_arr[train_idx][inner_val_rel]
                        )
                    bias_corrector.fit(y[train_idx], oof_pred)
                slope = getattr(bias_corrector, "slope_", None)
                if slope is not None:
                    fold_slopes.append(float(slope))

            pred_test_corrected = bias_corrector.transform(pred_test, y[test_idx])

            rows.append(
                pd.DataFrame(
                    {
                        "repeat": repeat_i,
                        "fold": fold_i,
                        "index": test_idx,
                        "y_true": y[test_idx],
                        "y_pred_raw": pred_test,
                        "y_pred_corrected": pred_test_corrected,
                    }
                )
            )

    predictions = pd.concat(rows, ignore_index=True)
    band_raw = mae_by_band(predictions["y_true"], predictions["y_pred_raw"])
    band_corrected = mae_by_band(predictions["y_true"], predictions["y_pred_corrected"])
    # mlflow-safe keys (no "<"/"+") for the metrics dict below — band_raw/
    # band_corrected above keep the human-readable form for other callers.
    band_raw_keys = mae_by_band(
        predictions["y_true"], predictions["y_pred_raw"], label_fn=_metric_key_band_label
    )
    band_corrected_keys = mae_by_band(
        predictions["y_true"], predictions["y_pred_corrected"], label_fn=_metric_key_band_label
    )
    y_sd = float(np.std(predictions["y_true"])) or 1.0
    mae_raw = mean_absolute_error(predictions["y_true"], predictions["y_pred_raw"])
    mae_corrected = mean_absolute_error(predictions["y_true"], predictions["y_pred_corrected"])
    metrics = {
        "mae_raw": mae_raw,
        "mae_corrected": mae_corrected,
        "r2_raw": r2_score(predictions["y_true"], predictions["y_pred_raw"]),
        "r2_corrected": r2_score(predictions["y_true"], predictions["y_pred_corrected"]),
        # mean of per-band MAE, not pooled MAE — so the old tail (a small
        # fraction of rows) counts as much as the dominant 18-40 band when
        # judging whether a change actually helped the uneven-error problem.
        "mae_balanced_raw": float(np.mean(list(band_raw.values()))),
        "mae_balanced_corrected": float(np.mean(list(band_corrected.values()))),
        "mae_over_sd_raw": mae_raw / y_sd,
    }
    if fold_slopes:
        metrics["cole_slope"] = float(np.mean(fold_slopes))
    for label, v in band_raw_keys.items():
        metrics[f"mae_raw_band_{label}"] = v
    for label, v in band_corrected_keys.items():
        metrics[f"mae_corrected_band_{label}"] = v
    return EvalResult(predictions=predictions, metrics=metrics)
