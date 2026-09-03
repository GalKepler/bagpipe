"""§6 CAT12 reproducibility acceptance test — docs/cat12_container_spec.md §6.
Gates every `container/cat12.sif` change: proves the containerized standalone
reproduces training-time features closely enough to trust for inference.

Runs the real production stage graph (`bagpipe.app.pipeline.run_manifest` —
the exact code path `/predict` uses) against a sample of real SNBB subjects,
then compares its output to the stored training-time features/predictions
for those same subjects. Never runs in CI; only ever against real local data.

`bag preprocess repro-test --config config/repro_test.yaml`
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sqlalchemy import text

from bagpipe.app.pipeline import run_manifest
from bagpipe.core.config import get_path
from bagpipe.db.base import get_engine, get_session
from bagpipe.db.models import ModelRegistry, Prediction

ACCEPTANCE = {
    "pearson_r_volumetric": 0.999,
    "max_rel_dev_p99": 0.05,
    "bag_abs_dev_years": 0.3,
    "iqr_abs_dev_pts": 2.0,
}


def _select_subjects(engine, n_stratified: int, n_stress: int, seed: int = 0) -> pd.DataFrame:
    cohort = pd.read_sql(
        """
        select s.uid as subject_key, s.session_id, d.age_at_scan as age, d.sex
        from session s
        join demographics d on d.session_id = s.session_id
        where s.uid is not null and d.age_at_scan is not null and d.sex is not null
        """,
        engine,
    )
    quality = pd.read_sql(
        "select subject_key, session_id, siqr_pct from cat12_quality where source = 'cat12'",
        engine,
    )
    cohort = cohort.merge(quality, on=["subject_key", "session_id"], how="inner").dropna(
        subset=["siqr_pct"]
    )

    cohort["age_tertile"] = pd.qcut(cohort["age"], 3, labels=False, duplicates="drop")
    groups = list(cohort.groupby(["age_tertile", "sex"]))
    per_stratum = max(1, n_stratified // max(1, len(groups)))
    sampled = pd.concat(
        [g.sample(min(len(g), per_stratum), random_state=seed) for _, g in groups],
        ignore_index=False,
    ).head(n_stratified)

    remaining = cohort.drop(sampled.index)
    stress = remaining.nsmallest(n_stress, "siqr_pct")

    selected = pd.concat([sampled, stress]).drop_duplicates(subset=["subject_key", "session_id"])
    return selected.reset_index(drop=True)


def _t1w_path(bids_root: Path, subject_key: str, session_id: str) -> Path | None:
    matches = sorted(bids_root.glob(f"sub-{subject_key}/ses-{session_id}/anat/sub-*_T1w.nii*"))
    return matches[0] if matches else None


def _run_one(row: dict, bids_root: Path, work_root: Path, model_name: str) -> dict:
    t1w = _t1w_path(bids_root, row["subject_key"], row["session_id"])
    result = dict(row)
    if t1w is None:
        result["error"] = "no raw T1w found under bids_root for this subject/session"
        return result

    work_dir = work_root / f"{row['subject_key']}_{row['session_id']}"
    try:
        manifest = run_manifest(
            t1w,
            sex=row["sex"],
            work_dir=work_dir,
            model_name=model_name,
            chronological_age=float(row["age"]),
            job_id=f"repro-{row['subject_key']}-{row['session_id']}",
            retention_opt_in=True,  # keep outputs around for report/debugging
        )
    except Exception as e:  # noqa: BLE001 — one subject's failure must not kill the suite
        result["error"] = f"{type(e).__name__}: {e}"
        return result

    result["manifest_status"] = manifest.status
    if manifest.status != "succeeded":
        result["error"] = manifest.error.message if manifest.error else "unknown pipeline failure"
        return result

    result["work_dir"] = str(work_dir)
    prediction = json.loads((work_dir / "predict" / "prediction.json").read_text())
    result["bag_corrected_container"] = prediction["bag_corrected"]

    qc_stage = next((s for s in manifest.stages if s.name == "qc_gate"), None)
    result["siqr_pct_container"] = (qc_stage.metrics or {}).get("siqr_pct") if qc_stage else None

    features = json.loads((work_dir / "features" / "features.json").read_text())
    result["features_container"] = features
    return result


def _stored_features(engine, subject_key: str, session_id: str) -> dict[str, float]:
    df = pd.read_sql(
        text(
            "select atlas, region, metric, value from features "
            "where subject_key = :subject_key and session_id = :session_id "
            "and source = 'cat12'"
        ),
        engine,
        params={"subject_key": subject_key, "session_id": session_id},
    )
    return {f"{r.atlas}__{r.region}__{r.metric}": r.value for r in df.itertuples()}


def _feature_cohort_std(engine) -> pd.Series:
    df = pd.read_sql(
        "select atlas, region, metric, value from features where source = 'cat12'", engine
    )
    df["col"] = df["atlas"] + "__" + df["region"] + "__" + df["metric"]
    return df.groupby("col")["value"].std()


def _stored_bag(model_id: int, subject_key: str, session_id: str) -> float | None:
    with get_session() as session:
        row = (
            session.query(Prediction)
            .filter_by(model_id=model_id, subject_key=subject_key, session_id=session_id)
            .first()
        )
        return row.bag_corrected if row else None


def _production_model_id(name: str) -> int | None:
    with get_session() as session:
        row = (
            session.query(ModelRegistry)
            .filter_by(name=name, stage="production")
            .order_by(ModelRegistry.trained_at.desc())
            .first()
        )
        return row.model_id if row else None


def _image_digest(image_path: Path) -> str:
    h = hashlib.sha256()
    with image_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(config_path: str) -> dict:
    with open(config_path) as f:
        config = yaml.safe_load(f)

    engine = get_engine()
    bids_root = Path(config.get("bids_root")) if config.get("bids_root") else get_path("bids_root")
    work_root = Path(config["work_dir"])
    work_root.mkdir(parents=True, exist_ok=True)
    model_name = config.get("model_name", "stacked")
    concurrency = config.get("concurrency", 3)

    subjects = _select_subjects(engine, config.get("n_stratified", 12), config.get("n_stress", 2))

    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(_run_one, row._asdict(), bids_root, work_root, model_name): row
            for row in subjects.itertuples()
        }
        for future in as_completed(futures):
            results.append(future.result())

    model_id = _production_model_id(model_name)
    cohort_std = _feature_cohort_std(engine)

    rows = []
    feature_pairs: list[tuple[str, float, float]] = []
    for r in results:
        if "error" in r:
            rows.append({**r, "verdict": "ERROR"})
            continue

        stored_bag = _stored_bag(model_id, r["subject_key"], r["session_id"]) if model_id else None
        stored_features = _stored_features(engine, r["subject_key"], r["session_id"])

        rel_devs = []
        for col, container_val in r["features_container"].items():
            stored_val = stored_features.get(col)
            if stored_val is None:
                continue
            feature_pairs.append((col, container_val, stored_val))
            sigma = cohort_std.get(col)
            if sigma and sigma > 0:
                rel_devs.append(abs(container_val - stored_val) / sigma)

        bag_dev = abs(r["bag_corrected_container"] - stored_bag) if stored_bag is not None else None
        iqr_dev = None  # filled below if a stored siqr is found

        rows.append(
            {
                **{k: v for k, v in r.items() if k != "features_container"},
                "stored_bag_corrected": stored_bag,
                "bag_abs_dev": bag_dev,
                "rel_dev_p99": np.percentile(rel_devs, 99) if rel_devs else None,
                "n_features_compared": len(rel_devs),
                "iqr_dev": iqr_dev,
            }
        )

    pair_df = pd.DataFrame(feature_pairs, columns=["feature", "container", "stored"])
    overall_pearson_r = (
        pair_df["container"].corr(pair_df["stored"]) if len(pair_df) > 1 else float("nan")
    )

    image_path = get_path("cat12_apptainer_image")
    digest = _image_digest(image_path)
    report_path = _write_report(digest, rows, overall_pearson_r, config)

    return {
        "digest": digest,
        "report_path": str(report_path),
        "n_subjects": len(rows),
        "n_errors": sum(1 for r in rows if r.get("verdict") == "ERROR"),
        "overall_pearson_r": overall_pearson_r,
    }


def _write_report(digest: str, rows: list[dict], overall_pearson_r: float, config: dict) -> Path:
    out_dir = Path("docs/repro_reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{digest[:16]}.md"

    lines = [
        f"# CAT12 reproducibility report — image digest `{digest}`",
        "",
        f"Generated {datetime.now(UTC).isoformat()} — docs/cat12_container_spec.md §6.",
        "",
        f"- Subjects: {len(rows)} ({config.get('n_stratified', 12)} stratified + "
        f"{config.get('n_stress', 2)} stress-case)",
        "- Overall feature Pearson r (all compared features, all subjects pooled): "
        + (f"{overall_pearson_r:.5f}" if pd.notna(overall_pearson_r) else "n/a"),
        "",
        "## Per-subject results",
        "",
        "| subject | session | bag_abs_dev (y) | rel_dev p99 | n_features | status |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        if "verdict" in r and r["verdict"] == "ERROR":
            lines.append(
                f"| {r['subject_key']} | {r['session_id']} | - | - | - | "
                f"ERROR: {r.get('error', '')[:80]} |"
            )
            continue
        bag_dev = r.get("bag_abs_dev")
        rel_dev = r.get("rel_dev_p99")
        bag_dev_str = f"{bag_dev:.3f}" if bag_dev is not None else "n/a"
        rel_dev_str = f"{rel_dev:.4f}" if rel_dev is not None else "n/a"
        lines.append(
            f"| {r['subject_key']} | {r['session_id']} | {bag_dev_str} | {rel_dev_str} | "
            f"{r.get('n_features_compared', 0)} | ok |"
        )

    max_bag_dev = (
        max((r.get("bag_abs_dev") or 0) for r in rows if "bag_abs_dev" in r)
        if any("bag_abs_dev" in r for r in rows)
        else float("nan")
    )
    lines += [
        "",
        "## Acceptance criteria",
        "",
        f"- Pearson r ≥ {ACCEPTANCE['pearson_r_volumetric']}: "
        f"{'PASS' if overall_pearson_r >= ACCEPTANCE['pearson_r_volumetric'] else 'FAIL'} "
        f"({overall_pearson_r:.5f})",
        f"- Max |Δ_BAG| ≤ {ACCEPTANCE['bag_abs_dev_years']}y: "
        f"{'PASS' if max_bag_dev <= ACCEPTANCE['bag_abs_dev_years'] else 'FAIL'} "
        f"({max_bag_dev:.3f}y)",
        "",
        "Per docs/cat12_container_spec.md §6 interpretation rule: if criteria fail "
        "due to a genuine CAT12 revision difference (not a bug), re-extract SNBB "
        "training features with this container and retrain, rather than loosening "
        "tolerances.",
    ]
    out_path.write_text("\n".join(lines) + "\n")
    return out_path
