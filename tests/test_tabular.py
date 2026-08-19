"""build_region_matrix against tiny synthetic Parquet fixtures — no real data."""

from __future__ import annotations

import pandas as pd

from bagpipe.models.tabular import build_region_matrix


def test_build_region_matrix(tmp_path):
    regional = pd.DataFrame(
        [
            {
                "subject_key": "S1",
                "session_id": "01",
                "atlas": "neuromorphometrics",
                "region": "Hippocampus_L",
                "metric": "vol_gm",
                "value": 3.5,
            },
            {
                "subject_key": "S1",
                "session_id": "01",
                "atlas": "neuromorphometrics",
                "region": "Hippocampus_R",
                "metric": "vol_gm",
                "value": 3.6,
            },
            {
                "subject_key": "S2",
                "session_id": "01",
                "atlas": "neuromorphometrics",
                "region": "Hippocampus_L",
                "metric": "vol_gm",
                "value": 3.1,
            },
            {
                "subject_key": "S2",
                "session_id": "01",
                "atlas": "neuromorphometrics",
                "region": "Hippocampus_R",
                "metric": "vol_gm",
                "value": 3.3,
            },
        ]
    )
    globals_df = pd.DataFrame(
        [
            {"subject_key": "S1", "session_id": "01", "age": 45.0, "sex": "M", "TIV": 1500.0},
            {"subject_key": "S2", "session_id": "01", "age": 62.0, "sex": "F", "TIV": 1400.0},
        ]
    )
    regional.to_parquet(tmp_path / "regional.parquet")
    globals_df.to_parquet(tmp_path / "globals.parquet")

    X, y, groups, region_columns = build_region_matrix(tmp_path)

    assert X.shape == (2, 4)  # 2 regions + TIV + sex
    assert region_columns == [
        "neuromorphometrics__Hippocampus_L__vol_gm",
        "neuromorphometrics__Hippocampus_R__vol_gm",
    ]
    assert list(y) == [45.0, 62.0]
    assert list(groups) == ["S1", "S2"]
    assert list(X[:, -1]) == [0.0, 1.0]  # sex encoded M=0, F=1
