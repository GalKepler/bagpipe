"""`bagpipe.app.charts` — the SVG figures shared by the PDF and the web page.

These are string-producing pure functions, so the tests assert the two things
that actually break in practice: that a figure degrades to "" instead of
raising when its data is missing or degenerate, and that values stay inside
the drawing area (an unclamped extreme z used to run its bar off the canvas).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from bagpipe.app import charts
from bagpipe.app.region_names import ATLAS_PREFIX, by_network, describe, regions, top_deviations

PALETTES = [charts.DARK, charts.PRINT]
LABELS = list(regions())


def _parse(svg: str) -> ET.Element:
    """Every figure must be well-formed XML — WeasyPrint silently drops an
    SVG it cannot parse, so a malformed one would just vanish from the PDF."""
    return ET.fromstring(svg)


def _scores(values: dict[str, float]):
    return describe({f"{ATLAS_PREFIX}__{label}__vol_gm": z for label, z in values.items()})


@pytest.fixture
def histogram() -> dict:
    return {"edges": [-4.0, -2.0, 0.0, 2.0, 4.0], "counts": [3, 12, 9, 2]}


@pytest.mark.parametrize("palette", PALETTES)
def test_bag_distribution_is_wellformed_and_marks_the_reader(histogram, palette):
    svg = charts.bag_distribution(histogram, 1.4, 62.0, palette)
    root = _parse(svg)
    assert root.tag.endswith("svg")
    assert "62nd percentile" in svg
    assert "+1.4 y" in svg


def test_bag_distribution_without_a_percentile_omits_it(histogram):
    svg = charts.bag_distribution(histogram, 1.4, None, charts.DARK)
    assert "percentile" not in svg


def test_bag_distribution_clamps_a_reader_outside_the_histogram(histogram):
    """An extreme gap must land on the edge of the axis, not off-canvas."""
    svg = charts.bag_distribution(histogram, 99.0, 100.0, charts.DARK)
    root = _parse(svg)
    width = float(root.get("viewBox").split()[2])
    xs = [
        float(value)
        for el in root.iter()
        for key, value in el.attrib.items()
        if key in {"x", "x1", "x2", "cx"} and re.fullmatch(r"-?\d+(\.\d+)?", value)
    ]
    assert xs and max(xs) <= width


def test_empty_inputs_render_nothing_rather_than_raising():
    assert charts.bag_distribution({"edges": [], "counts": []}, 0.0, None, charts.DARK) == ""
    assert charts.calibration([], None, 40.0, charts.DARK) == ""
    assert charts.network_profile([], charts.DARK) == ""
    assert charts.deviation_ranking([], charts.DARK) == ""
    assert charts.zscore_spread(_scores({LABELS[0]: 1.0}), charts.DARK) == ""


@pytest.mark.parametrize("palette", PALETTES)
def test_calibration_marks_the_reader_only_when_an_age_is_known(palette):
    bands = [
        {"age_lo": 20.0, "age_hi": 25.0, "n": 40, "median": 26.0, "p10": 20.0, "p90": 33.0},
        {"age_lo": 25.0, "age_hi": 30.0, "n": 40, "median": 30.0, "p10": 24.0, "p90": 37.0},
    ]
    assert ">you<" in charts.calibration(bands, 27.0, 29.0, palette)
    assert ">you<" not in charts.calibration(bands, None, 29.0, palette)


def test_network_profile_lists_every_network_with_its_mean():
    rows = by_network(_scores({label: 1.0 for label in LABELS}))
    svg = charts.network_profile(rows, charts.DARK)
    _parse(svg)
    for row in rows:
        assert row["display"] in svg


def test_deviation_ranking_respects_its_limit_and_uses_display_names():
    scores = top_deviations(_scores({label: (i % 7) - 3.0 for i, label in enumerate(LABELS)}), n=20)
    svg = charts.deviation_ranking(scores, charts.DARK, limit=3)
    _parse(svg)
    assert svg.count("<circle") == 3


def test_zscore_spread_reports_the_chance_baseline():
    scores = _scores({label: 0.0 for label in LABELS})
    svg = charts.zscore_spread(scores, charts.DARK)
    _parse(svg)
    assert f"0 of your {len(LABELS)} regions are beyond" in svg
    assert "~20 expected by chance" in svg


def test_ordinal_formats_percentiles():
    assert charts.ordinal(1) == "1st"
    assert charts.ordinal(2) == "2nd"
    assert charts.ordinal(3) == "3rd"
    assert charts.ordinal(11) == "11th"
    assert charts.ordinal(62.4) == "62nd"
    # A 0th or 100th percentile is not a thing a reader should be shown.
    assert charts.ordinal(0) == "1st"
    assert charts.ordinal(100) == "99th"


def test_region_display_names_are_escaped_into_the_svg():
    """Region names are generated data, but they reach the SVG as text — a
    stray `&` in a future atlas must not produce unparseable XML."""
    scores = top_deviations(_scores({LABELS[0]: 2.0}), n=1)
    hacked = [type(scores[0])(**{**scores[0].__dict__, "display": "A & B <tag>"})]
    _parse(charts.deviation_ranking(hacked, charts.DARK))
