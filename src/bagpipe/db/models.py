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
