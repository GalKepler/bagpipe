"""`bagpipe.app.region_names` against the committed `region_names.json`.

This reads the real generated file rather than a fixture: it is committed
atlas metadata (no subject data), and the point of these tests is that the
generator's output actually covers the atlas the production model reports on
— a fixture would pass while the shipped file was truncated.
"""

from __future__ import annotations

import pytest

from bagpipe.app import region_names as rn

ATLAS = rn.ATLAS_PREFIX


def test_every_atlas_region_has_a_readable_name():
    regions = rn.regions()
    assert len(regions) == 432  # Schaefer400 cortical + Tian S2 subcortical
    for label, meta in regions.items():
        assert meta["display"] and not meta["display"].startswith(("LH_", "RH_"))
        assert meta["short"]
        assert meta["hemisphere"] in {"L", "R"}
        assert meta["structure"] in {"cortex", "subcortex"}
        assert meta["network"] in rn.networks()
        assert label == meta["atlas_label"]


def test_display_names_are_unique():
    """Two regions sharing a display name would make the explorer and the
    report table ambiguous — the generator numbers duplicates for exactly
    this reason, so assert it worked."""
    displays = [meta["display"] for meta in rn.regions().values()]
    assert len(set(displays)) == len(displays)


def test_parse_column():
    assert rn.parse_column(f"{ATLAS}__LH_Vis_1__vol_gm") == ("LH_Vis_1", "vol_gm")
    assert rn.parse_column("TIV") is None
    assert rn.parse_column("SomeOtherAtlas__X__vol_gm") is None


def test_describe_skips_unknown_columns():
    scores = rn.describe(
        {
            f"{ATLAS}__LH_Vis_1__vol_gm": 1.5,
            f"{ATLAS}__NOT_A_REGION__vol_gm": 9.0,
            "TIV": 1_500_000.0,
        }
    )
    assert [s.label for s in scores] == ["LH_Vis_1"]
    assert scores[0].z == 1.5
    assert scores[0].metric_display == "Gray matter"


def test_top_deviations_ranks_by_absolute_z_within_one_metric():
    labels = list(rn.regions())[:4]
    zscores = {f"{ATLAS}__{labels[0]}__vol_gm": 0.2, f"{ATLAS}__{labels[1]}__vol_gm": -3.1}
    # A larger |z| on a different metric must not outrank the GM list.
    zscores[f"{ATLAS}__{labels[2]}__vol_csf"] = 9.9
    top = rn.top_deviations(rn.describe(zscores), n=2, metric="vol_gm")
    assert [s.label for s in top] == [labels[1], labels[0]]


def test_by_network_uses_canonical_order_and_reports_n():
    zscores = {
        f"{ATLAS}__{label}__vol_gm": 2.5 for label in rn.regions()
    }
    rows = rn.by_network(rn.describe(zscores))
    assert [r["network"] for r in rows] == [
        n for n in rn.networks() if any(r["network"] == n for r in rows)
    ]
    assert sum(r["n"] for r in rows) == 432
    assert all(r["mean_z"] == pytest.approx(2.5) for r in rows)
    assert all(r["n_beyond_2sd"] == r["n"] for r in rows)


def test_subcortical_names_expand_tian_abbreviations():
    regions = rn.regions()
    assert regions["aHIP-lh"]["display"] == "Left hippocampus (anterior)"
    assert regions["THA-VA-rh"]["display"] == "Right thalamus (ventroanterior)"
    assert regions["NAc-shell-lh"]["lobe"] == "Basal ganglia"
