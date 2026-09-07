"""Human-readable names for the production atlas's regions, plus the small
amount of grouping/aggregation every user-facing surface needs on top of a
raw `{region_column: z}` map.

The data itself is `static/atlas/region_names.json`, generated once by
`scripts/build_region_names.py` (cortical names derived by Schaefer x
Desikan-Killiany surface overlap, subcortical by Tian S2 abbreviation
expansion — see that script). This module is the read side: the PDF report
(`bagpipe.app.report`), the narrative generator (`bagpipe.app.narrative`)
and the results page all resolve names through here, and the browser fetches
the same JSON so nothing can drift between the printed and the interactive
report.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ATLAS_PREFIX = "Schaefer2018N400n7Tian2020S2"
REGION_NAMES_PATH = Path(__file__).parent / "static" / "atlas" / "region_names.json"

# The tissue metrics the production (volume-only) model reports on, in the
# order they're shown. Keyed by the `metric` component of a region column
# (`<atlas>__<label>__<metric>`, per bagpipe.models.tabular).
METRIC_LABELS = {
    "vol_gm": "Gray matter",
    "vol_wm": "White matter",
    "vol_csf": "CSF",
    "thickness": "Cortical thickness",
    "gyrification": "Gyrification",
    "sulcal_depth": "Sulcal depth",
    "fractal_dimension": "Fractal dimension",
    "area": "Surface area",
}


@dataclass(frozen=True)
class RegionScore:
    """One (region, metric) z-score with everything needed to display it."""

    label: str  # atlas join key, e.g. "LH_Vis_1"
    metric: str  # e.g. "vol_gm"
    z: float
    display: str  # "Left fusiform gyrus 1"
    short: str  # "Fusiform gyrus 1"
    network: str  # "Vis" / "subcortex"
    network_display: str  # "Visual"
    lobe: str
    hemisphere: str  # "L" / "R"
    structure: str  # "cortex" / "subcortex"
    index: int  # atlas ROIid
    coverage: float  # anatomical-name confidence, 1.0 for subcortex

    @property
    def metric_display(self) -> str:
        return METRIC_LABELS.get(self.metric, self.metric)


@lru_cache(maxsize=1)
def load() -> dict:
    """The whole `region_names.json` payload (`regions` + `networks`)."""
    return json.loads(REGION_NAMES_PATH.read_text())


def regions() -> dict[str, dict]:
    return load()["regions"]


def networks() -> dict[str, dict]:
    return load()["networks"]


def network_display(network: str) -> str:
    return networks().get(network, {}).get("display", network)


def parse_column(column: str) -> tuple[str, str] | None:
    """`"<atlas>__<label>__<metric>"` -> `(label, metric)`, or None if the
    column isn't a per-region column of the production atlas (globals such as
    TIV, or a future second atlas, land here and are skipped rather than
    mangled into a fake region name)."""
    parts = column.split("__")
    if len(parts) != 3 or parts[0] != ATLAS_PREFIX:
        return None
    return parts[1], parts[2]


def describe(zscores: dict[str, float]) -> list[RegionScore]:
    """Resolve a raw `{region_column: z}` map (as written by
    `bagpipe.app.normative.regional_zscores`) into displayable rows, dropping
    anything with no name — an unnamed region is a bug in the atlas export,
    not something to show a user as a raw label.
    """
    known = regions()
    out: list[RegionScore] = []
    for column, z in zscores.items():
        parsed = parse_column(column)
        if parsed is None:
            continue
        label, metric = parsed
        meta = known.get(label)
        if meta is None:
            continue
        out.append(
            RegionScore(
                label=label,
                metric=metric,
                z=float(z),
                display=meta["display"],
                short=meta["short"],
                network=meta["network"],
                network_display=network_display(meta["network"]),
                lobe=meta["lobe"],
                hemisphere=meta["hemisphere"],
                structure=meta["structure"],
                index=meta["index"],
                coverage=meta["coverage"],
            )
        )
    return out


def top_deviations(
    scores: list[RegionScore], n: int = 8, metric: str | None = "vol_gm"
) -> list[RegionScore]:
    """The `n` largest-|z| regions, most extreme first. Restricted to one
    metric by default: a mixed GM/WM/CSF top-N is dominated by whichever
    tissue happens to be noisiest and reads as a longer, less meaningful
    list than one tissue's honest extremes.
    """
    pool = [s for s in scores if metric is None or s.metric == metric]
    return sorted(pool, key=lambda s: abs(s.z), reverse=True)[:n]


def by_network(scores: list[RegionScore], metric: str = "vol_gm") -> list[dict]:
    """Per-network mean z for one metric, ordered by the canonical network
    order in `region_names.json` (so the chart's bar order is stable across
    reports rather than sorted by whatever this person's values happen to be).

    The mean of ~57 parcels' z-scores is a much tighter quantity than a single
    parcel's, so `n` rides along for the UI to show — a network mean of +0.4
    across 57 regions is a far stronger signal than one region at +0.4, and
    the report should never let those look alike.
    """
    order = list(networks())
    buckets: dict[str, list[float]] = {}
    for score in scores:
        if score.metric != metric:
            continue
        buckets.setdefault(score.network, []).append(score.z)

    out = []
    for network in order:
        values = buckets.get(network)
        if not values:
            continue
        out.append(
            {
                "network": network,
                "display": network_display(network),
                "blurb": networks()[network].get("blurb", ""),
                "mean_z": sum(values) / len(values),
                "n": len(values),
                "n_beyond_2sd": sum(1 for v in values if abs(v) >= 2),
            }
        )
    return out
