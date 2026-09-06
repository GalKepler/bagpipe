"""Config-driven per-region stacked ensemble: base learner per brain region,
meta-learner on OOF predictions (DESIGN.md §4.1). Reuses the same TIV/sex
adjustment, grouped-CV eval harness, and MLflow logging as `baseline.py`.
Entry point: `bag models train-stacked`.
"""

from __future__ import annotations

from pathlib import Path

import mlflow
import numpy as np
import yaml
from regional_stacker import RegionalStackingRegressor, default_alpha_grid
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge, RidgeCV
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures

from bagpipe.core.config import get_path
from bagpipe.models.bias_correction import get_corrector
from bagpipe.models.covariate_adjustment import TIVSexAdjustedRegressor
from bagpipe.models.evaluate import EvalResult, evaluate
from bagpipe.models.tabular import build_region_mapping, build_region_matrix

# ponytail: interaction terms are only sane per-region (few metrics/region);
# doing this for the meta-learner (hundreds of region predictions) would blow up
# combinatorially, so "ridge_interactions" is base-estimator-only by convention.
ESTIMATOR_TYPES = {
    "ridge": lambda params: Ridge(**params),
    "ridgecv": lambda params: RidgeCV(alphas=params.pop("alphas", default_alpha_grid()), **params),
    "hgbr": lambda params: HistGradientBoostingRegressor(**{"random_state": 0, **params}),
    "ridgecv_interactions": lambda params: make_pipeline(
        PolynomialFeatures(interaction_only=True, include_bias=False),
        RidgeCV(alphas=params.pop("alphas", default_alpha_grid()), **params),
    ),
}


def _build_estimator(spec: dict) -> object:
    spec = dict(spec)
    estimator_type = spec.pop("type")
    # dict(...) copy of "params" — ESTIMATOR_TYPES lambdas `.pop("alphas", ...)`
    # off it; without this copy that pop mutates the caller's config dict, and
    # since stacker_fn() is called fresh per CV fold, a config-set `alphas`
    # would apply on fold 0 only and silently vanish afterward.
    return ESTIMATOR_TYPES[estimator_type](dict(spec.pop("params", {})))


def _grouped_outer_cv(
    fold_groups: np.ndarray, n_splits: int
) -> list[tuple[np.ndarray, np.ndarray]]:
    """A materialized, subject-grouped split for `RegionalStackingRegressor`'s
    internal OOF stage.

    `RegionalStackingRegressor.outer_cv` goes through sklearn's `check_cv`,
    which — given a plain int — builds a non-grouped `KFold`. Since a
    subject's repeated sessions can land in the same `fold_groups` array
    passed in here (real for the SNBB cohort: ~330 subjects have >1
    session), that split would put one subject's sessions on both sides of
    the stacker's own internal train/val boundary, optimistically biasing
    the OOF predictions the meta-learner is fit on. `check_cv` accepts a
    precomputed iterable of `(train_idx, val_idx)` pairs as-is (wrapped in
    `_CVIterableWrapper`), so we build one with `GroupKFold` instead and
    pass that — same index space regardless of which region's `X` slice
    the stacker applies it to, so this only needs to be computed once per
    outer bagpipe fold, not once per region.
    """
    n_splits = min(n_splits, len(np.unique(fold_groups)))
    dummy_X = np.zeros((len(fold_groups), 1))
    return list(GroupKFold(n_splits=n_splits).split(dummy_X, groups=fold_groups))


def region_importance(fitted_model: TIVSexAdjustedRegressor) -> dict[str, float]:
    """Meta-learner coefficient magnitude per region, from a fitted stacked
    model (`TIVSexAdjustedRegressor` wrapping `RegionalStackingRegressor`).

    Complements `region_cv_scores_` (how well a region predicts age *on its
    own*) with which regions the meta-learner actually weights when
    combining them — a different, both-worth-having explainability view.
    Sorted descending by |coefficient|.
    """
    stacker = fitted_model.model_
    # meta_estimator_ is always a Pipeline (StandardScaler + estimator) —
    # coef_ lives on its last step.
    coefs = np.ravel(stacker.meta_estimator_[-1].coef_)
    importance = dict(zip(stacker.region_names_, np.abs(coefs), strict=True))
    return dict(sorted(importance.items(), key=lambda kv: kv[1], reverse=True))


