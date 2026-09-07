"""`bagpipe.app.results_page` — the interactive report's HTML.

The interaction itself lives in `static/js/*` and isn't covered here; what
these tests hold is the server-rendered contract those scripts depend on
(the z-score JSON payload, the explorer's control hooks, the region-name
asset) plus the same no-raw-labels rule the PDF report has.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from bagpipe.app.region_names import ATLAS_PREFIX, regions
from bagpipe.app.results_page import render

LABELS = list(regions())


@pytest.fixture
def prediction() -> dict:
    zscores = {f"{ATLAS_PREFIX}__{label}__vol_gm": 0.3 for label in LABELS}
    zscores[f"{ATLAS_PREFIX}__{LABELS[9]}__vol_gm"] = -3.1
    return {
        "predicted_age": 46.3,
        "chronological_age": 43.9,
        "bag_corrected": 2.4,
        "regional_zscores": zscores,
        "age_band": {"label": "40-50", "n": 331, "mae_corrected": 6.1, "is_fallback": False},
        "population": {
            "n": 2260,
            "bag_sd": 5.2,
            "bag_percentile": 68.0,
            "bag_histogram": {"edges": [-4.0, -2.0, 0.0, 2.0, 4.0], "counts": [3, 12, 9, 2]},
            "calibration": [
                {"age_lo": 40.0, "age_hi": 45.0, "n": 90, "median": 44.0, "p10": 37.0,
                 "p90": 51.0},
                {"age_lo": 45.0, "age_hi": 50.0, "n": 80, "median": 47.0, "p10": 40.0,
                 "p90": 55.0},
            ],
        },
    }


@pytest.fixture
def qc() -> dict:
    return {"siqr_pct": 88.4, "siqr_grade": "B+"}


def test_page_has_every_section_and_its_nav_anchor(prediction, qc):
    html = render(prediction, qc, "job-1", volume_available=True)
    for slug in ("summary", "meaning", "cohort", "brain3d", "brainmap", "networks", "regions"):
        assert f'id="{slug}"' in html
        assert f'href="#{slug}"' in html


def test_zscores_are_embedded_verbatim_for_the_client_widgets(prediction, qc):
    """brainmap.js, the 3D panel and the explorer all read this one script
    tag; if it stops being valid JSON every interactive part goes dark."""
    html = render(prediction, qc, "job-1", volume_available=False)
    payload = re.search(
        r'<script id="regional-zscores" type="application/json">(.*?)</script>', html, re.S
    )
    assert payload
    assert json.loads(payload.group(1)) == prediction["regional_zscores"]


def test_page_loads_the_explorer_and_its_controls(prediction, qc):
    html = render(prediction, qc, "job-1", volume_available=False)
    assert "/static/js/region-explorer.js" in html
    for hook in (
        "data-region-explorer",
        "data-explorer-search",
        "data-explorer-group",
        "data-explorer-sort",
        "data-explorer-outliers",
        "data-explorer-metric",
        "data-explorer-list",
    ):
        assert hook in html


def test_summary_tiles_report_the_cohort_position(prediction, qc):
    html = render(prediction, qc, "job-1", volume_available=False)
    assert "68th" in html
    assert "percentile of 2,260 people" in html
    assert "88.4%" in html


def test_summary_tiles_degrade_without_a_chronological_age(prediction, qc):
    prediction["chronological_age"] = None
    prediction["population"]["bag_percentile"] = None
    html = render(prediction, qc, "job-1", volume_available=False)
    assert "not provided" in html
    assert "needs your age to place you" in html


def test_page_never_prints_a_raw_atlas_label(prediction, qc):
    """Labels still travel in the JSON payload (they are the join key the JS
    needs); what must not appear is a label rendered as visible text."""
    html = render(prediction, qc, "job-1", volume_available=False)
    body = re.sub(r'<script id="regional-zscores".*?</script>', "", html, flags=re.S)
    assert LABELS[9] not in body
    assert regions()[LABELS[9]]["display"] in body


def test_volume_unavailable_note_appears_only_when_the_t1_is_gone(prediction, qc):
    kept = render(prediction, qc, "job-1", volume_available=True)
    deleted = render(prediction, qc, "job-1", volume_available=False)
    assert "opted into data retention" not in kept
    assert "opted into data retention" in deleted
    assert 'data-volume-available="true"' in kept
    assert 'data-volume-available="false"' in deleted


def test_page_renders_without_a_population_block(prediction, qc):
    prediction.pop("population")
    html = render(prediction, qc, "job-1", volume_available=False)
    assert "Brain Age Gap: +2.4 years" in html


def test_brain_map_detail_never_renders_a_raw_atlas_label(prediction, qc):
    """The detail panel is built client-side from region_names.json, so the
    contract is enforced in `static/brainmap.js` rather than in this HTML —
    assert the template it uses carries no atlas label."""
    import bagpipe.app.results_page as results_page

    brainmap = (Path(results_page.__file__).parent / "static" / "brainmap.js").read_text()
    detail = brainmap[
        brainmap.index("function renderDetail") : brainmap.index("function initBrainmap")
    ]
    # `meta.label` is still the z-score lookup key inside this function; what
    # must not exist is the label interpolated into the rendered markup.
    assert "${meta.label}" not in detail, "detail panel must show anatomy, not the join key"
    assert "${named.lobe}" in detail
