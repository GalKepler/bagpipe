"""predict stage against a stubbed model/DB — no real DB, no apptainer,
no CAT12. Exercises vectorization, missing-column and unknown-sex errors,
and that bias correction + regional z-scoring get wired together."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from bagpipe.app.normative import RegionNorm
from bagpipe.app.pipeline import predict
from bagpipe.app.pipeline.base import PipelineError
from bagpipe.app.pipeline.models import Environment, JobInput, Manifest


class _StubModel:
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


@pytest.fixture(autouse=True)
def _stub_dependencies(monkeypatch):
    monkeypatch.setattr(
        predict,
        "_load_production_model",
        lambda name: (_StubModel(), {"features": {"metrics": ["vol_gm"]}}, 1),
    )
    monkeypatch.setattr(predict, "region_columns_for", lambda metrics: REGION_COLUMNS)

    class _IdentityCorrector:
        def transform(self, y_pred):
            return y_pred + 1.0  # arbitrary, distinguishable from raw

    monkeypatch.setattr(predict, "_fit_cole_corrector", lambda model_id: _IdentityCorrector())
    monkeypatch.setattr(
        predict,
        "fit_norms",
        lambda region_columns: {
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
