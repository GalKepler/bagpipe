"""End-to-end Pillar 4 pipeline (DESIGN.md §6): uploaded T1w (DICOM or NIfTI)
-> NIfTI -> defaced -> CAT12 (apptainer) -> tabular features -> age
prediction -> regional norm comparison.

Every stage is a separate function so tests can exercise the pure parts
(feature vectorization, prediction, norms) without dcm2niix/pydeface/
apptainer installed. `run()` wires them together for the real deployment.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cloudpickle
import numpy as np
import pandas as pd

from bagpipe.app.cat12_parse import extract_features
from bagpipe.app.normative import fit_norms, regional_zscores
from bagpipe.core.config import get_path, load_config
from bagpipe.db.base import get_session
from bagpipe.db.models import ModelRegistry, Prediction
from bagpipe.models.bias_correction import ColeCorrection
from bagpipe.models.tabular import SEX_MAP, region_columns_for

DICOM_SUFFIXES = {".dcm", ".zip"}
NIFTI_SUFFIXES = {".nii", ".nii.gz"}


class PipelineError(RuntimeError):
    pass


def _is_nifti(path: Path) -> bool:
    return path.name.endswith(".nii") or path.name.endswith(".nii.gz")


def to_nifti(input_path: Path, work_dir: Path) -> Path:
    """DICOM directory/zip -> NIfTI via dcm2niix; NIfTI passes through."""
    if _is_nifti(input_path):
        dest = work_dir / input_path.name
        shutil.copy(input_path, dest)
        return dest

    dicom_dir = input_path
    if input_path.suffix == ".zip":
        dicom_dir = work_dir / "dicom"
        dicom_dir.mkdir(exist_ok=True)
        shutil.unpack_archive(input_path, dicom_dir)

    subprocess.run(
        ["dcm2niix", "-z", "y", "-f", "t1w", "-o", str(work_dir), str(dicom_dir)],
        check=True,
        capture_output=True,
    )
    out = sorted(work_dir.glob("t1w*.nii.gz"))
    if not out:
        raise PipelineError(f"dcm2niix produced no NIfTI output for {input_path}")
    return out[0]


def deface(nifti_path: Path, work_dir: Path) -> Path:
    defaced = work_dir / f"defaced_{nifti_path.name}"
    subprocess.run(
        ["pydeface", "--outfile", str(defaced), str(nifti_path)],
        check=True,
        capture_output=True,
    )
    return defaced


def run_cat12(nifti_path: Path, work_dir: Path) -> tuple[Path, Path]:
    """Runs the CAT12 apptainer image (see `container/cat12.def`) on
    `nifti_path`, producing `catROI_<name>.xml`/`cat_<name>.xml` under
    `work_dir`. Requires `paths.cat12_apptainer_image` in config/local.yaml.
    """
    image = get_path("cat12_apptainer_image")
    subprocess.run(
        ["apptainer", "run", "--bind", f"{work_dir}:/data", str(image), f"/data/{nifti_path.name}"],
        check=True,
        capture_output=True,
    )
    stem = nifti_path.name.removesuffix(".nii.gz").removesuffix(".nii")
    catroi_xml = work_dir / "report" / f"catROI_{stem}.xml"
    cat_xml = work_dir / "report" / f"cat_{stem}.xml"
    if not catroi_xml.exists() or not cat_xml.exists():
        raise PipelineError(f"CAT12 run did not produce expected XML reports under {work_dir}")
    return catroi_xml, cat_xml


@dataclass
class BAGResult:
    predicted_age_raw: float
    predicted_age_corrected: float
    regional_zscores: dict[str, float]
    n_regions_scored: int


def _load_production_model(name: str) -> tuple[object, dict, int]:
    with get_session() as session:
        row = (
            session.query(ModelRegistry)
            .filter_by(name=name, stage="production")
            .order_by(ModelRegistry.trained_at.desc())
            .first()
        )
        if row is None:
            raise PipelineError(f"no production model registered for name={name!r}")
        with open(row.artifact_path, "rb") as f:
            model = cloudpickle.load(f)
        config = json.loads(row.config_json)
        model_id = row.model_id
    return model, config, model_id


def _fit_cole_corrector(model_id: int) -> ColeCorrection:
    """Fits Cole correction on the promoted model's own stored CV
    predictions (`predictions` table) — always in sync with the deployed
    artifact, no separate corrector-persistence step needed.
    """
    with get_session() as session:
        rows = session.query(Prediction).filter_by(model_id=model_id).all()
    if not rows:
        raise PipelineError(f"no stored predictions for model_id={model_id}, can't bias-correct")
    y_true = np.array([r.age_true for r in rows])
    y_pred = np.array([r.predicted_age_raw for r in rows])
    return ColeCorrection().fit(y_true, y_pred)


def predict_and_score(
    features: dict[str, float], sex: str, model_name: str = "stacked"
) -> BAGResult:
    """Pure prediction step: given a parsed feature dict (see
    `cat12_parse.extract_features`) and reported sex, returns predicted age
    (raw + Cole-corrected) and regional z-scores against the training
    population. Separated from CAT12/DICOM handling so it's unit-testable.
    """
    model, config, model_id = _load_production_model(model_name)
    metrics = config.get("features", {}).get("metrics", ["vol_gm"])
    region_columns = region_columns_for(metrics)

    missing = [c for c in region_columns if c not in features]
    if missing:
        raise PipelineError(
            f"{len(missing)} region column(s) missing from parsed features "
            f"(atlas mismatch with training?): {missing[:5]}..."
        )

    sex_code = SEX_MAP.get(sex)
    if sex_code is None:
        raise PipelineError(f"unrecognized sex value {sex!r}, expected one of {sorted(SEX_MAP)}")
    tiv = features["TIV"]

    x = np.array([[features[c] for c in region_columns] + [tiv, sex_code]])
    raw = float(model.predict(x)[0])

    corrector = _fit_cole_corrector(model_id)
    corrected = float(corrector.transform(np.array([raw]))[0])

    norms = fit_norms(region_columns)
    zscores = regional_zscores(features, norms, age=corrected, sex=sex_code, tiv=tiv)

    return BAGResult(
        predicted_age_raw=raw,
        predicted_age_corrected=corrected,
        regional_zscores=zscores,
        n_regions_scored=len(zscores),
    )


def run(input_path: Path, sex: str, work_dir: Path, model_name: str = "stacked") -> BAGResult:
    """Full pipeline: upload -> NIfTI -> defaced -> CAT12 -> features -> BAG."""
    work_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    atlas_name = cfg["app"]["atlas_name"]
    atlas_key = cfg["app"]["atlas_key"]
    lut = pd.read_csv(get_path("atlas_lut_file"), sep="\t")

    nifti = to_nifti(input_path, work_dir)
    defaced_nifti = deface(nifti, work_dir)
    catroi_xml, cat_xml = run_cat12(defaced_nifti, work_dir)

    # ponytail: reloads the model artifact a second time inside
    # predict_and_score — one upload at a time, not a hot path; add caching
    # if this pipeline ever serves concurrent requests from one process.
    config, _model_id = _load_production_model(model_name)[1:]
    metrics = config.get("features", {}).get("metrics", ["vol_gm"])
    features = extract_features(catroi_xml, cat_xml, atlas_name, atlas_key, lut, metrics)

    return predict_and_score(features, sex, model_name)
