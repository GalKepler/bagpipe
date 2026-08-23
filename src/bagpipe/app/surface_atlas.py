"""Regional cortical thickness for a custom surface atlas, computed
directly from CAT12's own native-space output — bypasses CAT12's
`output.sROImenu.satlases.ownatlas` batch field, which was confirmed
(2026-08-23, docs/cat12_container_spec.md §4b) to NOT take effect in this
build: only the two natively-registered atlases (DK40/Destrieux) showed up
in `catROIs_*.xml`, even with `ownatlas` set.

Mirrors what CAT12's own `cat_surf_surf2roi` does internally for
non-pre-resampled input (nearest-vertex resampling onto the atlas' fixed
vertex grid via each mesh's spherical registration, no smoothing), just
run ourselves in Python against CAT12's real outputs:
  - `{lh,rh}.thickness.<name>`      native per-vertex thickness
  - `{lh,rh}.sphere.reg.<name>.gii` native mesh registered onto CAT12's
                                     fsaverage-space reference sphere
  - CAT12's own bundled reference sphere,
    `templates_surfaces/{lh,rh}.sphere.freesurfer.gii` — the same
    fsaverage space the atlas `.annot` and `sphere.reg` both live in.

Validated (2026-08-23) against CAT12's own DK40 output: this exact method,
run with CAT12's bundled DK40 `.annot` in place of a custom one, reproduces
`catROIs_*.xml`'s own DK40 regional thickness to within resampling noise
(see tests/test_surface_atlas.py's real-data comparison).
"""

from __future__ import annotations

from pathlib import Path

import nibabel as nib
import nibabel.freesurfer.io as fio
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree


def _unit_sphere(coords: np.ndarray) -> np.ndarray:
    return coords / np.linalg.norm(coords, axis=1, keepdims=True)


def resample_and_average(
    native_thickness: np.ndarray,
    native_sphere_coords: np.ndarray,
    atlas_sphere_coords: np.ndarray,
    atlas_labels: np.ndarray,
    atlas_names: list[str],
) -> pd.DataFrame:
    """Nearest-neighbor resamples `native_thickness` onto `atlas_sphere_coords`
    (matched via each point set's position on the unit sphere) then averages
    per atlas region. `atlas_labels[i]` is the row index into `atlas_names`
    for atlas vertex i; index 0 (background/medial wall in every FreeSurfer
    annot) and -1 (unlabeled) are dropped.
    """
    tree = cKDTree(_unit_sphere(native_sphere_coords))
    _, nearest = tree.query(_unit_sphere(atlas_sphere_coords))
    resampled = native_thickness[nearest]

    rows = [
        {
            "label": atlas_names[label_id],
            "thickness": float(resampled[atlas_labels == label_id].mean()),
        }
        for label_id in np.unique(atlas_labels)
        if label_id > 0
    ]
    return pd.DataFrame(rows)


def custom_surface_regional(
    lh_thickness_path: Path,
    rh_thickness_path: Path,
    lh_sphere_reg_path: Path,
    rh_sphere_reg_path: Path,
    lh_annot_path: Path,
    rh_annot_path: Path,
    lh_ref_sphere_path: Path,
    rh_ref_sphere_path: Path,
) -> pd.DataFrame:
    """Regional cortical thickness for a custom surface atlas — [label,
    thickness], one row per region across both hemispheres (region names
    are taken verbatim from the atlas .annot, not hemisphere-prefixed here;
    use an atlas whose own names already disambiguate hemisphere, as
    Schaefer2018's do).
    """
    rows = []
    for thickness_path, sphere_reg_path, annot_path, ref_sphere_path in (
        (lh_thickness_path, lh_sphere_reg_path, lh_annot_path, lh_ref_sphere_path),
        (rh_thickness_path, rh_sphere_reg_path, rh_annot_path, rh_ref_sphere_path),
    ):
        native_thickness = fio.read_morph_data(str(thickness_path))
        native_sphere = nib.load(str(sphere_reg_path)).darrays[0].data
        ref_sphere = nib.load(str(ref_sphere_path)).darrays[0].data
        labels, _, names = fio.read_annot(str(annot_path))
        names = [n.decode() if isinstance(n, bytes) else n for n in names]

        rows.append(
            resample_and_average(native_thickness, native_sphere, ref_sphere, labels, names)
        )
    return pd.concat(rows, ignore_index=True)
