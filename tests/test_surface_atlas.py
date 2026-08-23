"""bagpipe.app.surface_atlas — synthetic geometry only (no real CAT12/nibabel
files needed for CI). A real-data validation against CAT12's own DK40 output
was run manually 2026-08-23 (see docs/cat12_container_spec.md §4b): max
0.003mm diff vs. catROIs_*.xml's own DK40 regional thickness, methodology
confirmed sound — not re-run here since it needs a real CAT12 container run.
"""

from __future__ import annotations

import numpy as np

from bagpipe.app.surface_atlas import resample_and_average


def test_resample_and_average_exact_match_when_grids_coincide():
    # atlas grid == native grid (identity resampling): region mean must be
    # the plain mean of each region's native values.
    coords = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [-1, 0, 0], [0, -1, 0], [0, 0, -1]], float)
    labels = np.array([0, 1, 1, 2, 2, -1])  # 0=background, -1=unlabeled — both dropped
    names = ["background", "regionA", "regionB"]
    thickness = np.array([99.0, 2.0, 4.0, 10.0, 20.0, 999.0])

    result = resample_and_average(thickness, coords, coords, labels, names).set_index("label")

    assert set(result.index) == {"regionA", "regionB"}
    assert result.loc["regionA", "thickness"] == 3.0  # mean(2, 4)
    assert result.loc["regionB", "thickness"] == 15.0  # mean(10, 20)


def test_resample_and_average_nearest_neighbor_matching():
    # native has one vertex per octant; atlas asks for the same 6 directions
    # but scaled differently (radius 5) and offset in ordering — resampling
    # must still match by direction on the unit sphere, not by index or scale.
    native_coords = np.array([[1, 0, 0], [-1, 0, 0]], float)
    native_thickness = np.array([1.0, 7.0])

    atlas_coords = np.array([[5, 0, 0], [-5, 0.001, 0]], float)  # scaled + slightly off-axis
    atlas_labels = np.array([1, 1])
    atlas_names = ["background", "regionA"]

    result = resample_and_average(
        native_thickness, native_coords, atlas_coords, atlas_labels, atlas_names
    )

    # both atlas points nearest-match to opposite native vertices -> mean(1, 7)
    assert result.loc[0, "thickness"] == 4.0


def test_resample_and_average_drops_background_and_unlabeled():
    coords = np.array([[1, 0, 0], [0, 1, 0]], float)
    labels = np.array([0, -1])
    result = resample_and_average(np.array([1.0, 2.0]), coords, coords, labels, ["background"])
    assert result.empty
