"""Stage protocol, StageResult, and error taxonomy — DESIGN.md §Pillar 4,
docs/design_inference_pipeline.md § Stage interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from bagpipe.app.pipeline.models import Manifest


class ErrorCode(StrEnum):
    UNSUPPORTED_FORMAT = "unsupported_format"
    DICOM_CONVERSION_FAILED = "dicom_conversion_failed"
    NOT_T1W = "not_t1w"
    GEOMETRY_INVALID = "geometry_invalid"
    MULTIPLE_SERIES_AMBIGUOUS = "multiple_series_ambiguous"
    CAT12_FAILED = "cat12_failed"
    CAT12_TIMEOUT = "cat12_timeout"
    QC_BELOW_THRESHOLD = "qc_below_threshold"
    FEATURE_SCHEMA_MISMATCH = "feature_schema_mismatch"
    ROI_PARSE_FAILED = "roi_parse_failed"
    AGE_OUT_OF_RANGE = "age_out_of_range"
    MODEL_LOAD_FAILED = "model_load_failed"
    INTERNAL = "internal"


class PipelineError(Exception):
    def __init__(self, code: ErrorCode, message: str, user_message: str | None = None):
        self.code = code
        self.message = message
        self.user_message = user_message or "Something went wrong processing your scan."
        super().__init__(message)


@dataclass
class StageResult:
    outputs: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, float | int | str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class Stage(Protocol):
    name: str

    def run(self, workspace: Path, manifest: Manifest) -> StageResult:
        """Execute against the job workspace. Raise PipelineError on failure.

        May read manifest entries of earlier stages. Must not mutate the
        manifest directly; the runner records the StageResult.
        """
        ...
