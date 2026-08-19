"""SFCN smoke test: tiny synthetic NIfTI volumes, no real data, no GPU
required, no network — checks the regressor and the config-driven `run()`
end-to-end through the shared eval harness, not model quality."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

nib = pytest.importorskip("nibabel")

from bagpipe.models import sfcn  # noqa: E402
from bagpipe.models.sfcn import SFCN, SFCNRegressor  # noqa: E402

TINY_CHANNELS = [4, 8]
SHAPE = (12, 14, 12)


def _write_volumes(tmp_path, n=12, seed=0):
    rng = np.random.default_rng(seed)
    paths, ages = [], []
    for i in range(n):
        age = rng.uniform(20, 80)
        volume = rng.normal(0, 1, size=SHAPE).astype(np.float32) + age * 0.01
        path = tmp_path / f"sub-{i:03d}_mwp1.nii.gz"
        nib.save(nib.Nifti1Image(volume, np.eye(4)), path)
        paths.append(str(path))
        ages.append(age)
    return np.array(paths, dtype=object), np.array(ages, dtype=np.float32)


def test_sfcn_forward_shape():
    model = SFCN(channel_number=TINY_CHANNELS)
    import torch

    x = torch.randn(2, 1, *SHAPE)
    out = model(x)
    assert out.shape == (2,)


def test_sfcn_regressor_fit_predict(tmp_path):
    paths, ages = _write_volumes(tmp_path)
    reg = SFCNRegressor(
        epochs=2, batch_size=2, channel_number=TINY_CHANNELS, num_workers=0, val_fraction=0.2
    )
    reg.fit(paths, ages)
    preds = reg.predict(paths)
    assert preds.shape == ages.shape
    assert np.all(np.isfinite(preds))


def test_sfcn_regressor_fit_callback(tmp_path):
    paths, ages = _write_volumes(tmp_path)
    calls = []
    reg = SFCNRegressor(
        epochs=3, batch_size=2, channel_number=TINY_CHANNELS, num_workers=0, val_fraction=0.2
    )
    reg.fit(
        paths,
        ages,
        callback=lambda epoch, train_loss, val_mae: calls.append((epoch, train_loss, val_mae)),
    )
    assert [c[0] for c in calls] == [0, 1, 2]
    assert all(np.isfinite(c[1]) for c in calls)
    assert all(c[2] is not None and np.isfinite(c[2]) for c in calls)


@pytest.fixture
def fake_paths(tmp_path, monkeypatch):
    datasets_dir = tmp_path / "datasets"
    mlflow_dir = tmp_path / "mlruns"
    datasets_dir.mkdir()
    paths, ages = _write_volumes(datasets_dir, n=12)

    rows = [
        {
            "subject_key": f"S{i}",
            "session_id": "01",
            "cohort": "snbb",
            "image_path_mwp1": p,
            "image_path_wm": None,
            "age": a,
            "sex": "M" if i % 2 == 0 else "F",
            "TIV": 1500.0,
        }
        for i, (p, a) in enumerate(zip(paths, ages, strict=True))
    ]
    pd.DataFrame(rows)[
        ["subject_key", "session_id", "cohort", "image_path_mwp1", "image_path_wm"]
    ].to_parquet(datasets_dir / "image_paths.parquet")
    pd.DataFrame(rows)[["subject_key", "session_id", "age", "sex", "TIV"]].to_parquet(
        datasets_dir / "globals.parquet"
    )

    def fake_get_path(key):
        return {"datasets_dir": datasets_dir, "mlflow_dir": mlflow_dir}[key]

    monkeypatch.setattr(sfcn, "get_path", fake_get_path)
    return tmp_path


def test_sfcn_run_end_to_end(fake_paths):
    config_path = fake_paths / "sfcn.yaml"
    config_path.write_text(
        "model:\n"
        "  epochs: 2\n"
        "  batch_size: 2\n"
        "  channel_number: [4, 8]\n"
        "  num_workers: 0\n"
        "  val_fraction: 0.0\n"
        "bias_correction: none\nn_splits: 3\nmlflow:\n  experiment: test-exp\n"
    )
    result, info = sfcn.run(config_path)
    assert np.isfinite(result.metrics["mae_raw"])
    assert info["n_samples"] == 12

    log_dir = Path(info["log_dir"])
    history = pd.read_csv(log_dir / "history.csv")
    assert set(history["fold"]) == {0, 1, 2}  # one label per outer-CV fold
    assert (history.groupby("fold").size() == 2).all()  # 2 epochs each
    assert (log_dir / "loss_curve.png").exists()
