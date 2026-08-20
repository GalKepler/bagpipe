"""fit_norms / regional_zscores against tiny synthetic Parquet fixtures."""

from __future__ import annotations

import numpy as np
import pandas as pd

from bagpipe.app.normative import fit_norms, regional_zscores


def _write_fixtures(tmp_path, n=40, seed=0):
    rng = np.random.default_rng(seed)
    ages = rng.uniform(20, 80, size=n)
    sexes = rng.integers(0, 2, size=n).astype(float)
    tivs = rng.uniform(1300, 1700, size=n)
    # region volume shrinks with age, roughly linear + noise
    vol = 5.0 - 0.02 * ages + rng.normal(0, 0.05, size=n)

    regional = pd.DataFrame(
        {
            "subject_key": [f"S{i}" for i in range(n)],
            "session_id": ["01"] * n,
            "atlas": ["neuromorphometrics"] * n,
            "region": ["Hippocampus_L"] * n,
            "metric": ["vol_gm"] * n,
            "value": vol,
        }
    )
    globals_df = pd.DataFrame(
        {
            "subject_key": [f"S{i}" for i in range(n)],
            "session_id": ["01"] * n,
            "age": ages,
            "sex": ["F" if s else "M" for s in sexes],
            "TIV": tivs,
        }
    )
    regional.to_parquet(tmp_path / "regional.parquet")
    globals_df.to_parquet(tmp_path / "globals.parquet")


def test_fit_norms_and_zscores(tmp_path):
    _write_fixtures(tmp_path)
    col = "neuromorphometrics__Hippocampus_L__vol_gm"
    norms = fit_norms([col], datasets_dir=tmp_path)

    assert col in norms
    assert norms[col].resid_std > 0

    # a value exactly at the fitted expectation should z-score to ~0
    age, sex, tiv = 50.0, 0.0, 1500.0
    expected = float(np.array([age, sex, tiv, 1.0]) @ norms[col].coefs)
    z = regional_zscores({col: expected}, norms, age=age, sex=sex, tiv=tiv)
    assert abs(z[col]) < 1e-6

    # a big outlier should score as a large |z|
    z_outlier = regional_zscores({col: expected + 5 * norms[col].resid_std}, norms, age, sex, tiv)
    assert abs(z_outlier[col]) > 4
