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

The same rows also produce the cohort-context figures the report plots the
reader against (`_population_context`). Those are deliberately aggregate —
histogram counts, per-age-bin percentiles over >= MIN_BAND_N subjects — since
the reference cohort is real SNBB data and this payload is served to a public
browser.
"""

from __future__ import annotations

import json
from pathlib import Path

import cloudpickle
import numpy as np

from bagpipe.app import region_names
from bagpipe.app.normative import fit_norms_cached, regional_zscores
from bagpipe.app.pipeline.base import ErrorCode, PipelineError, StageResult
from bagpipe.db.base import get_session
from bagpipe.db.models import ModelRegistry, Prediction
from bagpipe.models.bias_correction import ColeCorrection
from bagpipe.models.covariate_adjustment import _fillna
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


# Cohort-context figures (`bagpipe.app.charts`) are computed here, from the
# same held-out `predictions` rows as the corrector and the band MAE, and
# they are AGGREGATE ONLY — histogram counts and per-bin percentiles, never
# per-subject rows. The reference cohort is real SNBB data and this payload
# is served to a public browser, so nothing that resolves to an individual
# (an age paired with a prediction, a subject count of one) may enter it.
# See CLAUDE.md's hard constraints.
BAG_HIST_BINS = 28
CALIBRATION_BIN_YEARS = 5.0


def _cohort_bag(rows: list[Prediction]) -> np.ndarray:
    """The cohort's own corrected brain age gaps — the distribution a
    reader's number is only interpretable against."""
    return np.array([r.predicted_age_corrected - r.age_true for r in rows])


def _pool_sparse_bins(edges: list[float], counts: list[int]) -> tuple[list[float], list[int]]:
    """Merge any bin holding between 1 and `MIN_BAND_N - 1` subjects into a
    neighbour, until every published bin is either empty or holds at least
    `MIN_BAND_N`.

    Without this, a tail bin containing a single held-out subject publishes
    exactly what the aggregate-only contract forbids: that one person's brain
    age gap, localised to that bin's width. Merging rather than zeroing keeps
    the distribution honest — the subjects stay in the total, the bin just
    gets wide enough to stop describing an individual. (Empty bins are left
    alone; a count of zero discloses nothing.)
    """
    edges, counts = list(edges), list(counts)
    while len(counts) > 1:
        sparse = [i for i, c in enumerate(counts) if 0 < c < MIN_BAND_N]
        if not sparse:
            break
        i = min(sparse, key=lambda i: counts[i])
        # Merge into whichever neighbour is itself smaller, so pooling grows
        # the thin tails instead of eating into the dense middle.
        if i == 0:
            j = 1
        elif i == len(counts) - 1:
            j = i - 1
        else:
            j = i - 1 if counts[i - 1] <= counts[i + 1] else i + 1
        lo, hi = min(i, j), max(i, j)
        counts[lo] = counts[lo] + counts[hi]
        del counts[hi]
        del edges[hi]  # drop the edge between the two merged bins
    return edges, counts


def _bag_histogram(bag: np.ndarray) -> dict:
    """Distribution of the cohort's gaps over a robust range (99th percentile
    of |gap|, symmetric about zero) so one extreme validation subject can't
    squash the shape the reader is being placed in, with sparse bins pooled
    (`_pool_sparse_bins`) so no bin describes an individual.

    Bins are therefore NOT uniform-width after pooling — `charts.bag_distribution`
    draws density (count / bin width), not raw count.
    """
    limit = float(max(np.percentile(np.abs(bag), 99), 1.0))
    edges = np.linspace(-limit, limit, BAG_HIST_BINS + 1)
    counts, _ = np.histogram(np.clip(bag, edges[0], edges[-1]), bins=edges)

    pooled_edges, pooled_counts = _pool_sparse_bins(
        [float(e) for e in edges], [int(c) for c in counts]
    )
    # A cohort too small to fill even one bin has no publishable distribution.
    if not any(c >= MIN_BAND_N for c in pooled_counts):
        return {"edges": [], "counts": []}
    return {
        "edges": [round(e, 3) for e in pooled_edges],
        "counts": pooled_counts,
    }


