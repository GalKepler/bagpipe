"""Config-driven per-region stacked ensemble: base learner per brain region,
meta-learner on OOF predictions (DESIGN.md §4.1). Reuses the same TIV/sex
adjustment, grouped-CV eval harness, and MLflow logging as `baseline.py`.
Entry point: `bag models train-stacked`.
"""

from __future__ import annotations

from pathlib import Path

import mlflow
import yaml
from regional_stacker import RegionalStackingRegressor, default_alpha_grid
from sklearn.linear_model import Ridge, RidgeCV

from bagpipe.core.config import get_path
from bagpipe.models.bias_correction import get_corrector
from bagpipe.models.covariate_adjustment import TIVSexAdjustedRegressor
from bagpipe.models.evaluate import EvalResult, evaluate
from bagpipe.models.tabular import build_region_mapping, build_region_matrix

ESTIMATOR_TYPES = {
    "ridge": lambda params: Ridge(**params),
    "ridgecv": lambda params: RidgeCV(alphas=params.pop("alphas", default_alpha_grid()), **params),
}


def _build_estimator(spec: dict) -> object:
    spec = dict(spec)
    estimator_type = spec.pop("type")
    return ESTIMATOR_TYPES[estimator_type](spec.pop("params", {}))


def run(config_path: Path) -> tuple[EvalResult, dict]:
    config = yaml.safe_load(Path(config_path).read_text())
    stacker_cfg = config["stacker"]

    metrics = config.get("features", {}).get("metrics")  # None = all metrics per region
    X, y, groups, region_columns = build_region_matrix(get_path("datasets_dir"), metrics=metrics)
    region_mapping = build_region_mapping(region_columns)

    def stacker_fn():
        return RegionalStackingRegressor(
            region_mapping=region_mapping,
            base_estimator=_build_estimator(stacker_cfg["base_estimator"]),
            meta_estimator=_build_estimator(stacker_cfg["meta_estimator"]),
            outer_cv=stacker_cfg.get("outer_cv", 5),
            inner_cv=stacker_cfg.get("inner_cv", 3),
            n_jobs=stacker_cfg.get("n_jobs", -1),
            random_state=stacker_cfg.get("random_state", 0),
        )

    model_fn = lambda: TIVSexAdjustedRegressor(stacker_fn)  # noqa: E731

    bias_corrector = get_corrector(config.get("bias_correction", "none"))
    n_splits = config.get("n_splits", 5)

    result = evaluate(model_fn, X, y, groups, n_splits=n_splits, bias_corrector=bias_corrector)

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
                "n_splits": n_splits,
                "metrics": ",".join(metrics) if metrics else "all",
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
    }


if __name__ == "__main__":
    result, info = run(Path("config/models/stacked.yaml"))
    print(f"run: {info['run_name']} ({info['n_regions']} regions)")
    for k, v in result.metrics.items():
        print(f"  {k}: {v:.3f}")
