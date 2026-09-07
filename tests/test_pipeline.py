"""predict stage against a stubbed model/DB — no real DB, no apptainer,
no CAT12. Exercises vectorization, missing-column and unknown-sex errors,
bias correction + regional z-scoring wiring, per-age-band accuracy
reporting, the feature-vector shape assertion, out-of-range reporting
(not raising), and the normative-fit cache.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pytest

from bagpipe.app.normative import RegionNorm
from bagpipe.app.pipeline import predict
from bagpipe.app.pipeline.base import PipelineError
from bagpipe.app.pipeline.models import Environment, JobInput, Manifest


class _StubModel:
    region_medians_ = np.zeros(2)  # 2 region columns, matches REGION_COLUMNS

    def predict(self, x):
        return np.array([50.0 + x[0, 0]])  # deterministic, depends on first region col


REGION_COLUMNS = ["atlas__R1__vol_gm", "atlas__R2__vol_gm"]


def _manifest(sex: str = "F", age: float | None = None) -> Manifest:
    return Manifest(
        job_id="test",
        created_at=datetime.now(UTC),
        input=JobInput(
            upload_format="nifti",
            upload_sha256="x",
            upload_size_bytes=1,
            sex=sex,
            chronological_age=age,
        ),
        environment=Environment(bagpipe_version="0", model_id="stacked", feature_schema_id="test"),
    )


def _pred_row(age_true, raw, corrected):
    return SimpleNamespace(
        age_true=age_true, predicted_age_raw=raw, predicted_age_corrected=corrected
    )


# 12 rows with ages 20-31 (10 of them, ages 20-29, land in the [.., 30) band
# — >= MIN_BAND_N=10 — with a known MAE), plus 2 rows in the 70-90 band
# (< MIN_BAND_N) to exercise the small-band fallback.
_PRED_ROWS = [_pred_row(20.0 + i, 20.0 + i + 2.0, 20.0 + i + 1.0) for i in range(12)] + [
    _pred_row(75.0, 80.0, 79.0),
    _pred_row(78.0, 84.0, 83.0),
]


@pytest.fixture(autouse=True)
def _stub_dependencies(monkeypatch):
    monkeypatch.setattr(
        predict,
        "_load_production_model",
        lambda name: (_StubModel(), {"features": {"metrics": ["vol_gm"]}}, 1),
    )
    monkeypatch.setattr(predict, "region_columns_for", lambda metrics, **kw: REGION_COLUMNS)
    monkeypatch.setattr(predict, "_load_model_predictions", lambda model_id: _PRED_ROWS)

    class _IdentityCorrector:
        def transform(self, y_pred):
            return y_pred + 1.0  # arbitrary, distinguishable from raw

    monkeypatch.setattr(predict, "_fit_cole_corrector", lambda rows: _IdentityCorrector())
    monkeypatch.setattr(
        predict,
        "fit_norms_cached",
        lambda region_columns, datasets_dir=None: {
            c: RegionNorm(coefs=np.zeros(4), resid_std=1.0) for c in region_columns
        },
    )


def test_predict_stage_happy_path(tmp_path):
    (tmp_path / "features").mkdir()
    (tmp_path / "features" / "features.json").write_text(
        '{"atlas__R1__vol_gm": 3.0, "atlas__R2__vol_gm": 4.0, "TIV": 1500.0}'
    )

    stage = predict.PredictStage()
    result = stage.run(tmp_path, _manifest())

    assert result.metrics["predicted_age_raw"] == pytest.approx(53.0)  # 50 + region1(3.0)
    assert result.metrics["predicted_age_corrected"] == pytest.approx(
        54.0
    )  # +1 from stub corrector
    assert result.metrics["n_regions_scored"] == 2
    assert (tmp_path / "predict" / "prediction.json").exists()
    # corrected age 54.0 falls in the 50-60 band, which has 0 rows in
    # _PRED_ROWS (< MIN_BAND_N) — must fall back to the overall MAE, not
    # crash or report a meaningless 0/0 band.
    assert result.metrics["age_band_label"] == "50-60"
    assert result.metrics["age_band_n"] == len(_PRED_ROWS)
    assert result.metrics["age_band_mae_corrected"] == pytest.approx(1.5)
    assert result.metrics["age_out_of_range"] is False


def test_predict_stage_band_uses_matching_band_when_n_sufficient(tmp_path):
    (tmp_path / "features").mkdir()
    # raw = 50 + (-26) = 24.0, corrected (stub +1) = 25.0 -> comfortably
    # inside the well-populated 18-30 band (12 synthetic rows in _PRED_ROWS).
    (tmp_path / "features" / "features.json").write_text(
        '{"atlas__R1__vol_gm": -26.0, "atlas__R2__vol_gm": 4.0, "TIV": 1500.0}'
    )

    stage = predict.PredictStage()
    result = stage.run(tmp_path, _manifest())

    assert result.metrics["age_band_label"] == "<18-30"
    # _PRED_ROWS has ages 20-31; only 20-29 (10 rows) fall in the [.., 30)
    # band — the age==30/31 rows belong to the next band.
    assert result.metrics["age_band_n"] == 10
    assert result.metrics["age_band_mae_corrected"] == pytest.approx(1.0)


def test_predict_stage_shape_mismatch_raises_feature_schema_mismatch(tmp_path, monkeypatch):
    (tmp_path / "features").mkdir()
    (tmp_path / "features" / "features.json").write_text(
        '{"atlas__R1__vol_gm": 3.0, "atlas__R2__vol_gm": 4.0, "TIV": 1500.0}'
    )
    # Model expects 1 region column + TIV + sex = 3, but region_columns_for
    # (stubbed) still yields 2 region columns -> vector length 4 != 3.
    bad_model = _StubModel()
    bad_model.region_medians_ = np.zeros(1)
    monkeypatch.setattr(
        predict,
        "_load_production_model",
        lambda name: (bad_model, {"features": {"metrics": ["vol_gm"]}}, 1),
    )

    stage = predict.PredictStage()
    with pytest.raises(PipelineError) as excinfo:
        stage.run(tmp_path, _manifest())
    assert excinfo.value.code.value == "feature_schema_mismatch"


def test_predict_stage_out_of_range_reports_not_raises(tmp_path):
    (tmp_path / "features").mkdir()
    # first region col very large -> raw and corrected age far above 90 ->
    # must be *reported*, not raised, since the input-age gate lives at the
    # API layer (before the CAT12 run), not here (after it).
    (tmp_path / "features" / "features.json").write_text(
        '{"atlas__R1__vol_gm": 100.0, "atlas__R2__vol_gm": 4.0, "TIV": 1500.0}'
    )

    stage = predict.PredictStage()
    result = stage.run(tmp_path, _manifest())  # must not raise

    assert result.metrics["predicted_age_corrected"] > 90.0
    assert result.metrics["age_out_of_range"] is True
    assert result.warnings and "outside" in result.warnings[0]

    saved = json.loads((tmp_path / "predict" / "prediction.json").read_text())
    assert saved["age_out_of_range"] is True
    assert "training_support" in saved


def test_predict_stage_missing_region_raises(tmp_path):
    (tmp_path / "features").mkdir()
    (tmp_path / "features" / "features.json").write_text(
        '{"atlas__R1__vol_gm": 3.0, "TIV": 1500.0}'
    )  # R2 missing

    stage = predict.PredictStage()
    with pytest.raises(
        KeyError
    ):  # region_columns_for stub still returns R2; features dict lacks it
        stage.run(tmp_path, _manifest())


def test_predict_stage_unknown_sex_raises(tmp_path):
    (tmp_path / "features").mkdir()
    (tmp_path / "features" / "features.json").write_text(
        '{"atlas__R1__vol_gm": 3.0, "atlas__R2__vol_gm": 4.0, "TIV": 1500.0}'
    )

    stage = predict.PredictStage()
    with pytest.raises(PipelineError, match="unrecognized sex"):
        stage.run(tmp_path, _manifest(sex="nonbinary-not-in-map"))


def test_fit_norms_cached_hits_cache_on_repeat_call(monkeypatch):
    """bagpipe.app.normative.fit_norms_cached — real lru_cache, not stubbed.
    predict.py calls this once per job; a long-lived worker process must not
    redo ~1300 OLS fits on every job for the same production model."""
    from bagpipe.app import normative

    normative.fit_norms_cached.cache_clear()
    calls = {"n": 0}

    def _fake_fit_norms(region_columns, datasets_dir=None):
        calls["n"] += 1
        return {c: RegionNorm(coefs=np.zeros(4), resid_std=1.0) for c in region_columns}

    # Bypass the real parquet read entirely — only cache behavior is under
    # test here, not fit_norms' own regression logic (covered elsewhere).
    monkeypatch.setattr(normative, "fit_norms", _fake_fit_norms)

    cols = ("atlas__R1__vol_gm", "atlas__R2__vol_gm")
    first = normative.fit_norms_cached(cols, None)
    second = normative.fit_norms_cached(cols, None)

    assert calls["n"] == 1  # second call served from cache, not recomputed
    assert first == second
    normative.fit_norms_cached.cache_clear()


# --------------------------------------------------------------------------
# Cohort-context block (`_population_context`) — the aggregate figures the
# report plots the reader against. The privacy contract matters as much as
# the arithmetic: this payload is served to a public browser, so it must
# never carry a per-subject row (CLAUDE.md hard constraints).
# --------------------------------------------------------------------------
def test_population_context_is_aggregate_only():
    context = predict._population_context(_PRED_ROWS, 1.0)
    assert set(context) == {
        "n",
        "bag_mean",
        "bag_sd",
        "bag_percentile",
        "bag_histogram",
        "calibration",
    }
    assert set(context["bag_histogram"]) == {"edges", "counts"}
    assert all(isinstance(c, int) for c in context["bag_histogram"]["counts"])
    for band in context["calibration"]:
        assert set(band) == {"age_lo", "age_hi", "n", "median", "p10", "p90"}


def test_population_context_percentile_places_the_reader():
    # _PRED_ROWS' corrected gaps are 1.0 (the twelve 20s rows) plus 4.0 and
    # 5.0 (the two 70s rows), so a reader above all of them is at 100.
    assert predict._population_context(_PRED_ROWS, 9.0)["bag_percentile"] == pytest.approx(100.0)
    assert predict._population_context(_PRED_ROWS, -5.0)["bag_percentile"] == pytest.approx(0.0)
    assert predict._population_context(_PRED_ROWS, 4.5)["bag_percentile"] == pytest.approx(
        100 * 13 / 14
    )


def test_population_context_omits_the_percentile_without_a_reader_gap():
    assert predict._population_context(_PRED_ROWS, None)["bag_percentile"] is None


def test_calibration_bands_drop_thinly_populated_bins():
    """A bin below MIN_BAND_N is both statistically meaningless and close to
    describing individuals, so it is dropped entirely.

    _PRED_ROWS' 5-year bins all fall below the threshold, which is the
    degenerate case worth pinning: an empty calibration is a valid outcome
    that every consumer has to survive (`charts.calibration` returns "" and
    the report omits the figure), not something to paper over.
    """
    assert predict._calibration_bands(_PRED_ROWS) == []

    dense = [_pred_row(31.0 + i * 0.1, 33.0 + i * 0.1, 32.0 + i * 0.1) for i in range(20)]
    bands = predict._calibration_bands(dense)
    assert [b["age_lo"] for b in bands] == [30.0]
    assert bands[0]["n"] == 20
    assert bands[0]["median"] == pytest.approx(32.95, abs=0.05)
    assert bands[0]["p10"] < bands[0]["median"] < bands[0]["p90"]


def test_bag_histogram_is_symmetric_and_conserves_the_cohort():
    histogram = predict._bag_histogram(predict._cohort_bag(_PRED_ROWS))
    edges = histogram["edges"]
    assert len(edges) == predict.BAG_HIST_BINS + 1
    assert edges[0] == pytest.approx(-edges[-1])
    # Values are clipped into range, never dropped.
    assert sum(histogram["counts"]) == len(_PRED_ROWS)


def test_prediction_json_carries_the_population_block(tmp_path):
    (tmp_path / "features").mkdir()
    (tmp_path / "features" / "features.json").write_text(
        '{"atlas__R1__vol_gm": 3.0, "atlas__R2__vol_gm": 4.0, "TIV": 1500.0}'
    )
    result = predict.PredictStage().run(tmp_path, _manifest(age=52.0))
    payload = json.loads((tmp_path / "predict" / "prediction.json").read_text())

    assert payload["chronological_age"] == 52.0
    assert payload["bag_corrected"] == pytest.approx(2.0)  # corrected 54.0 - 52.0
    assert payload["population"]["n"] == len(_PRED_ROWS)
    assert result.metrics["bag_percentile"] == payload["population"]["bag_percentile"]
