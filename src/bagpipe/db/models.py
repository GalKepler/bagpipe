"""bagpipe-owned tables, added to the shared brainlink.db.

`uid`/`session_id` join to brainlink's `participant.uid`/`session.session_id`
when the subject was assigned an SNBB S###### ID. Legacy pre-SNBB CAT12
subjects (12-digit timestamp IDs, YYYYMMDDHHMM, never assigned S####) have
`uid=None` and carry their raw folder ID in `legacy_subject_id` instead — a
separate cohort, not joined into brainlink's identity tables. Their
demographics and image paths live in `LegacyParticipant`/`LegacyImagingPath`
below, since brainlink's `participant`/`imaging_path` FK to an SNBB uid.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from bagpipe.db.base import Base


class ModelRegistry(Base):
    """Versioned, promotable model artifacts (DESIGN.md §3.2/§4.3). Every BAG
    value traces back to a specific row here."""

    __tablename__ = "models_registry"

    model_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)  # e.g. "stacked"
    version: Mapped[str] = mapped_column(String)  # e.g. "v1"
    stage: Mapped[str] = mapped_column(String, default="none")  # none | production | archived
    config_json: Mapped[str] = mapped_column(String)
    metrics_json: Mapped[str] = mapped_column(String)
    artifact_path: Mapped[str] = mapped_column(String)
    mlflow_run_id: Mapped[str | None] = mapped_column(String)
    trained_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Prediction(Base):
    """Per-session BAG values, traceable to the `models_registry` row that
    produced them (DESIGN.md §3.2). One row per (model, session): re-running
    persist_predictions for the same model_id replaces its rows."""

    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint("model_id", "subject_key", "session_id", name="uq_prediction_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(Integer, index=True)
    subject_key: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str | None] = mapped_column(String, index=True)
    fold: Mapped[int] = mapped_column(Integer)
    age_true: Mapped[float] = mapped_column(Float)
    predicted_age_raw: Mapped[float] = mapped_column(Float)
    predicted_age_corrected: Mapped[float] = mapped_column(Float)
    bag_raw: Mapped[float] = mapped_column(Float)
    bag_corrected: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Event(Base):
    """Named date ranges driving Pillar 3 causal analyses (DESIGN.md §5): Oct 7
    war, COVID lockdown waves, judicial-reform period. `end_date` null means
    ongoing/ill-defined end (e.g. the war). Seeded from `config/events.yaml`
    via `bag ingest events` — dates are public historical fact, not subject
    data, so they're safe to hardcode in that config."""

    __tablename__ = "events"

    event_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    category: Mapped[str] = mapped_column(String)  # conflict | pandemic | political
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(String)


class Cat12Quality(Base):
    """Per-session CAT12 QC profile — SIQR/NCR/ICR/resolution/contrast,
    WMH burden, and CAT version provenance. Wide format (one row per
    session), not the long-format `Feature` table, since these are session-
    level QC facts rather than per-region metrics and `siqr_grade`/
    `cat_version` are strings, which `Feature.value: Float` can't hold.
    Front-facing use: Pillar 4 report/QC-gate diagnostics surfaced to the
    user; also queryable here for the training/legacy cohort ingested via
    `bag ingest cat12`. Keyed with `source` (e.g. "cat12" for the CAT12.9
    training-era export, "cat12_v26" for the CAT26 reprocessing cohort) so
    re-running the same subjects through a newer CAT version doesn't
    silently clobber the older QC row — both stay queryable side by side
    for version-drift comparison."""

    __tablename__ = "cat12_quality"
    __table_args__ = (
        UniqueConstraint("subject_key", "session_id", "source", name="uq_cat12_quality_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_key: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str | None] = mapped_column(String, index=True)
    source: Mapped[str] = mapped_column(String, default="cat12")
    siqr_pct: Mapped[float | None] = mapped_column(Float)
    siqr_grade: Mapped[str | None] = mapped_column(String)
    ncr: Mapped[float | None] = mapped_column(Float)
    icr: Mapped[float | None] = mapped_column(Float)
    res_rms_mm: Mapped[float | None] = mapped_column(Float)
    contrast: Mapped[float | None] = mapped_column(Float)
    gmv_tiv_pct: Mapped[float | None] = mapped_column(Float)
    vol_abs_wmh: Mapped[float | None] = mapped_column(Float)
    vol_rel_wmh: Mapped[float | None] = mapped_column(Float)
    cat_version: Mapped[str | None] = mapped_column(String)
    cat_revision: Mapped[str | None] = mapped_column(String)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Feature(Base):
    __tablename__ = "features"
    __table_args__ = (
        UniqueConstraint(
            "subject_key", "session_id", "source", "atlas", "region", "metric",
            name="uq_feature_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # uid or legacy_subject_id, whichever is set — NOT NULL so the unique
    # constraint actually dedups (SQLite treats each NULL as distinct).
    subject_key: Mapped[str] = mapped_column(String, index=True)
    # logical ref to brainlink's participant.uid — not a real FK, that table
    # isn't in this metadata, and create_all can't resolve cross-metadata FKs
    uid: Mapped[str | None] = mapped_column(String, index=True)
    legacy_subject_id: Mapped[str | None] = mapped_column(String, index=True)
    session_id: Mapped[str | None] = mapped_column(String, index=True)
    source: Mapped[str] = mapped_column(String)  # e.g. "cat12"
    # "" (not NULL) for global morphometry — SQLite treats every NULL as
    # distinct in a unique index, which would break dedup on re-ingest.
    atlas: Mapped[str] = mapped_column(String, default="")
    region: Mapped[str] = mapped_column(String)  # ROI label, or "global"
    metric: Mapped[str] = mapped_column(String)  # e.g. "vol_gm", "volume_ml"
    value: Mapped[float] = mapped_column(Float)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LegacyParticipant(Base):
    """Demographics for the pre-SNBB cohort. PII columns (name, contact info)
    from the source sheet are intentionally not carried over."""

    __tablename__ = "legacy_participant"

    subject_id: Mapped[str] = mapped_column(String, primary_key=True)  # 12-digit scan id
    lab: Mapped[str | None] = mapped_column(String)
    gender: Mapped[str | None] = mapped_column(String)
    age_at_scan: Mapped[float | None] = mapped_column(Float)
    weight: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)
    scan_date: Mapped[date | None] = mapped_column(Date)
    study: Mapped[str | None] = mapped_column(String)
    group_label: Mapped[str | None] = mapped_column(String)
    scan_tag: Mapped[str | None] = mapped_column(String)
    subject_code: Mapped[str | None] = mapped_column(String)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LegacyImagingPath(Base):
    """T1w image paths for the pre-SNBB cohort — mirrors brainlink's
    `imaging_path` shape, kept separate since that table's `uid` FKs to
    `participant`, which legacy subjects have no row in."""

    __tablename__ = "legacy_imaging_path"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    pipeline: Mapped[str] = mapped_column(String)
    modality: Mapped[str] = mapped_column(String)
    processing_stream: Mapped[str] = mapped_column(String)
    filepath: Mapped[str] = mapped_column(String, unique=True)
    filename: Mapped[str] = mapped_column(String)
    file_exists: Mapped[bool] = mapped_column(default=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    space: Mapped[str | None] = mapped_column(String)
    software: Mapped[str | None] = mapped_column(String)
    suffix: Mapped[str | None] = mapped_column(String)
    extension: Mapped[str | None] = mapped_column(String)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
