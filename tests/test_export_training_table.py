import pandas as pd
from sqlalchemy import create_engine

from bagpipe.db.export_training_table import _globals, _qc_failed_session_ids, _regional

COHORTS = pd.DataFrame(
    {
        "subject_key": ["s1", "s2"],
        "session_id": ["ses1", "ses2"],
        "cohort": ["snbb", "snbb"],
        "lab": ["a", "a"],
        "age": [30.0, 40.0],
        "sex": ["M", "F"],
    }
)


def _engine():
    engine = create_engine("sqlite://")
    features = pd.DataFrame(
        [
            {
                "subject_key": "s1",
                "session_id": "ses1",
                "atlas": "",
                "region": "global",
                "metric": "TIV",
                "value": 1500.0,
                "source": "cat12",
            },
            {
                "subject_key": "s1",
                "session_id": "ses1",
                "atlas": "",
                "region": "global",
                "metric": "TIV",
                "value": 1600.0,
                "source": "cat12_v26",
            },
            *[
                {
                    "subject_key": "s1",
                    "session_id": "ses1",
                    "atlas": "",
                    "region": "global",
                    "metric": metric,
                    "value": 1.0,
                    "source": "cat12_v26",
                }
                for metric in ["vol_gm", "vol_wm", "vol_csf", "vol_wmh"]
            ],
            {
                "subject_key": "s1",
                "session_id": "ses1",
                "atlas": "atlasA",
                "region": "r1",
                "metric": "vol_gm",
                "value": 5.0,
                "source": "cat12",
            },
            {
                "subject_key": "s1",
                "session_id": "ses1",
                "atlas": "atlasA",
                "region": "r1",
                "metric": "vol_gm",
                "value": 6.0,
                "source": "cat12_v26",
            },
        ]
    )
    features.to_sql("features", engine, index=False)
    return engine


def test_source_filter_selects_only_matching_rows():
    engine = _engine()
    globals_v26 = _globals(engine, COHORTS, source="cat12_v26")
    assert globals_v26.loc[globals_v26["subject_key"] == "s1", "TIV"].item() == 1600.0

    regional_v26 = _regional(engine, COHORTS, source="cat12_v26")
    assert regional_v26["value"].tolist() == [6.0]


def test_no_source_pools_every_version():
    engine = _engine()
    regional_all = _regional(engine, COHORTS, source=None)
    assert sorted(regional_all["value"].tolist()) == [5.0, 6.0]


def test_qc_failed_session_ids_flags_low_siqr_and_respects_source():
    engine = _engine()
    quality = pd.DataFrame(
        [
            {"subject_key": "s1", "session_id": "ses1", "source": "cat12_v26", "siqr_pct": 65.71},
            {"subject_key": "s2", "session_id": "ses2", "source": "cat12_v26", "siqr_pct": 85.0},
            {"subject_key": "s1", "session_id": "ses1", "source": "cat12", "siqr_pct": 88.0},
        ]
    )
    quality.to_sql("cat12_quality", engine, index=False)

    assert _qc_failed_session_ids(engine, source="cat12_v26") == {"ses1"}
    assert _qc_failed_session_ids(engine, source="cat12") == set()
    assert _qc_failed_session_ids(engine, source=None) == {"ses1"}
