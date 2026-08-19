"""Register T1w image paths (for DL training) into the shared DB.

Source: paths.cat12_images_dir (CAT12 native output, local disk — not the SMB
tabular_cat12 export). Only pixel-data *paths* are stored, never image content.

Registers two candidate volumes per session, both MNI-normalized:
  - mwp1: modulated warped GM density map
  - wm:   warped, bias-corrected T1 intensity image

S#### subjects go into brainlink's `imaging_path` (uid FKs to `participant`).
Legacy (non-S####) subjects go into bagpipe's own `legacy_imaging_path`,
since they have no `participant` row for that FK.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import MetaData, Table
from sqlalchemy.dialects.sqlite import insert

from bagpipe.core.config import get_path
from bagpipe.db.base import get_engine, init_db
from bagpipe.db.models import LegacyImagingPath

_SUB_RE = re.compile(r"sub-(S\d+|\d{12})$")
_SES_RE = re.compile(r"ses-(\S+)$")

_STREAMS = {
    "mwp1": "mwp1",  # modulated warped GM
    "wm": "wm",  # warped, bias-corrected T1
}

_INFIXES = ["_rec-norm_run-01_T1w.nii", "_T1w.nii"]


def _find_volumes(anat_dir: Path, sub: str, ses: str) -> list[tuple[Path, str]]:
    hits = []
    for prefix, stream in _STREAMS.items():
        for infix in _INFIXES:
            candidate = anat_dir / f"{prefix}sub-{sub}_ses-{ses}{infix}"
            if candidate.is_file():
                hits.append((candidate, stream))
                break
    return hits


def _collect(cat12_images_dir: Path) -> tuple[list[dict], list[dict]]:
    snbb_rows, legacy_rows = [], []
    for sub_dir in sorted(cat12_images_dir.glob("sub-*")):
        m = _SUB_RE.match(sub_dir.name)
        if not m:
            continue
        sub = m.group(1)
        is_snbb = sub.startswith("S")
        for ses_dir in sorted(sub_dir.glob("ses-*")):
            sm = _SES_RE.match(ses_dir.name)
            if not sm:
                continue
            ses = sm.group(1)
            anat_dir = ses_dir / "anat"
            if not anat_dir.is_dir():
                continue
            for path, stream in _find_volumes(anat_dir, sub, ses):
                base = {
                    "session_id": ses,
                    "modality": "anat",
                    "processing_stream": stream,
                    "filepath": str(path),
                    "filename": path.name,
                    "file_exists": True,
                    "file_size_bytes": path.stat().st_size,
                    "space": "MNI152",
                    "software": "CAT12",
                    "suffix": "T1w",
                    "extension": ".nii",
                }
                if is_snbb:
                    snbb_rows.append(
                        {**base, "uid": sub, "tier": "1", "pipeline": "cat12", "run": "01"}
                    )
                else:
                    legacy_rows.append({**base, "subject_id": sub, "pipeline": "cat12"})
    return snbb_rows, legacy_rows


def ingest(cat12_images_dir: Path | None = None) -> dict:
    cat12_images_dir = cat12_images_dir or get_path("cat12_images_dir")
    snbb_rows, legacy_rows = _collect(cat12_images_dir)

    init_db()
    engine = get_engine()
    imaging_path_tbl = Table("imaging_path", MetaData(), autoload_with=engine)

    with engine.begin() as conn:
        for i in range(0, len(snbb_rows), 500):
            chunk = snbb_rows[i : i + 500]
            stmt = insert(imaging_path_tbl).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["filepath"],
                set_={
                    "file_exists": stmt.excluded.file_exists,
                    "file_size_bytes": stmt.excluded.file_size_bytes,
                },
            )
            conn.execute(stmt)

        for i in range(0, len(legacy_rows), 500):
            chunk = legacy_rows[i : i + 500]
            stmt = insert(LegacyImagingPath).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["filepath"],
                set_={
                    "file_exists": stmt.excluded.file_exists,
                    "file_size_bytes": stmt.excluded.file_size_bytes,
                },
            )
            conn.execute(stmt)

    return {"snbb_rows": len(snbb_rows), "legacy_rows": len(legacy_rows)}


if __name__ == "__main__":
    summary = ingest()
    print(
        f"T1w image path ingest: {summary['snbb_rows']} SNBB rows, "
        f"{summary['legacy_rows']} legacy rows"
    )
