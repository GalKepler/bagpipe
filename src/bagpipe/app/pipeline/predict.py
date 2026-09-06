"""predict stage — docs/design_inference_pipeline.md § Stage specifications: predict.

Loads the production model + fits its Cole correction from its own stored
`predictions` rows (always in sync with the deployed artifact, no separate
corrector-persistence step — same approach as the old flat pipeline.py).

Chronological age here is self-reported by the uploader and never verified.
This stage deliberately never writes to the `predictions` table (that's
populated only by CV/promote runs against the verified SNBB cohort) — app
uploads must never enter the training set, since there is no way to confirm
the reported age is real.

Honest-accuracy note (2026-09): the production model's error is strongly
age-dependent — MAE roughly triples from the 18-30 band to the 70-90 band on
the model's own held-out `predictions` rows. `_band_mae` recomputes this
per age band from those same rows at request time (never hardcoded), so the
reported uncertainty always tracks whichever model is currently promoted.
"""

from __future__ import annotations

import json
from pathlib import Path

import cloudpickle
import numpy as np

from bagpipe.app.normative import fit_norms_cached, regional_zscores
from bagpipe.app.pipeline.base import ErrorCode, PipelineError, StageResult
from bagpipe.db.base import get_session
from bagpipe.db.models import ModelRegistry, Prediction
from bagpipe.models.bias_correction import ColeCorrection
from bagpipe.models.evaluate import AGE_BANDS
from bagpipe.models.evaluate import band_label as _band_label
from bagpipe.models.tabular import SEX_MAP, region_columns_for

# Below this many held-out subjects in a band, its MAE is too noisy to show
# on its own — fall back to the overall MAE instead (mirrors the n<10
# threshold bagpipe.app.normative.fit_norms already uses for the same
# small-sample-noise reason).
MIN_BAND_N = 10


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


def _load_model_predictions(model_id: int) -> list[Prediction]:
    """The production model's own held-out `predictions` rows — the single
    source both the Cole corrector and the per-age-band accuracy figures are
    computed from, so they can never disagree with each other."""
    with get_session() as session:
        rows = session.query(Prediction).filter_by(model_id=model_id).all()
    if not rows:
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED, f"no stored predictions for model_id={model_id}"
        )
    return rows


def _fit_cole_corrector(rows: list[Prediction]) -> ColeCorrection:
    y_true = np.array([r.age_true for r in rows])
    y_pred = np.array([r.predicted_age_raw for r in rows])
    return ColeCorrection().fit(y_true, y_pred)


def _training_support(rows: list[Prediction]) -> dict[str, float]:
    """Real age coverage of the training predictions, for user-facing text —
    never hardcode this, the training cohort changes as more subjects get
    reprocessed (see CLAUDE.md's CAT26 ledger notes)."""
    age = np.array([r.age_true for r in rows])
    return {
        "min": float(age.min()),
        "max": float(age.max()),
        "p5": float(np.percentile(age, 5)),
        "p95": float(np.percentile(age, 95)),
    }


def _band_mae(rows: list[Prediction], age: float) -> dict[str, float | int | str | bool]:
    """Per-age-band MAE (raw and corrected) computed from the production
    model's own held-out predictions, for the band `age` falls into. Falls
    back to the overall MAE (with `is_fallback=True`) when the matching band
    has too few subjects to trust, or — in principle, for a future model —
    is empty outright.
    """
    age_true = np.array([r.age_true for r in rows])
    raw_err = np.abs(np.array([r.predicted_age_raw for r in rows]) - age_true)
    corrected_err = np.abs(np.array([r.predicted_age_corrected for r in rows]) - age_true)

    overall = {
        "label": "overall",
        "n": len(rows),
        "mae_raw": float(raw_err.mean()),
        "mae_corrected": float(corrected_err.mean()),
        "is_fallback": True,
    }

    for lo, hi in AGE_BANDS:
        if lo <= age < hi:
            mask = (age_true >= lo) & (age_true < hi)
            n = int(mask.sum())
            if n < MIN_BAND_N:
                fallback = dict(overall)
                fallback["label"] = _band_label(lo, hi)
                return fallback
            return {
                "label": _band_label(lo, hi),
                "n": n,
                "mae_raw": float(raw_err[mask].mean()),
                "mae_corrected": float(corrected_err[mask].mean()),
                "is_fallback": False,
            }

    # Unreachable given AGE_BANDS' open tails, but never crash the report.
    return overall


