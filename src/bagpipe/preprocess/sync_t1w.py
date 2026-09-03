"""Sync newly-arrived SNBB T1w sessions from the SMB BIDS source
(`paths.bids_root`, config/local.yaml) into the local BIDS mirror
(`cat12_cohort.yaml: bids_root`) that `bag preprocess cat12-cohort` scans.

Only the one best T1w file per session is copied (same selection as
`cat12_cohort._select_best_t1w`) — not the whole source tree — so a session
with multiple raw variants (defaced, multi-run) doesn't land duplicate/wrong
files locally. Idempotent: any session that already has a T1w file in the
local mirror (from this sync or the original historical copy) is skipped,
never re-copied or re-selected.

`bag preprocess sync-t1w --config config/cat12_cohort.yaml`
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from bagpipe.core.config import get_path
from bagpipe.preprocess.cat12_cohort import _resolve_bids_root, _select_best_t1w


def _session_anat_dirs(root: Path) -> list[Path]:
    return sorted({p.parent for p in root.glob("sub-*/ses-*/anat/sub-*_T1w.nii*")})


def run(config_path: str | Path) -> dict:
    config = yaml.safe_load(Path(config_path).read_text())
    source_root = get_path("bids_root")  # SMB, the real SNBB tree
    local_root = _resolve_bids_root(config)  # local mirror the cat12-cohort scan reads

    summary = {"sessions_scanned": 0, "copied": 0, "already_present": 0, "skipped_ambiguous": 0}

    for source_anat in _session_anat_dirs(source_root):
        summary["sessions_scanned"] += 1
        rel = source_anat.relative_to(source_root)  # sub-X/ses-Y/anat
        local_anat = local_root / rel

        if any(local_anat.glob("sub-*_T1w.nii*")):
            summary["already_present"] += 1
            continue

        files = sorted(source_anat.glob("sub-*_T1w.nii*"))
        best = _select_best_t1w(files, source_anat)
        if best is None:
            summary["skipped_ambiguous"] += 1
            continue

        local_anat.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best, local_anat / best.name)
        summary["copied"] += 1

    return summary