def run(config_path: Path) -> tuple[EvalResult, dict]:
    config = yaml.safe_load(Path(config_path).read_text())
    stacker_cfg = config["stacker"]

    metrics = config.get("features", {}).get("metrics")  # None = all metrics per region
    atlases = config.get("features", {}).get("atlases")  # None = every atlas (see tabular.py)
    datasets_dir = (
        Path(config["datasets_dir"]) if config.get("datasets_dir") else get_path("datasets_dir")
    )
    X, y, groups, region_columns, session_ids = build_region_matrix(
        datasets_dir, metrics=metrics, atlases=atlases
    )
    region_mapping = build_region_mapping(region_columns)

    def stacker_fn(fold_groups: np.ndarray):
        outer_cv = _grouped_outer_cv(fold_groups, stacker_cfg.get("outer_cv", 5))
        return RegionalStackingRegressor(
            region_mapping=region_mapping,
            base_estimator=_build_estimator(stacker_cfg["base_estimator"]),
            meta_estimator=_build_estimator(stacker_cfg["meta_estimator"]),
            outer_cv=outer_cv,
            inner_cv=stacker_cfg.get("inner_cv", 3),
            n_jobs=stacker_cfg.get("n_jobs", -1),
            random_state=stacker_cfg.get("random_state", 0),
        )

    # fold_groups is the outer bagpipe CV fold's own training-subject array
    # (see evaluate.ModelFactory) — captured by the inner lambda so
    # TIVSexAdjustedRegressor's `base_model_fn()` (called with no args, at
    # `.fit()` time) still builds a stacker keyed to the right fold.
    model_fn = lambda fold_groups: TIVSexAdjustedRegressor(  # noqa: E731
        lambda: stacker_fn(fold_groups)
    )

    bias_corrector = get_corrector(config.get("bias_correction", "none"))
    n_splits = config.get("n_splits", 5)
    sample_weighting = config.get("sample_weighting", "none")

    result = evaluate(
        model_fn,
        X,
        y,
        groups,
        n_splits=n_splits,
        bias_corrector=bias_corrector,
        sample_weighting=sample_weighting,
    )

    mlflow_cfg = config.get("mlflow", {})
    mlflow_dir = get_path("mlflow_dir")
    mlflow_dir.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(f"sqlite:///{mlflow_dir / 'mlflow.db'}")
    mlflow.set_experiment(mlflow_cfg.get("experiment", "bagpipe-baseline"))
    run_name = mlflow_cfg.get("run_name") or "stacked"
    with mlflow.start_run(run_name=run_name) as mlflow_run:
        mlflow.log_params(
            {
                "model_type": "stacked",
                "bias_correction": config.get("bias_correction", "none"),
                "sample_weighting": sample_weighting,
                "n_splits": n_splits,
                "metrics": ",".join(metrics) if metrics else "all",
                "atlases": ",".join(atlases) if atlases else "all",
                "n_regions": len(region_mapping),
                "n_samples": len(y),
                "outer_cv": stacker_cfg.get("outer_cv", 5),
                "inner_cv": stacker_cfg.get("inner_cv", 3),
                "base_estimator": stacker_cfg["base_estimator"]["type"],
                "meta_estimator": stacker_cfg["meta_estimator"]["type"],
            }
        )
        mlflow.log_metrics(result.metrics)

    return result, {
        "region_columns": region_columns,
        "n_regions": len(region_mapping),
        "run_name": run_name,
        "mlflow_run_id": mlflow_run.info.run_id,
        "model_fn": model_fn,
        "config": config,
        "groups": groups,
        "session_ids": session_ids,
    }


if __name__ == "__main__":
    result, info = run(Path("config/models/stacked.yaml"))
    print(f"run: {info['run_name']} ({info['n_regions']} regions)")
    for k, v in result.metrics.items():
        print(f"  {k}: {v:.3f}")
