"""Seed the `events` table from `config/events.yaml` (DESIGN.md §5). Dates
are public historical fact, not subject data, so they live in a checked-in
config rather than `config/local.yaml`."""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy.dialects.sqlite import insert

from bagpipe.db.base import get_engine, init_db
from bagpipe.db.models import Event

DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "events.yaml"


def ingest(config_path: Path | None = None) -> dict:
    config_path = config_path or DEFAULT_CONFIG
    rows = yaml.safe_load(Path(config_path).read_text())["events"]

    init_db()
    engine = get_engine()
    with engine.begin() as conn:
        for row in rows:
            stmt = insert(Event).values(**row)
            update_cols = {c: stmt.excluded[c] for c in row if c != "name"}
            stmt = stmt.on_conflict_do_update(index_elements=["name"], set_=update_cols)
            conn.execute(stmt)

    return {"rows_ingested": len(rows)}


if __name__ == "__main__":
    summary = ingest()
    print(f"Events ingest: {summary['rows_ingested']} rows")