class PredictStage:
    name = "predict"

    def __init__(self, model_name: str = "stacked", age_range: tuple[float, float] = (18.0, 90.0)):
        self.model_name = model_name
        self.age_range = age_range

    def run(self, workspace: Path, manifest) -> StageResult:
        features = json.loads((workspace / "features" / "features.json").read_text())
        sex = manifest.input.sex

        model, config, model_id = _load_production_model(self.model_name)
        feature_cfg = config.get("features", {})
        metrics_spec = feature_cfg.get("metrics", ["vol_gm"])
        atlases = feature_cfg.get("atlases")
        datasets_dir = Path(config["datasets_dir"]) if config.get("datasets_dir") else None
        region_columns = region_columns_for(
            metrics_spec, datasets_dir=datasets_dir, atlases=atlases
        )

        sex_code = SEX_MAP.get(sex)
        if sex_code is None:
            raise PipelineError(ErrorCode.MODEL_LOAD_FAILED, f"unrecognized sex value {sex!r}")
        tiv = features["TIV"]

        x = np.array([[features[c] for c in region_columns] + [tiv, sex_code]])

        # The artifact is a TIVSexAdjustedRegressor; its region_medians_
        # length is the ground truth for how many region columns it was
        # trained on. A silent mismatch here (stale atlas/metrics config,
        # a parquet schema drift) would otherwise just produce a plausible-
        # looking wrong number on a medical report — fail loudly instead.
        expected_len = model.region_medians_.size + 2  # + TIV + sex
        if x.shape[1] != expected_len:
            raise PipelineError(
                ErrorCode.FEATURE_SCHEMA_MISMATCH,
                f"feature vector has {x.shape[1]} columns, model expects {expected_len} "
                f"({model.region_medians_.size} region columns + TIV + sex) — "
                "atlas/metrics config drift between training and inference?",
            )

        raw = float(model.predict(x)[0])

        pred_rows = _load_model_predictions(model_id)
        corrector = _fit_cole_corrector(pred_rows)
        corrected = float(corrector.transform(np.array([raw]))[0])

        support = _training_support(pred_rows)
        age_out_of_range = not (self.age_range[0] <= corrected <= self.age_range[1])
        # Per product decision: the input-age gate lives at the API layer
        # (before the ~hour-long CAT12 run starts). Down here, after CAT12
        # has already finished, we report an out-of-range corrected age
        # rather than hard-failing the job — see CLAUDE.md task #3.
        warnings = []
        if age_out_of_range:
            warnings.append(
                f"Predicted age {corrected:.1f} falls outside this model's "
                f"{self.age_range[0]:.0f}-{self.age_range[1]:.0f} reporting range "
                f"(training data covers ages {support['min']:.1f}-{support['max']:.1f}, "
                f"with most subjects between {support['p5']:.1f} and {support['p95']:.1f})."
            )

        band = _band_mae(pred_rows, corrected)

        norms = fit_norms_cached(tuple(region_columns), datasets_dir)
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
                    "age_band": band,
                    "age_out_of_range": age_out_of_range,
                    "training_support": support,
                }
            )
        )

        return StageResult(
            outputs={"prediction": str(out_path.relative_to(workspace))},
            metrics={
                "predicted_age_raw": raw,
                "predicted_age_corrected": corrected,
                "n_regions_scored": len(zscores),
                "age_band_label": band["label"],
                "age_band_n": band["n"],
                "age_band_mae_corrected": band["mae_corrected"],
                "age_out_of_range": age_out_of_range,
            },
            warnings=warnings,
        )
