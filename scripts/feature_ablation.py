"""Which per-region metrics (vol_gm/wm/csf, thickness, gyrification,
sulcal_depth, fractal_dimension, area) actually help the regional stacked
ensemble (architecture fixed — this is a measure-selection study, not an
ensemble-choice study).

Rerun after cohort reprocessing progresses further: `python scripts/feature_ablation.py`.
Not wired into `bag` — throwaway diagnostic, not a production training run
(no MLflow logging, no promotion).

Design: every combo is evaluated on the SAME session set (the full-panel
intersection — sessions with every surface metric present), so MAE deltas
reflect the metric's marginal effect, not sample-size differences. Every
combo runs under BOTH base estimators (RidgeCV, HistGradientBoosting) —
at low n a linear per-region base learner is noise-dominated and can hide
a real metric effect (or show a fake one), so a measure-selection
conclusion only counts if it holds under both.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from regional_stacker import RegionalStackingRegressor, default_alpha_grid
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bagpipe.models.bias_correction import get_corrector  # noqa: E402
from bagpipe.models.covariate_adjustment import TIVSexAdjustedRegressor  # noqa: E402
from bagpipe.models.evaluate import evaluate  # noqa: E402
from bagpipe.models.tabular import build_region_mapping, build_region_matrix  # noqa: E402

DATASETS_DIR = Path("outputs/datasets_v26")
ATLASES = ["Schaefer2018N400n7Tian2020S2", "surf_Schaefer2018N400n7"]  # one parcellation, both sides
VOLUME = ["vol_gm", "vol_wm", "vol_csf"]
SURFACE = ["thickness", "gyrification", "sulcal_depth", "fractal_dimension", "area"]
FULL_PANEL = VOLUME + SURFACE

# cumulative: does adding each surface metric on top of volume help?
CUMULATIVE_COMBOS = {
    "volume_only": VOLUME,
    "+thickness": VOLUME + ["thickness"],
    "+gyrification": VOLUME + ["thickness", "gyrification"],
    "+sulcal_depth": VOLUME + ["thickness", "gyrification", "sulcal_depth"],
    "+fractal_dimension": VOLUME + ["thickness", "gyrification", "sulcal_depth", "fractal_dimension"],
    "full_panel": FULL_PANEL,
}
# leave-one-out from the full panel: which single metric hurts most if dropped?
LOO_COMBOS = {f"full_minus_{m}": [x for x in FULL_PANEL if x != m] for m in SURFACE}

ESTIMATOR_VARIANTS = {
    # matches config/models/stacked_v26*.yaml's base/meta (production default)
    "ridgecv/ridgecv": (
        lambda: RidgeCV(alphas=default_alpha_grid()),
        lambda: RidgeCV(alphas=default_alpha_grid()),
    ),
    "hgbr/ridgecv": (
        lambda: HistGradientBoostingRegressor(random_state=0),
        lambda: RidgeCV(alphas=default_alpha_grid()),
    ),
    # matches config/models/stacked_v26*.yaml as of 2026-08-26: hgbr too slow
    # at full-cohort scale, this is the fast closed-form fallback
    "ridgecv_interactions/ridgecv": (
        lambda: make_pipeline(
            PolynomialFeatures(interaction_only=True, include_bias=False),
            RidgeCV(alphas=default_alpha_grid()),
        ),
        lambda: RidgeCV(alphas=default_alpha_grid()),
    ),
}


def _stacked_model_fn(region_mapping, base_fn, meta_fn):
    def build():
        stacker = RegionalStackingRegressor(
            region_mapping=region_mapping,
            base_estimator=base_fn(),
            meta_estimator=meta_fn(),
            outer_cv=5,
            inner_cv=3,
            n_jobs=-1,
            random_state=0,
        )
        return TIVSexAdjustedRegressor(lambda: stacker)

    return build


def run_combo(name, metrics, common_sessions, base_fn, meta_fn, n_splits=5):
    X, y, groups, region_columns, session_ids = build_region_matrix(
        DATASETS_DIR, metrics=metrics, atlases=ATLASES
    )
    n_before = len(y)
    if common_sessions is not None:
        mask = np.isin(session_ids, common_sessions)
        X, y, groups = X[mask], y[mask], groups[mask]

    n_unique_groups = len(np.unique(groups))
    if n_unique_groups < 2:
        print(f"  {name}: skipped, only {n_unique_groups} subject(s) after filtering")
        return None
    splits = min(n_splits, n_unique_groups)

    region_mapping = build_region_mapping(region_columns)
    model_fn = _stacked_model_fn(region_mapping, base_fn, meta_fn)
    bias_corrector = get_corrector("cole")
    result = evaluate(model_fn, X, y, groups, n_splits=splits, bias_corrector=bias_corrector)
    return {
        "combo": name,
        "n_samples": len(y),
        "n_samples_unfiltered": n_before,
        "n_regions": len(region_mapping),
        "n_splits": splits,
        **result.metrics,
    }


def main():
    # full-panel session set defines the fair comparison sample
    _, _, _, _, full_panel_sessions = build_region_matrix(
        DATASETS_DIR, metrics=FULL_PANEL, atlases=ATLASES
    )
    common_sessions = np.unique(full_panel_sessions)
    print(f"full-panel intersection: {len(common_sessions)} sessions\n")

    rows = []
    for variant_name, (base_fn, meta_fn) in ESTIMATOR_VARIANTS.items():
        print(f"== cumulative metric additions [{variant_name}] ==")
        for name, metrics in CUMULATIVE_COMBOS.items():
            r = run_combo(name, metrics, common_sessions, base_fn, meta_fn)
            if r:
                r["estimator"] = variant_name
                rows.append(r)
                print(f"  {name}: mae_raw={r['mae_raw']:.3f} mae_corrected={r['mae_corrected']:.3f} "
                      f"r2_raw={r['r2_raw']:.3f} n={r['n_samples']} regions={r['n_regions']}")

        print(f"\n== leave-one-out from full panel [{variant_name}] ==")
        for name, metrics in LOO_COMBOS.items():
            r = run_combo(name, metrics, common_sessions, base_fn, meta_fn)
            if r:
                r["estimator"] = variant_name
                rows.append(r)
                print(f"  {name}: mae_raw={r['mae_raw']:.3f} mae_corrected={r['mae_corrected']:.3f} "
                      f"r2_raw={r['r2_raw']:.3f} n={r['n_samples']} regions={r['n_regions']}")
        print()

    out_path = Path("outputs/feature_ablation_results.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_path, index=False)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
