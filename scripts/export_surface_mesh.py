"""One-off export of the CAT12 fsaverage 32k cortical surface to a web-ready glb.

Source: container/atlas/fsaverage32k/{lh,rh}.{central,mc}.freesurfer.gii
(32k geometry/curvature) + container/atlas/{lh,rh}.schaefer2018_400p_7n.annot
(164k Schaefer2018 400-parcel/7-network surface labels — the SAME atlas
`config/models/stacked.yaml` trains on and `volume-viewer.js` overlays,
per-vertex region ids resampled from 164k down to 32k via each mesh's own
reference sphere, nearest-neighbor on the unit sphere — the identical
technique `bagpipe.app.surface_atlas.resample_and_average` uses, just
label-nearest instead of value-averaged since these are categorical IDs).
Both source resolutions extracted from CAT12's own bundled spm25.ctf (see
that directory's provenance note). Region ids are the production volume
atlas's own ROIid (`container/atlas/schaefer2018n400n7tian2020s2.csv`),
1..400 (cortical only — the mesh has no subcortical geometry) — so a
{regionId: value} map built for volume-viewer.js's Schaefer overlay works
unmodified against this mesh too; no separate id space to reconcile.
Output: src/bagpipe/app/static/mesh/{cortex.glb,regions.json}.

Run once: `uv run python scripts/export_surface_mesh.py`. Re-run only if the
source surface/atlas files change.
"""

from __future__ import annotations

import csv
import json
import struct
from pathlib import Path

import nibabel as nib
import numpy as np
import trimesh
from fast_simplification import replay_simplification, simplify
from scipy.spatial import cKDTree

# fast_simplification: quadric-edge-collapse decimation, pure-Python
# bindings over a small C++ core (no MATLAB/VTK/PyMeshLab install), and
# its `return_collapses`/`replay_simplification` API is the only one of
# the lighter options that exposes a deterministic original->decimated
# vertex mapping — needed to carry curvature/region_id along, not just
# geometry.

CONTAINER_ATLAS_DIR = Path(__file__).resolve().parent.parent / "container" / "atlas"
ATLAS_32K_DIR = CONTAINER_ATLAS_DIR / "fsaverage32k"
OUT_DIR = Path(__file__).resolve().parent.parent / "src" / "bagpipe" / "app" / "static" / "mesh"
TARGET_TRIANGLES = 40_000


def _load_roi_name_to_id() -> dict[str, int]:
    """ROIname -> ROIid from the production Schaefer+Tian volume atlas's own
    label map — the single source of truth for region ids everywhere
    (features table, volume-viewer.js, this mesh).
    """
    csv_path = CONTAINER_ATLAS_DIR / "schaefer2018n400n7tian2020s2.csv"
    with csv_path.open() as f:
        return {row["ROIname"]: int(row["ROIid"]) for row in csv.DictReader(f, delimiter=";")}


def _unit_sphere(coords: np.ndarray) -> np.ndarray:
    return coords / np.linalg.norm(coords, axis=1, keepdims=True)


def load_hemisphere(hemi: str, roi_name_to_id: dict[str, int]) -> tuple:
    """Return (vertices, faces, curvature, region_ids) for one hemisphere,
    region_ids already in the production volume atlas's global ROIid space.
    """
    surf = nib.load(ATLAS_32K_DIR / f"{hemi}.central.freesurfer.gii")
    vertices = surf.darrays[0].data.astype(np.float64)
    faces = surf.darrays[1].data.astype(np.int64)

    curv = nib.load(ATLAS_32K_DIR / f"{hemi}.mc.freesurfer.gii").darrays[0].data.astype(np.float64)

    # Schaefer annot + its reference sphere are both 164k fsaverage; the
    # central surface above is 32k. Resample labels onto the 32k mesh via
    # nearest-neighbor on the unit sphere (each hemisphere's own sphere.reg
    # space, not 3D anatomical space).
    labels_164k, _ctab, names = nib.freesurfer.read_annot(
        CONTAINER_ATLAS_DIR / f"{hemi}.schaefer2018_400p_7n.annot"
    )
    names = [n.decode() if isinstance(n, bytes) else n for n in names]
    roi_ids_by_annot_index = np.array(
        [roi_name_to_id.get(n, 0) for n in names], dtype=np.int64
    )

    sphere_164k = nib.load(CONTAINER_ATLAS_DIR / f"{hemi}.sphere.freesurfer.gii").darrays[0].data
    sphere_32k = nib.load(ATLAS_32K_DIR / f"{hemi}.sphere.freesurfer.gii").darrays[0].data
    tree = cKDTree(_unit_sphere(sphere_164k.astype(np.float64)))
    _dist, nearest_164k = tree.query(_unit_sphere(sphere_32k.astype(np.float64)))

    region_ids = roi_ids_by_annot_index[labels_164k[nearest_164k]]

    return vertices, faces, curv, region_ids


def merge_hemispheres() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, int]]:
    roi_name_to_id = _load_roi_name_to_id()
    lh_v, lh_f, lh_c, lh_r = load_hemisphere("lh", roi_name_to_id)
    rh_v, rh_f, rh_c, rh_r = load_hemisphere("rh", roi_name_to_id)

    vertices = np.concatenate([lh_v, rh_v])
    faces = np.concatenate([lh_f, rh_f + len(lh_v)])
    curvature = np.concatenate([lh_c, rh_c])
    region_ids = np.concatenate([lh_r, rh_r])

    used_ids = set(region_ids.tolist()) - {0}
    region_abbr_to_id = {
        name.removeprefix("7Networks_"): rid
        for name, rid in roi_name_to_id.items()
        if rid in used_ids
    }
    return vertices, faces, curvature, region_ids, region_abbr_to_id


