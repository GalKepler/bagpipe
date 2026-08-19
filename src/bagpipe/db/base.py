"""SQLAlchemy engine/session bound to the shared brainlink.db.

bagpipe adds its own tables (features, ...) to the same SQLite file brainlink
manages (participant, session, imaging_path, ...). We only ever create
bagpipe-owned tables here — never touch brainlink's schema.
"""

from __future__ import annotations

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from bagpipe.core.config import get_path


class Base(DeclarativeBase):
    metadata = MetaData()


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(f"sqlite:///{get_path('db_path')}")
    return _engine


def get_session() -> Session:
    return Session(get_engine())


def init_db() -> None:
    """Create bagpipe-owned tables that don't exist yet (checkfirst)."""
    import bagpipe.db.models  # noqa: F401  registers tables on Base.metadata

    Base.metadata.create_all(get_engine())
