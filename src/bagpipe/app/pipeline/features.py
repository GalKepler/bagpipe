"""extract_features stage — docs/design_inference_pipeline.md § Stage
specifications: extract_features. Wraps bagpipe.app.cat12_parse against
the production model's exact feature schema (region_columns_for).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from bagpipe.app.cat12_parse import extract_features
from bagpipe.app.pipeline.base import ErrorCode, PipelineError, StageResult
from bagpipe.core.config import get_path, load_config
from bagpipe.models.tabular import region_columns_for


class FeaturesStage:
    name = "extract_features"

    def __init__(
        self,
        model_metrics: list[str],
        atlases: list[str] | None = None,
        datasets_dir: Path | None = None,
    ):
        """`atlases`/`datasets_dir` should come from the same production
        model config `predict.py` reads (`config["features"]["atlases"]`,
        `config["datasets_dir"]`) — see `region_columns_for`'s own atlases
        filter (bagpipe.models.tabular). Defaulting to None (all atlases,
        `get_path("datasets_dir")`) keeps this back-compatible with the
        current volume-only production model, where it makes no difference
        (see CLAUDE.md's Agent SCI report for why this matters the moment a
        surface model is promoted).
        """
        self.model_metrics = model_metrics
        self.atlases = atlases
        self.datasets_dir = datasets_dir

    def run(self, workspace: Path, manifest) -> StageResult:  # noqa: ARG002
        cfg = load_config()
        atlas_name = cfg["app"]["atlas_name"]
        atlas_key = cfg["app"]["atlas_key"]
        lut = pd.read_csv(get_path("atlas_lut_file"), sep="\t")

        # mri/report/label subdirs — see segment.py's comment (reverted
        # 2026-08-21 after a real smoke test showed the flat assumption
        # was wrong)
        cat_xml = workspace / "cat12" / "report" / "cat_T1w.xml"
        catroi_xml = workspace / "cat12" / "label" / "catROI_T1w.xml"

        features = extract_features(
            catroi_xml, cat_xml, atlas_name, atlas_key, lut, self.model_metrics
        )

        region_columns = region_columns_for(
            self.model_metrics, datasets_dir=self.datasets_dir, atlases=self.atlases
        )
        missing = [c for c in region_columns if c not in features]
        if missing:
            raise PipelineError(
                ErrorCode.FEATURE_SCHEMA_MISMATCH,
                f"{len(missing)} region column(s) missing from parsed features "
                f"(atlas mismatch with training?): {missing[:5]}",
            )

        out_dir = workspace / "features"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / "features.json"
        out_path.write_text(json.dumps(features))

        return StageResult(
            outputs={"features": str(out_path.relative_to(workspace))},
            metrics={"n_features": len(features)},
        )
