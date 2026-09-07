"""One-off export of human-readable names for every region the production
atlas (Schaefer2018 400p/7-network + Tian S2 subcortex) reports on.

The problem this solves: the atlas's own labels are `LH_Vis_23`, `pGP-lh` —
fine as join keys, meaningless to a person reading their own brain report.
Every user-facing surface (`bagpipe.app.report`, `results_page`, the brain
map and the region explorer) needs an anatomical name instead.

Cortex: the readable name is *derived*, not hand-written. Both
`container/atlas/{lh,rh}.schaefer2018_400p_7n.annot` and
`container/atlas/{lh,rh}.aparc_DK40.freesurfer.annot` are per-vertex
labelings of the SAME 164k fsaverage surface, so each Schaefer parcel's
anatomical name is just the modal Desikan-Killiany label over its vertices,
with the overlap fraction kept alongside it so the UI can be honest when a
parcel straddles two gyri. Same source files `scripts/export_surface_mesh.py`
already uses; no new inputs, no network access, no hand-curated 400-row table
to drift out of sync with the atlas.

Subcortex: Tian S2's 32 labels are a small documented abbreviation scheme
(`aHIP` = anterior hippocampus, `THA-VA` = ventroanterior thalamus, ...),
expanded from the table below — there is no second labeling to derive them
from, and 32 rows is small enough to state explicitly.

Output: `src/bagpipe/app/static/atlas/region_names.json`, committed and read
at runtime by `bagpipe.app.region_names` (server side) and fetched by
`static/js/*` (browser side). No nibabel at runtime.

Run once: `uv run python scripts/build_region_names.py`. Re-run only if the
atlas files change.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import nibabel as nib
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CONTAINER_ATLAS_DIR = ROOT / "container" / "atlas"
OUT_PATH = ROOT / "src" / "bagpipe" / "app" / "static" / "atlas" / "region_names.json"

# Yeo-7 networks. `blurb` is deliberately function-descriptive and hedged —
# this is a wellness report (docs/design-brief.md §1/§10), so it says what a
# network is *involved in*, never what a deviation there would mean.
NETWORKS = {
    "Vis": {
        "display": "Visual",
        "blurb": "Areas that process what you see, from basic edges and motion "
        "to recognising objects and faces.",
    },
    "SomMot": {
        "display": "Somatomotor",
        "blurb": "Areas that handle touch, body position, and the planning and "
        "execution of movement.",
    },
    "DorsAttn": {
        "display": "Dorsal attention",
        "blurb": "Areas involved in deliberately directing attention — searching a "
        "scene, tracking a moving target.",
    },
    "SalVentAttn": {
        "display": "Salience / ventral attention",
        "blurb": "Areas that flag what is worth noticing and switch attention when "
        "something unexpected happens.",
    },
    "Limbic": {
        "display": "Limbic",
        "blurb": "Areas closely tied to emotion, motivation, smell, and memory for "
        "personal events.",
    },
    "Cont": {
        "display": "Frontoparietal control",
        "blurb": "Areas involved in holding a goal in mind, planning, and flexibly "
        "switching between tasks.",
    },
    "Default": {
        "display": "Default mode",
        "blurb": "Areas most active during inward-directed thought — remembering, "
        "imagining, thinking about other people.",
    },
    "subcortex": {
        "display": "Subcortex",
        "blurb": "Structures beneath the cortex involved in memory, emotion, reward, "
        "and relaying signals to and from the cortex.",
    },
}

# Desikan-Killiany label -> (readable name, lobe). The 34 cortical DK labels
# plus the two non-cortical entries the annot carries, which never become a
# region's name (see `_modal_dk`).
DK_NAMES = {
    "bankssts": ("Banks of the superior temporal sulcus", "Temporal"),
    "caudalanteriorcingulate": ("Caudal anterior cingulate", "Cingulate"),
    "caudalmiddlefrontal": ("Caudal middle frontal", "Frontal"),
    "cuneus": ("Cuneus", "Occipital"),
    "entorhinal": ("Entorhinal cortex", "Temporal"),
    "fusiform": ("Fusiform gyrus", "Temporal"),
    "inferiorparietal": ("Inferior parietal", "Parietal"),
    "inferiortemporal": ("Inferior temporal", "Temporal"),
    "isthmuscingulate": ("Isthmus of the cingulate", "Cingulate"),
    "lateraloccipital": ("Lateral occipital", "Occipital"),
    "lateralorbitofrontal": ("Lateral orbitofrontal", "Frontal"),
    "lingual": ("Lingual gyrus", "Occipital"),
    "medialorbitofrontal": ("Medial orbitofrontal", "Frontal"),
    "middletemporal": ("Middle temporal", "Temporal"),
    "parahippocampal": ("Parahippocampal gyrus", "Temporal"),
    "paracentral": ("Paracentral lobule", "Frontal"),
    "parsopercularis": ("Pars opercularis", "Frontal"),
    "parsorbitalis": ("Pars orbitalis", "Frontal"),
    "parstriangularis": ("Pars triangularis", "Frontal"),
    "pericalcarine": ("Pericalcarine cortex", "Occipital"),
    "postcentral": ("Postcentral gyrus", "Parietal"),
    "posteriorcingulate": ("Posterior cingulate", "Cingulate"),
    "precentral": ("Precentral gyrus", "Frontal"),
    "precuneus": ("Precuneus", "Parietal"),
    "rostralanteriorcingulate": ("Rostral anterior cingulate", "Cingulate"),
    "rostralmiddlefrontal": ("Rostral middle frontal", "Frontal"),
    "superiorfrontal": ("Superior frontal", "Frontal"),
    "superiorparietal": ("Superior parietal", "Parietal"),
    "superiortemporal": ("Superior temporal", "Temporal"),
    "supramarginal": ("Supramarginal gyrus", "Parietal"),
    "frontalpole": ("Frontal pole", "Frontal"),
    "temporalpole": ("Temporal pole", "Temporal"),
    "transversetemporal": ("Transverse temporal", "Temporal"),
    "insula": ("Insula", "Insula"),
}

# Labels in the DK annot that are not cortical parcels — a Schaefer parcel
# never takes its name from one of these.
DK_NON_CORTICAL = {"unknown", "corpuscallosum"}

# Tian S2 subcortex: `<prefix><STRUCTURE>-<hemi>`. Split into the structure
# and the subdivision prefix/suffix so the two compose into one phrase.
TIAN_STRUCTURES = {
    "HIP": ("Hippocampus", "Medial temporal"),
    "AMY": ("Amygdala", "Medial temporal"),
    "THA": ("Thalamus", "Diencephalon"),
    "NAc": ("Nucleus accumbens", "Basal ganglia"),
    "GP": ("Globus pallidus", "Basal ganglia"),
    "PUT": ("Putamen", "Basal ganglia"),
    "CAU": ("Caudate nucleus", "Basal ganglia"),
}
TIAN_SUBDIVISIONS = {
    "a": "anterior",
    "p": "posterior",
    "l": "lateral",
    "m": "medial",
    "DP": "dorsoposterior",
    "VP": "ventroposterior",
    "VA": "ventroanterior",
    "DA": "dorsoanterior",
    "shell": "shell",
    "core": "core",
}

HEMI_WORD = {"L": "Left", "R": "Right"}

# A parcel whose modal DK label covers less than this fraction of its
# vertices gets a two-gyrus name ("Superior frontal / precentral") rather
# than a confidently wrong single one.
STRADDLE_THRESHOLD = 0.60


def _load_atlas_csv() -> list[dict[str, str]]:
    """The production volume atlas's own label map — the single source of
    truth for region ids/abbreviations everywhere (same file
    `scripts/export_surface_mesh.py` reads)."""
    path = CONTAINER_ATLAS_DIR / "schaefer2018n400n7tian2020s2.csv"
    with path.open() as f:
        return list(csv.DictReader(f, delimiter=";"))


def _modal_dk(hemi: str) -> dict[str, tuple[list[str], float]]:
    """Schaefer parcel label -> (DK labels ordered by overlap, modal coverage).

    Both annots label the same 164k fsaverage vertices, so this is a plain
    per-parcel vote. Non-cortical DK labels (medial wall, corpus callosum)
    are dropped from the vote rather than allowed to win it — a parcel
    bordering the medial wall is still a real cortical parcel.
    """
    prefix = "lh" if hemi == "L" else "rh"
    sch_labels, _, sch_names = nib.freesurfer.read_annot(
        CONTAINER_ATLAS_DIR / f"{prefix}.schaefer2018_400p_7n.annot"
    )
    dk_labels, _, dk_names = nib.freesurfer.read_annot(
        CONTAINER_ATLAS_DIR / f"{prefix}.aparc_DK40.freesurfer.annot"
    )
    if sch_labels.shape != dk_labels.shape:
        raise SystemExit(
            f"{prefix}: Schaefer ({sch_labels.shape}) and DK40 ({dk_labels.shape}) annots "
            "are not on the same surface — cannot derive anatomical names by overlap"
        )

    sch_names = [n.decode() for n in sch_names]
    dk_names = [n.decode() for n in dk_names]

    out: dict[str, tuple[list[str], float]] = {}
    for sch_index, sch_name in enumerate(sch_names):
        if not sch_name.startswith("7Networks_"):
            continue  # medial wall / background
        mask = sch_labels == sch_index
        if not mask.any():
            continue
        votes = Counter(
            dk_names[i] for i in dk_labels[mask] if dk_names[i] not in DK_NON_CORTICAL
        )
        if not votes:
            continue
        total = sum(votes.values())
        ranked = [name for name, _ in votes.most_common()]
        coverage = votes[ranked[0]] / total
        # `label` in the manifests/z-score keys is the ROIabbr (`LH_Vis_1`),
        # i.e. the annot name minus its `7Networks_` prefix.
        out[sch_name.removeprefix("7Networks_")] = (ranked, float(coverage))
    return out


def _cortical_entries() -> dict[str, dict]:
    overlap = {**_modal_dk("L"), **_modal_dk("R")}
    entries: dict[str, dict] = {}

    for row in _load_atlas_csv():
        label = row["ROIabbr"]
        if label not in overlap:
            continue
        hemi = "L" if label.startswith("LH_") else "R"
        network = label.split("_")[1]
        ranked, coverage = overlap[label]

        primary, lobe = DK_NAMES[ranked[0]]
        if coverage < STRADDLE_THRESHOLD and len(ranked) > 1:
            secondary = DK_NAMES[ranked[1]][0]
            anatomy = f"{primary} / {secondary.lower()}"
        else:
            anatomy = primary

        entries[label] = {
            "index": int(row["ROIid"]),
            "structure": "cortex",
            "hemisphere": hemi,
            "network": network,
            "lobe": lobe,
            "anatomy": anatomy,
            "coverage": round(coverage, 3),
            "atlas_label": label,
        }

    _number_duplicates(entries)
    return entries


def _number_duplicates(entries: dict[str, dict]) -> None:
    """Several Schaefer parcels land in the same DK gyrus, so the anatomical
    name alone is ambiguous — number them within (hemisphere, anatomy) in
    atlas order. A gyrus covered by exactly one parcel keeps a bare name.
    """
    groups: dict[tuple[str, str], list[str]] = {}
    for label, entry in sorted(entries.items(), key=lambda kv: kv[1]["index"]):
        groups.setdefault((entry["hemisphere"], entry["anatomy"]), []).append(label)

    for (hemi, anatomy), labels in groups.items():
        for ordinal, label in enumerate(labels, start=1):
            entry = entries[label]
            suffix = f" {ordinal}" if len(labels) > 1 else ""
            entry["short"] = f"{anatomy}{suffix}"
            entry["display"] = f"{HEMI_WORD[hemi]} {anatomy.lower()}{suffix}"
            entry["parcel_of"] = len(labels)


def _subcortical_entries() -> dict[str, dict]:
    entries: dict[str, dict] = {}
    for row in _load_atlas_csv():
        label = row["ROIabbr"]
        if "-lh" not in label and "-rh" not in label:
            continue
        body, hemi_tag = label.rsplit("-", 1)
        hemi = "L" if hemi_tag == "lh" else "R"

        if "-" in body:  # THA-DP, NAc-shell
            structure_key, sub_key = body.split("-", 1)
        else:  # aHIP, pGP
            structure_key, sub_key = body[1:], body[0]

        structure, group = TIAN_STRUCTURES[structure_key]
        subdivision = TIAN_SUBDIVISIONS[sub_key]
        anatomy = f"{structure} ({subdivision})"

        entries[label] = {
            "index": int(row["ROIid"]),
            "structure": "subcortex",
            "hemisphere": hemi,
            "network": "subcortex",
            "lobe": group,
            "anatomy": anatomy,
            "coverage": 1.0,
            "atlas_label": label,
            "short": anatomy,
            "display": f"{HEMI_WORD[hemi]} {structure.lower()} ({subdivision})",
            "parcel_of": 1,
        }
    return entries


def main() -> None:
    regions = {**_cortical_entries(), **_subcortical_entries()}
    expected = len(_load_atlas_csv())
    if len(regions) != expected:
        raise SystemExit(f"named {len(regions)} regions but the atlas has {expected}")

    payload = {
        "version": 1,
        "source": (
            "cortex: modal Desikan-Killiany (aparc_DK40) label per Schaefer2018 "
            "400p/7-network parcel, both on the 164k fsaverage surface; "
            "subcortex: Tian2020 S2 abbreviation expansion. "
            "Generated by scripts/build_region_names.py — do not hand-edit."
        ),
        "networks": NETWORKS,
        "regions": dict(sorted(regions.items(), key=lambda kv: kv[1]["index"])),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=1, sort_keys=False) + "\n")

    straddling = sum(1 for r in regions.values() if r["coverage"] < STRADDLE_THRESHOLD)
    print(f"wrote {OUT_PATH.relative_to(ROOT)}: {len(regions)} regions")
    print(
        f"  cortical parcels with a straddling (<{STRADDLE_THRESHOLD:.0%}) modal DK label: "
        f"{straddling}"
    )
    coverages = np.array([r["coverage"] for r in regions.values() if r["structure"] == "cortex"])
    print(f"  median DK overlap: {np.median(coverages):.2f}")


if __name__ == "__main__":
    main()
