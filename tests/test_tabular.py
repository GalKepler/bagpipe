"""build_region_matrix against tiny synthetic Parquet fixtures — no real data."""

from __future__ import annotations

import numpy as np
import pandas as pd

from bagpipe.models.tabular import build_region_mapping, build_region_matrix, region_columns_for


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


def test_build_region_matrix_atlases_filter(tmp_path):
    regional = pd.DataFrame(
        [
            {
                "subject_key": "S1",
                "session_id": "01",
                "atlas": "surf_DK40",
                "region": "R1",
                "metric": "thickness",
                "value": 2.5,
            },
            {
                "subject_key": "S1",
                "session_id": "01",
                "atlas": "surf_Schaefer2018N400n7",
                "region": "R1",
                "metric": "thickness",
                "value": 2.6,
            },
        ]
    )
    globals_df = pd.DataFrame(
        [{"subject_key": "S1", "session_id": "01", "age": 45.0, "sex": "M", "TIV": 1500.0}]
    )
    regional.to_parquet(tmp_path / "regional.parquet")
    globals_df.to_parquet(tmp_path / "globals.parquet")

    X, y, groups, region_columns, session_ids = build_region_matrix(
        tmp_path, atlases=["surf_Schaefer2018N400n7"]
    )
    assert region_columns == ["surf_Schaefer2018N400n7__R1__thickness"]
    assert X.shape == (1, 3)


def test_build_region_matrix_keeps_rows_missing_some_regions(tmp_path):
    # S2 has no Hippocampus_R row at all — used to be dropped entirely;
    # now kept with NaN in that column for downstream imputation.
    regional = pd.DataFrame(
        [
            {
                "subject_key": "S1",
                "session_id": "01",
                "atlas": "a",
                "region": "Hippocampus_L",
                "metric": "vol_gm",
                "value": 3.5,
            },
            {
                "subject_key": "S1",
                "session_id": "01",
                "atlas": "a",
                "region": "Hippocampus_R",
                "metric": "vol_gm",
                "value": 3.6,
            },
            {
                "subject_key": "S2",
                "session_id": "01",
                "atlas": "a",
                "region": "Hippocampus_L",
                "metric": "vol_gm",
                "value": 3.1,
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

    assert X.shape == (2, 4)  # both sessions kept, not just S1
    assert list(groups) == ["S1", "S2"]
    assert np.isnan(X[1, 1])  # S2's missing Hippocampus_R is NaN, not dropped


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


def test_build_region_mapping_fuses_surface_and_volume():
    """The volume atlas calls a region 'LH_Cont_Cing_1'; the surface atlas
    calls the exact same region '7Networks_LH_Cont_Cing_1' — a region's
    volume and its surface metrics must land in ONE base-learner group, not
    two independent single-modality ones (the 2026-09 fix)."""
    columns = [
        "Schaefer2018N400n7Tian2020S2__LH_Cont_Cing_1__vol_gm",
        "Schaefer2018N400n7Tian2020S2__LH_Cont_Cing_1__vol_wm",
        "surf_Schaefer2018N400n7__7Networks_LH_Cont_Cing_1__thickness",
    ]
    mapping = build_region_mapping(columns)
    assert len(mapping) == 1
    (group,) = mapping.values()
    assert sorted(group) == [0, 1, 2]


def test_build_region_mapping_keeps_tian_subcortical_volume_only():
    """Tian subcortical regions (part of the volume atlas) have no surface
    counterpart — canonicalizing a name nothing else matches must stay a
    singleton, not accidentally merge with an unrelated region."""
    columns = [
        "Schaefer2018N400n7Tian2020S2__NAc-core-lh__vol_gm",
        "Schaefer2018N400n7Tian2020S2__LH_Cont_Cing_1__vol_gm",
        "surf_Schaefer2018N400n7__7Networks_LH_Cont_Cing_1__thickness",
    ]
    mapping = build_region_mapping(columns)
    assert len(mapping) == 2
    assert mapping["NAc-core-lh"] == [0]


def test_build_region_mapping_does_not_fuse_across_different_parcellations():
    """surf_DK40 is a different parcellation from the Schaefer volume atlas
    — even if a region name happened to collide, only atlases explicitly
    marked fusible (the two Schaefer2018N400n7 variants) should merge."""
    columns = [
        "Schaefer2018N400n7Tian2020S2__LH_Cont_Cing_1__vol_gm",
        "surf_DK40__LH_Cont_Cing_1__thickness",
    ]
    mapping = build_region_mapping(columns)
    assert len(mapping) == 2
    assert set(mapping) == {"LH_Cont_Cing_1", "surf_DK40__LH_Cont_Cing_1"}
