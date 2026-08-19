"""Promote a trained model to production: fit on full data, serialize, and
register in `models_registry` (DESIGN.md §3.2/§4.3). Only one model per
`name` holds stage="production" at a time — promoting demotes the rest.
"""

from __future__ import annotations

import json
from pathlib import Path

import cloudpickle

from bagpipe.core.config import get_path
from bagpipe.db.base import get_session, init_db
from bagpipe.db.models import ModelRegistry
from bagpipe.models.tabular import build_region_matrix

RUNNERS = {
    "stacked": "bagpipe.models.stacked",
}


def promote(model_name: str, config_path: Path, version: str, stage: str = "production") -> ModelRegistry:
    if model_name not in RUNNERS:
        raise ValueError(f"unknown model {model_name!r}, choose from {list(RUNNERS)}")

    import importlib

    runner = importlib.import_module(RUNNERS[model_name])
    result, info = runner.run(config_path)

    feature_cfg = info["config"].get("features", {})
    X, y, _groups, _region_columns = build_region_matrix(
        get_path("datasets_dir"), metrics=feature_cfg.get("metrics")
    )
    final_model = info["model_fn"]()
    final_model.fit(X, y)

    models_dir = get_path("models_dir")
    models_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = models_dir / f"{model_name}-{version}.pkl"
    with open(artifact_path, "wb") as f:
        cloudpickle.dump(final_model, f)

    init_db()
    with get_session() as session:
        if stage == "production":
            for existing in session.query(ModelRegistry).filter_by(name=model_name, stage="production"):
                existing.stage = "archived"
        entry = ModelRegistry(
            name=model_name,
            version=version,
            stage=stage,
            config_json=json.dumps(info["config"]),
            metrics_json=json.dumps(result.metrics),
            artifact_path=str(artifact_path),
            mlflow_run_id=info.get("mlflow_run_id"),
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return entry


if __name__ == "__main__":
    entry = promote("stacked", Path("config/models/stacked.yaml"), version="v1")
    print(f"promoted model_id={entry.model_id} {entry.name} {entry.version} -> {entry.stage}")
