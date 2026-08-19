"""End-to-end baseline run against synthetic Parquet fixtures — no real data,
no network: MLflow logs to a local tmp file store."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bagpipe.models import baseline


def _write_fixtures(datasets_dir, n_subjects=30, seed=0):
    rng = np.random.default_rng(seed)
    regional_rows, globals_rows = [], []
    for i in range(n_subjects):
        subject_key = f"S{i}"
        age = rng.uniform(20, 80)
        tiv = rng.uniform(1200, 1700)
        sex = "M" if i % 2 == 0 else "F"
        for region in ("Hippocampus_L", "Hippocampus_R"):
            value = 0.002 * tiv - 0.01 * age + rng.normal(0, 0.05)
            regional_rows.append(
                {
                    "subject_key": subject_key,
                    "session_id": "01",
                    "atlas": "neuromorphometrics",
                    "region": region,
                    "metric": "vol_gm",
                    "value": value,
                }
            )
        globals_rows.append(
            {"subject_key": subject_key, "session_id": "01", "age": age, "sex": sex, "TIV": tiv}
        )
    pd.DataFrame(regional_rows).to_parquet(datasets_dir / "regional.parquet")
    pd.DataFrame(globals_rows).to_parquet(datasets_dir / "globals.parquet")


@pytest.fixture
def fake_paths(tmp_path, monkeypatch):
    datasets_dir = tmp_path / "datasets"
    mlflow_dir = tmp_path / "mlruns"
    datasets_dir.mkdir()
    _write_fixtures(datasets_dir)

    def fake_get_path(key):
        return {"datasets_dir": datasets_dir, "mlflow_dir": mlflow_dir}[key]

    monkeypatch.setattr(baseline, "get_path", fake_get_path)
    return tmp_path


def test_baseline_run_linear(fake_paths):
    config_path = fake_paths / "baseline.yaml"
    config_path.write_text(
        "model:\n  type: linear\n  params: {}\nbias_correction: cole\nn_splits: 3\n"
        "mlflow:\n  experiment: test-exp\n"
    )
    result, info = baseline.run(config_path)
    assert info["region_columns"] == [
        "neuromorphometrics__Hippocampus_L__vol_gm",
        "neuromorphometrics__Hippocampus_R__vol_gm",
    ]
    assert np.isfinite(result.metrics["mae_corrected"])
    assert (fake_paths / "mlruns").exists()


def test_baseline_run_ridge_tunes_alpha(fake_paths):
    config_path = fake_paths / "baseline_ridge.yaml"
    config_path.write_text(
        "model:\n  type: ridge\n  params:\n    alphas: [0.01, 1.0, 100.0]\n"
        "bias_correction: none\nn_splits: 3\nmlflow:\n  experiment: test-exp\n"
    )
    result, info = baseline.run(config_path)
    assert info["region_columns"] == [
        "neuromorphometrics__Hippocampus_L__vol_gm",
        "neuromorphometrics__Hippocampus_R__vol_gm",
    ]
    assert np.isfinite(result.metrics["mae_raw"])


def test_ridge_model_type_picks_alpha_from_grid():
    from bagpipe.models.baseline import MODEL_TYPES

    rng = np.random.default_rng(0)
    X = rng.normal(size=(50, 3))
    y = X[:, 0] * 2 + rng.normal(scale=0.1, size=50)
    model = MODEL_TYPES["ridge"]({"alphas": [0.01, 1.0, 100.0]})
    model.fit(X, y)
    assert model.alpha_ in [0.01, 1.0, 100.0]