def decimate(vertices, faces, curvature, region_ids):
    n_faces = faces.shape[0]
    if n_faces <= TARGET_TRIANGLES:
        return vertices, faces, curvature, region_ids

    dec_points, dec_faces, collapses = simplify(
        vertices, faces, target_count=TARGET_TRIANGLES, return_collapses=True
    )
    _, _, indice_mapping = replay_simplification(vertices, faces, collapses)

    n_out = dec_points.shape[0]
    sums = np.zeros(n_out)
    counts = np.zeros(n_out)
    np.add.at(sums, indice_mapping, curvature)
    np.add.at(counts, indice_mapping, 1)
    dec_curvature = sums / np.maximum(counts, 1)

    # region id: deterministic "first original vertex wins" per decimated
    # vertex — cheap and boundary vertices are a tiny minority of the mesh.
    dec_region = np.zeros(n_out, dtype=region_ids.dtype)
    seen = np.zeros(n_out, dtype=bool)
    order = np.argsort(indice_mapping, kind="stable")
    for orig_idx in order:
        j = indice_mapping[orig_idx]
        if not seen[j]:
            dec_region[j] = region_ids[orig_idx]
            seen[j] = True

    return dec_points, dec_faces, dec_curvature, dec_region


def normalize_curvature(curvature: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(curvature, [1, 99])
    clipped = np.clip(curvature, lo, hi)
    return (clipped - lo) / (hi - lo)


def _append_attribute(glb: bytes, name: str, data: np.ndarray, component_type: int) -> bytes:
    """Append a plain (uncompressed) per-vertex accessor to a GLB's BIN chunk.

    dracox's KHR_draco_mesh_compression encoder only knows about
    position/normal/texcoord — any other vertex_attributes present on the
    mesh at export time get silently zeroed out (their accessor buffers are
    blindly stubbed to 4 zero bytes, see dracox._draco_encode). So curvature
    and region_id are exported as a *geometry-only* draco mesh, then spliced
    in here as ordinary uncompressed accessors sharing the same BIN buffer —
    which is what "separate binary attribute in the glb" asks for anyway.
    """
    magic, version, length = struct.unpack("<4sII", glb[:12])
    offset = 12
    json_chunk = bin_chunk = None
    while offset < length:
        chunk_len, chunk_type = struct.unpack("<I4s", glb[offset : offset + 8])
        chunk_data = glb[offset + 8 : offset + 8 + chunk_len]
        if chunk_type == b"JSON":
            json_chunk = json.loads(chunk_data.decode("utf-8"))
        elif chunk_type == b"BIN\x00":
            bin_chunk = bytearray(chunk_data)
        offset += 8 + chunk_len

    raw = data.astype(data.dtype.newbyteorder("<")).tobytes()
    raw += b"\x00" * (-len(raw) % 4)  # keep the buffer 4-byte aligned

    byte_offset = len(bin_chunk)
    bin_chunk.extend(raw)

    buffer_view_index = len(json_chunk["bufferViews"])
    json_chunk["bufferViews"].append(
        {"buffer": 0, "byteOffset": byte_offset, "byteLength": len(raw), "target": 34962}
    )
    accessor_index = len(json_chunk["accessors"])
    json_chunk["accessors"].append(
        {
            "bufferView": buffer_view_index,
            "componentType": component_type,
            "count": int(data.shape[0]),
            "type": "SCALAR",
        }
    )
    json_chunk["buffers"][0]["byteLength"] = len(bin_chunk)
    json_chunk["meshes"][0]["primitives"][0]["attributes"][name] = accessor_index

    json_bytes = json.dumps(json_chunk, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * (-len(json_bytes) % 4)
    bin_bytes = bytes(bin_chunk)
    bin_bytes += b"\x00" * (-len(bin_bytes) % 4)

    out = struct.pack("<4sII", magic, version, 0)
    out += struct.pack("<I4s", len(json_bytes), b"JSON") + json_bytes
    out += struct.pack("<I4s", len(bin_bytes), b"BIN\x00") + bin_bytes
    return out[:8] + struct.pack("<I", len(out)) + out[12:]


def build_glb(vertices, faces, curvature, region_ids) -> bytes:
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    scene = trimesh.Scene([mesh])
    glb = trimesh.exchange.gltf.export_glb(scene, extension_draco=True)
    glb = _append_attribute(glb, "_CURVATURE", curvature.astype(np.float32), component_type=5126)
    glb = _append_attribute(glb, "_REGION_ID", region_ids.astype(np.uint16), component_type=5123)
    return glb


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    vertices, faces, curvature, region_ids, region_name_to_id = merge_hemispheres()
    vertices, faces, curvature, region_ids = decimate(vertices, faces, curvature, region_ids)
    curvature = normalize_curvature(curvature)

    glb_bytes = build_glb(vertices, faces, curvature, region_ids)
    (OUT_DIR / "cortex.glb").write_bytes(glb_bytes)
    (OUT_DIR / "regions.json").write_text(json.dumps(region_name_to_id, indent=2) + "\n")

    size_kb = len(glb_bytes) / 1024
    print(f"cortex.glb: {faces.shape[0]} triangles, {vertices.shape[0]} vertices, {size_kb:.1f} KB")
    print(f"regions.json: {len(region_name_to_id)} regions")


if __name__ == "__main__":
    main()
