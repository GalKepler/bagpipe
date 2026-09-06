"""Promote a trained model to production: fit on full data, serialize, and
register in `models_registry` (DESIGN.md §3.2/§4.3). Only one model per
`name` holds stage="production" at a time — promoting demotes the rest.
"""

from __future__ import annotations

import json
from pathlib import Path

import cloudpickle
import numpy as np
import pandas as pd

from bagpipe.core.config import get_path
from bagpipe.db.base import get_session, init_db
from bagpipe.db.models import ModelRegistry, Prediction
from bagpipe.models.bias_correction import fit_region_correctors
from bagpipe.models.compare import paired_bootstrap
from bagpipe.models.evaluate import EvalResult
from bagpipe.models.tabular import build_region_matrix

RUNNERS = {
    "stacked": "bagpipe.models.stacked",
}


class PromotionRejected(RuntimeError):
    """A challenger's `mae_corrected` isn't confidently better than the
    current production model's — see `promote(..., force=True)` to override."""


def _incumbent_eval_result(model_name: str) -> tuple[EvalResult, np.ndarray] | None:
    """The current production model's own stored `predictions` rows,
    reshaped into the same `(EvalResult, groups)` shape `paired_bootstrap`
    expects — so a challenger compares against real held-out numbers, not a
    re-run. Returns `None` if there is no production model yet (first
    promotion ever) or somehow no stored predictions for it."""
    with get_session() as session:
        incumbent = (
            session.query(ModelRegistry)
            .filter_by(name=model_name, stage="production")
            .order_by(ModelRegistry.trained_at.desc())
            .first()
        )
        if incumbent is None:
            return None
        rows = session.query(Prediction).filter_by(model_id=incumbent.model_id).all()
    if not rows:
        return None
    predictions = pd.DataFrame(
        {
            "repeat": 0,
            "fold": [r.fold for r in rows],
            "index": range(len(rows)),
            "y_true": [r.age_true for r in rows],
            "y_pred_raw": [r.predicted_age_raw for r in rows],
            "y_pred_corrected": [r.predicted_age_corrected for r in rows],
        }
    )
    groups = np.array([r.subject_key for r in rows])
    return EvalResult(predictions=predictions, metrics={}), groups


def _check_promotable(
    result: EvalResult,
    groups: np.ndarray,
    incumbent: tuple[EvalResult, np.ndarray] | None,
    metric: str = "mae_corrected",
) -> tuple[float, float, float] | None:
    """Pure decision logic (no DB access) — `promote()`'s thin wrapper around
    this does the DB lookups and raises `PromotionRejected`. Returns `None`
    when there's nothing to compare against (first-ever promotion). Returns
    `(delta, lo, hi)` from `paired_bootstrap` otherwise; caller decides what
    to do with it — kept separate so it's unit-testable without a DB.
    """
    if incumbent is None:
        return None
    result_b, groups_b = incumbent
    return paired_bootstrap(result, result_b, groups, groups_b, metric=metric)


def _persist_predictions(model_id: int, result, groups, session_ids) -> None:
    """Store each fold's held-out (subject never seen in that fold's
    training) predictions as this model's BAG values — real out-of-sample
    numbers, not predictions from the full-data refit used for the artifact.
    """
    rows = result.predictions
    with get_session() as session:
        session.query(Prediction).filter_by(model_id=model_id).delete()
        for row in rows.itertuples():
            idx = row.index
            session.add(
                Prediction(
                    model_id=model_id,
                    subject_key=str(groups[idx]),
                    session_id=str(session_ids[idx]),
                    fold=int(row.fold),
                    age_true=float(row.y_true),
                    predicted_age_raw=float(row.y_pred_raw),
                    predicted_age_corrected=float(row.y_pred_corrected),
                    bag_raw=float(row.y_pred_raw - row.y_true),
                    bag_corrected=float(row.y_pred_corrected - row.y_true),
                )
            )
        session.commit()


def promote(
    model_name: str,
    config_path: Path,
    version: str,
    stage: str = "production",
    force: bool = False,
) -> ModelRegistry:
    if model_name not in RUNNERS:
        raise ValueError(f"unknown model {model_name!r}, choose from {list(RUNNERS)}")

    import importlib

    runner = importlib.import_module(RUNNERS[model_name])
    result, info = runner.run(config_path)

    if stage == "production" and not force:
        comparison = _check_promotable(result, info["groups"], _incumbent_eval_result(model_name))
        if comparison is not None:
            delta, lo, hi = comparison
            # delta = challenger - incumbent MAE; delta<0 means the
            # challenger is better. Refuse unless the CI confidently shows
            # that (hi < 0) — "includes 0" (no confident difference) and
            # "clearly worse" both refuse, same escape hatch either way.
            if hi >= 0:
                raise PromotionRejected(
                    f"challenger mae_corrected - incumbent = {delta:+.3f}y "
                    f"[{lo:+.3f}, {hi:+.3f}] — CI doesn't confidently exclude "
                    "0/positive (challenger not shown better). Re-run with "
                    "force=True to promote anyway."
                )
            print(f"challenger beats incumbent by {-delta:.3f}y [{-hi:.3f}, {-lo:.3f}], promoting")

    config = info["config"]
    feature_cfg = config.get("features", {})
    datasets_dir = (
        Path(config["datasets_dir"]) if config.get("datasets_dir") else get_path("datasets_dir")
    )
    X, y, groups, _region_columns, _session_ids = build_region_matrix(
        datasets_dir, metrics=feature_cfg.get("metrics"), atlases=feature_cfg.get("atlases")
    )
    final_model = info["model_fn"](groups)
    final_model.fit(X, y)
    fit_region_correctors(final_model, X, y)  # per-region Cole correction, stored on the artifact

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
        model_id = entry.model_id

    _persist_predictions(model_id, result, info["groups"], info["session_ids"])

    with get_session() as session:
        return session.get(ModelRegistry, model_id)


if __name__ == "__main__":
    entry = promote("stacked", Path("config/models/stacked.yaml"), version="v1")
    print(f"promoted model_id={entry.model_id} {entry.name} {entry.version} -> {entry.stage}")
