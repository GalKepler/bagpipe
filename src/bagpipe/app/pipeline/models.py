"""Job manifest schema — docs/design_inference_pipeline.md § Job manifest schema."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class StageRecord(BaseModel):
    name: str
    status: str  # "succeeded" | "failed"
    started_at: datetime
    ended_at: datetime | None = None
    duration_s: float | None = None
    outputs: dict[str, str] = Field(default_factory=dict)
    metrics: dict[str, float | int | str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class JobInput(BaseModel):
    upload_format: str
    upload_sha256: str
    upload_size_bytes: int
    chronological_age: float | None = None
    sex: str
    retention_opt_in: bool = False


class Environment(BaseModel):
    bagpipe_version: str
    bagpipe_git_sha: str | None = None
    cat12_image: str | None = None
    cat12_version: str | None = None
    model_id: str
    model_sha256: str | None = None
    bias_correction_id: str = "cole"
    feature_schema_id: str


class ManifestError(BaseModel):
    stage: str
    code: str
    message: str
    user_message: str


class Manifest(BaseModel):
    schema_version: str = "1.0"
    job_id: str
    created_at: datetime
    status: str = "running"
    input: JobInput
    environment: Environment
    stages: list[StageRecord] = Field(default_factory=list)
    error: ManifestError | None = None