def _calibration_bands(rows: list[Prediction]) -> list[dict]:
    """Per age bin: how the cohort's predictions are actually distributed.

    Bins with fewer than `MIN_BAND_N` subjects are dropped rather than
    plotted — both because a decile from n<10 is noise, and because a
    thinly-populated bin's percentiles start to describe individuals.
    """
    age_true = np.array([r.age_true for r in rows])
    predicted = np.array([r.predicted_age_corrected for r in rows])
    lo = float(np.floor(age_true.min() / CALIBRATION_BIN_YEARS) * CALIBRATION_BIN_YEARS)
    hi = float(np.ceil(age_true.max() / CALIBRATION_BIN_YEARS) * CALIBRATION_BIN_YEARS)

    bands = []
    edge = lo
    while edge < hi:
        mask = (age_true >= edge) & (age_true < edge + CALIBRATION_BIN_YEARS)
        n = int(mask.sum())
        if n >= MIN_BAND_N:
            values = predicted[mask]
            bands.append(
                {
                    "age_lo": edge,
                    "age_hi": edge + CALIBRATION_BIN_YEARS,
                    "n": n,
                    "median": float(np.median(values)),
                    "p10": float(np.percentile(values, 10)),
                    "p90": float(np.percentile(values, 90)),
                }
            )
        edge += CALIBRATION_BIN_YEARS
    return bands


def _regional_bag(model, x: np.ndarray, chronological_age: float | None) -> dict[str, dict]:
    """Per-region brain age gap — what age each region's OWN base learner
    predicts (Cole-corrected with its own corrector, fit at promotion time —
    `bagpipe.models.bias_correction.fit_region_correctors`), not the
    normative z-score `regional_zscores` already reports. Same
    preprocessing `TIVSexAdjustedRegressor.predict`/`fit_region_correctors`
    use (median-impute, then TIV/sex-adjust), reused here rather than
    re-derived — see `notebooks/bag_correlates_explorer.ipynb`, the existing
    consumer of `region_correctors_`.

    Region keys are normalized to match `regional_zscores`' `label` (atlas
    prefix stripped) so the UI can join the two by the same key. The
    production model's own `region_names_` are atlas-qualified
    ("Schaefer2018N400n7Tian2020S2__LH_Cont_Cing_1", baked in at training
    time by whatever `bagpipe.models.tabular.build_region_mapping` did on
    that run) rather than bare labels — verified against the real
    production artifact, 2026-09-07 — so this strips the same
    `region_names.ATLAS_PREFIX` the rest of the report already hardcodes to
    this one cortical+subcortical atlas.
    """
    stacker = model.model_
    if not hasattr(stacker, "region_correctors_"):
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "production model has no per-region Cole correctors "
            "(bagpipe.models.bias_correction.fit_region_correctors) — re-promote to enable "
            "regional BAG.",
        )

    region_x, tiv, sex = x[:, :-2], x[:, -2], x[:, -1]
    residuals = model.adjuster_.transform(_fillna(region_x, model.region_medians_), tiv, sex)
    atlas_prefix = f"{region_names.ATLAS_PREFIX}__"

    regional: dict[str, dict] = {}
    for rname in stacker.region_names_:
        raw_age = float(
            stacker.region_estimators_[rname].predict(residuals[:, stacker.region_columns_[rname]])[
                0
            ]
        )
        corrected_age = float(stacker.region_correctors_[rname].transform(np.array([raw_age]))[0])
        label = rname.removeprefix(atlas_prefix)
        regional[label] = {
            "predicted_age_raw": raw_age,
            "predicted_age_corrected": corrected_age,
            "bag_corrected": corrected_age - (chronological_age or corrected_age),
        }
    return regional


def _population_context(rows: list[Prediction], user_bag: float | None) -> dict:
    """Everything the report needs to say "and here is where that sits"."""
    bag = _cohort_bag(rows)
    percentile = None
    if user_bag is not None:
        percentile = float((bag < user_bag).mean() * 100.0)
    return {
        "n": len(rows),
        "bag_mean": float(bag.mean()),
        "bag_sd": float(bag.std(ddof=1)),
        "bag_percentile": percentile,
        "bag_histogram": _bag_histogram(bag),
        "calibration": _calibration_bands(rows),
    }


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

        chronological_age = manifest.input.chronological_age
        bag_corrected = corrected - (chronological_age or corrected)
        regional_bag = _regional_bag(model, x, chronological_age)
        population = _population_context(
            pred_rows, bag_corrected if chronological_age is not None else None
        )

        out_dir = workspace / "predict"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / "prediction.json"
        out_path.write_text(
            json.dumps(
                {
                    "predicted_age": corrected,
                    "bag_raw": raw - (chronological_age or raw),
                    "bag_corrected": bag_corrected,
                    "predicted_age_raw": raw,
                    "chronological_age": chronological_age,
                    "sex": sex,
                    "regional_zscores": zscores,
                    "regional_bag": regional_bag,
                    "age_band": band,
                    "age_out_of_range": age_out_of_range,
                    "training_support": support,
                    "population": population,
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
                "bag_percentile": population["bag_percentile"],
            },
            warnings=warnings,
        )
