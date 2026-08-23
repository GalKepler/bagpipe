"""predict stage — docs/design_inference_pipeline.md § Stage specifications: predict.

Loads the production model + fits its Cole correction from its own stored
`predictions` rows (always in sync with the deployed artifact, no separate
corrector-persistence step — same approach as the old flat pipeline.py).
"""

from __future__ import annotations

import json
from pathlib import Path

import cloudpickle
import numpy as np

from bagpipe.app.normative import fit_norms, regional_zscores
from bagpipe.app.pipeline.base import ErrorCode, PipelineError, StageResult
from bagpipe.db.base import get_session
from bagpipe.db.models import ModelRegistry, Prediction
from bagpipe.models.bias_correction import ColeCorrection
from bagpipe.models.tabular import SEX_MAP, region_columns_for


def _load_production_model(name: str) -> tuple[object, dict, int]:
    with get_session() as session:
        row = (
            session.query(ModelRegistry)
            .filter_by(name=name, stage="production")
            .order_by(ModelRegistry.trained_at.desc())
            .first()
        )
        if row is None:
            raise PipelineError(
                ErrorCode.MODEL_LOAD_FAILED, f"no production model registered for name={name!r}"
            )
        with open(row.artifact_path, "rb") as f:
            model = cloudpickle.load(f)
        config = json.loads(row.config_json)
        model_id = row.model_id
    return model, config, model_id


def _fit_cole_corrector(model_id: int) -> ColeCorrection:
    with get_session() as session:
        rows = session.query(Prediction).filter_by(model_id=model_id).all()
    if not rows:
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED, f"no stored predictions for model_id={model_id}"
        )
    y_true = np.array([r.age_true for r in rows])
    y_pred = np.array([r.predicted_age_raw for r in rows])
    return ColeCorrection().fit(y_true, y_pred)


class PredictStage:
    name = "predict"

    def __init__(self, model_name: str = "stacked", age_range: tuple[float, float] = (18.0, 90.0)):
        self.model_name = model_name
        self.age_range = age_range

    def run(self, workspace: Path, manifest) -> StageResult:
        features = json.loads((workspace / "features" / "features.json").read_text())
        sex = manifest.input.sex

        model, config, model_id = _load_production_model(self.model_name)
        metrics_spec = config.get("features", {}).get("metrics", ["vol_gm"])
        region_columns = region_columns_for(metrics_spec)

        sex_code = SEX_MAP.get(sex)
        if sex_code is None:
            raise PipelineError(ErrorCode.MODEL_LOAD_FAILED, f"unrecognized sex value {sex!r}")
        tiv = features["TIV"]

        x = np.array([[features[c] for c in region_columns] + [tiv, sex_code]])
        raw = float(model.predict(x)[0])

        corrector = _fit_cole_corrector(model_id)
        corrected = float(corrector.transform(np.array([raw]))[0])

        if not (self.age_range[0] <= corrected <= self.age_range[1]):
            raise PipelineError(
                ErrorCode.AGE_OUT_OF_RANGE,
                f"predicted age {corrected:.1f} outside training support {self.age_range}",
                user_message="Your predicted age falls outside the model's reliable range.",
            )

        norms = fit_norms(region_columns)
        zscores = regional_zscores(features, norms, age=corrected, sex=sex_code, tiv=tiv)

        out_dir = workspace / "predict"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / "prediction.json"
        out_path.write_text(
            json.dumps(
                {
                    "predicted_age": corrected,
                    "bag_raw": raw - (manifest.input.chronological_age or raw),
                    "bag_corrected": corrected - (manifest.input.chronological_age or corrected),
                    "predicted_age_raw": raw,
                    "regional_zscores": zscores,
                }
            )
        )

        return StageResult(
            outputs={"prediction": str(out_path.relative_to(workspace))},
            metrics={
                "predicted_age_raw": raw,
                "predicted_age_corrected": corrected,
                "n_regions_scored": len(zscores),
            },
        )
