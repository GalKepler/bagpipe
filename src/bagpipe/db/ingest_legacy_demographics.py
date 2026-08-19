"""Ingest demographics for the pre-SNBB (non-S####) cohort from a local CSV.

Source CSV has PII (name, email, phone) — never copied into the repo, only
its path lives in config/local.yaml. Only non-PII columns are stored.
`ScanIdentifier` with underscores stripped matches the 12-digit legacy
subject id used in CAT12 folder names (e.g. "20010907_1247" -> "200109071247").
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.dialects.sqlite import insert

from bagpipe.core.config import get_path
from bagpipe.db.base import get_engine, init_db
from bagpipe.db.models import LegacyParticipant


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _parse_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def ingest(csv_path: Path | None = None) -> dict:
    csv_path = csv_path or get_path("legacy_demographics_csv")
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            subject_id = r["ScanIdentifier"].replace("_", "")
            if not subject_id.isdigit() or len(subject_id) != 12:
                continue
            rows.append(
                {
                    "subject_id": subject_id,
                    "lab": r.get("Lab") or None,
                    "gender": r.get("Gender") or None,
                    "age_at_scan": _parse_float(r.get("Age@Scan")),
                    "weight": _parse_float(r.get("Weight")),
                    "height": _parse_float(r.get("Height")),
                    "scan_date": _parse_date(r.get("ScanDate")),
                    "study": r.get("StudyName") or None,
                    "group_label": r.get("Group") or None,
                    "scan_tag": r.get("ScanTag") or None,
                    "subject_code": r.get("SubjectCode") or None,
                }
            )

    init_db()
    engine = get_engine()
    with engine.begin() as conn:
        for i in range(0, len(rows), 500):
            batch = rows[i : i + 500]
            stmt = insert(LegacyParticipant).values(batch)
            update_cols = {c: stmt.excluded[c] for c in batch[0] if c != "subject_id"}
            stmt = stmt.on_conflict_do_update(index_elements=["subject_id"], set_=update_cols)
            conn.execute(stmt)

    return {"rows_ingested": len(rows)}


if __name__ == "__main__":
    summary = ingest()
    print(f"Legacy demographics ingest: {summary['rows_ingested']} rows")
