"""predict_and_score against a stubbed model/DB — no real DB, no apptainer,
no CAT12. Exercises vectorization, missing-column and unknown-sex errors,
and that bias correction + regional z-scoring get wired together."""

from __future__ import annotations

import numpy as np
import pytest

from bagpipe.app import pipeline
from bagpipe.app.normative import RegionNorm


class _StubModel:
    def predict(self, x):
        return np.array([50.0 + x[0, 0]])  # deterministic, depends on first region col


REGION_COLUMNS = ["atlas__R1__vol_gm", "atlas__R2__vol_gm"]


@pytest.fixture(autouse=True)
def _stub_dependencies(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "_load_production_model",
        lambda name: (_StubModel(), {"features": {"metrics": ["vol_gm"]}}, 1),
    )
    monkeypatch.setattr(pipeline, "region_columns_for", lambda metrics: REGION_COLUMNS)

    class _IdentityCorrector:
        def transform(self, y_pred):
            return y_pred + 1.0  # arbitrary, distinguishable from raw

    monkeypatch.setattr(pipeline, "_fit_cole_corrector", lambda model_id: _IdentityCorrector())
    monkeypatch.setattr(
        pipeline,
        "fit_norms",
        lambda region_columns: {
            c: RegionNorm(coefs=np.zeros(4), resid_std=1.0) for c in region_columns
        },
    )


def test_predict_and_score_happy_path():
    features = {"atlas__R1__vol_gm": 3.0, "atlas__R2__vol_gm": 4.0, "TIV": 1500.0}
    result = pipeline.predict_and_score(features, sex="F")

    assert result.predicted_age_raw == pytest.approx(53.0)  # 50 + region1(3.0)
    assert result.predicted_age_corrected == pytest.approx(54.0)  # +1 from stub corrector
    assert result.n_regions_scored == 2
    assert set(result.regional_zscores) == set(REGION_COLUMNS)


def test_predict_and_score_missing_region_raises():
    features = {"atlas__R1__vol_gm": 3.0, "TIV": 1500.0}  # R2 missing
    with pytest.raises(pipeline.PipelineError, match="missing from parsed features"):
        pipeline.predict_and_score(features, sex="F")


def test_predict_and_score_unknown_sex_raises():
    features = {"atlas__R1__vol_gm": 3.0, "atlas__R2__vol_gm": 4.0, "TIV": 1500.0}
    with pytest.raises(pipeline.PipelineError, match="unrecognized sex"):
        pipeline.predict_and_score(features, sex="nonbinary-not-in-map")
