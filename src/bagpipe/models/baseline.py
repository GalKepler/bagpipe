"""Config-driven tabular baseline: region-wise features, TIV/sex adjustment,
grouped CV, bias correction, MLflow logging. Entry point: `bag models train-baseline`.
"""

from __future__ import annotations

from pathlib import Path

import mlflow
import numpy as np
import yaml
from sklearn.linear_model import LinearRegression, RidgeCV

from bagpipe.core.config import get_path
from bagpipe.models.bias_correction import get_corrector
from bagpipe.models.covariate_adjustment import TIVSexAdjustedRegressor
from bagpipe.models.evaluate import EvalResult, evaluate
from bagpipe.models.tabular import build_region_matrix

MODEL_TYPES = {
    "linear": lambda params: LinearRegression(**params),
    "ridge": lambda params: _ridge(params),
    "lightgbm": lambda params: _lightgbm(params),
}


def _ridge(params: dict):
    # RidgeCV tunes alpha via internal CV at fit() time — no separate search
    # loop needed. `alphas` is config-overridable; defaults to a log grid.
    params = {"alphas": np.logspace(-3, 3, 13), **params}
    return RidgeCV(**params)


def _lightgbm(params: dict):
    from lightgbm import LGBMRegressor

    return LGBMRegressor(**params)


def run(config_path: Path) -> tuple[EvalResult, dict]:
    config = yaml.safe_load(Path(config_path).read_text())

    model_type = config["model"]["type"]
    model_params = config["model"].get("params") or {}
    base_model_fn = lambda: MODEL_TYPES[model_type](model_params)  # noqa: E731
    model_fn = lambda: TIVSexAdjustedRegressor(base_model_fn)  # noqa: E731

    metrics = config.get("features", {}).get("metrics", ["vol_gm"])
    atlases = config.get("features", {}).get("atlases")  # None = every atlas
    datasets_dir = (
        Path(config["datasets_dir"]) if config.get("datasets_dir") else get_path("datasets_dir")
    )
    X, y, groups, region_columns, _session_ids = build_region_matrix(
        datasets_dir, metrics=metrics, atlases=atlases
    )
    bias_corrector = get_corrector(config.get("bias_correction", "none"))
    n_splits = config.get("n_splits", 5)

    result = evaluate(model_fn, X, y, groups, n_splits=n_splits, bias_corrector=bias_corrector)

    mlflow_cfg = config.get("mlflow", {})
    mlflow_dir = get_path("mlflow_dir")
    mlflow_dir.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(f"sqlite:///{mlflow_dir / 'mlflow.db'}")
    mlflow.set_experiment(mlflow_cfg.get("experiment", "bagpipe-baseline"))
    run_name = mlflow_cfg.get("run_name") or f"{model_type}-{config.get('bias_correction', 'none')}"
    with mlflow.start_run(run_name=run_name):
        mlflow.log_params(
            {
                "model_type": model_type,
                "bias_correction": config.get("bias_correction", "none"),
                "n_splits": n_splits,
                "metrics": ",".join(metrics),
                "n_regions": len(region_columns),
                "n_samples": len(y),
                **{f"model__{k}": v for k, v in model_params.items()},
            }
        )
        mlflow.log_metrics(result.metrics)

    return result, {"region_columns": region_columns, "run_name": run_name}


if __name__ == "__main__":
    result, info = run(Path("config/models/baseline.yaml"))
    print(f"run: {info['run_name']} ({len(info['region_columns'])} regions)")
    for k, v in result.metrics.items():
        print(f"  {k}: {v:.3f}")
