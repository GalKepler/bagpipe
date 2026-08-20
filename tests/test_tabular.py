"""build_region_matrix against tiny synthetic Parquet fixtures — no real data."""

from __future__ import annotations

import pandas as pd

from bagpipe.models.tabular import build_region_matrix, region_columns_for


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

    X, y, groups, region_columns, session_ids = build_region_matrix(tmp_path)

    assert X.shape == (2, 4)  # 2 regions + TIV + sex
    assert region_columns == [
        "neuromorphometrics__Hippocampus_L__vol_gm",
        "neuromorphometrics__Hippocampus_R__vol_gm",
    ]
    assert list(y) == [45.0, 62.0]
    assert list(groups) == ["S1", "S2"]
    assert list(X[:, -1]) == [0.0, 1.0]  # sex encoded M=0, F=1
    assert list(session_ids) == ["01", "01"]


def test_region_columns_for(tmp_path):
    regional = pd.DataFrame(
        [
            {"atlas": "a", "region": "R1", "metric": "vol_gm", "value": 1.0},
            {"atlas": "a", "region": "R1", "metric": "vol_wm", "value": 1.0},
            {"atlas": "a", "region": "R2", "metric": "vol_gm", "value": 1.0},
        ]
    )
    regional.to_parquet(tmp_path / "regional.parquet")

    assert region_columns_for(["vol_gm"], datasets_dir=tmp_path) == [
        "a__R1__vol_gm",
        "a__R2__vol_gm",
    ]
    assert region_columns_for(["vol_gm", "vol_wm"], datasets_dir=tmp_path) == [
        "a__R1__vol_gm",
        "a__R1__vol_wm",
        "a__R2__vol_gm",
    ]
