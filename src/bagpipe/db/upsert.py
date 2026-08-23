"""Shared batched upsert helpers — used by every ingest_* module writing
into `Feature`/`Cat12Quality` so the conflict-key/batch-size logic lives
in one place instead of copy-pasted per source."""

from __future__ import annotations

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import DeclarativeBase

_BATCH_SIZE = 500


def upsert_rows(
    conn, model: type[DeclarativeBase], rows: list[dict], conflict_cols: list[str]
) -> None:
    """Batched INSERT ... ON CONFLICT DO UPDATE. `rows` must have identical
    keys across all dicts (SQLAlchemy Core requires uniform columns per
    `insert().values(list)` call) — pad missing fields with `None` first."""
    if not rows:
        return
    update_cols = [c for c in rows[0] if c not in conflict_cols]
    for i in range(0, len(rows), _BATCH_SIZE):
        batch = rows[i : i + _BATCH_SIZE]
        stmt = insert(model).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=conflict_cols,
            set_={c: getattr(stmt.excluded, c) for c in update_cols},
        )
        conn.execute(stmt)
