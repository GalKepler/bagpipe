from pathlib import Path

import pytest

from bagpipe.app.region_names import ATLAS_PREFIX, regions
from bagpipe.app.report import render_failure_html, render_success_html, write_pdf

LABELS = list(regions())


def _column(label: str, metric: str = "vol_gm") -> str:
    return f"{ATLAS_PREFIX}__{label}__{metric}"


@pytest.fixture
def prediction() -> dict:
    """A minimal but realistic `prediction.json`: real atlas region columns
    (the report resolves them to anatomical names and silently drops anything
    it can't name), and the aggregate cohort block `predict` now writes."""
    zscores = {_column(label): 0.1 for label in LABELS[:40]}
    zscores[_column(LABELS[3])] = -3.2
    zscores[_column(LABELS[7])] = 2.6
    zscores[_column(LABELS[3], "vol_wm")] = 0.4
    return {
        "predicted_age": 42.3,
        "chronological_age": 40.6,
        "bag_corrected": 1.7,
        "regional_zscores": zscores,
        "age_band": {"label": "40-50", "n": 300, "mae_corrected": 6.1, "is_fallback": False},
        "population": {
            "n": 2260,
            "bag_sd": 5.2,
            "bag_percentile": 62.0,
            "bag_histogram": {"edges": [-3.0, -1.0, 1.0, 3.0], "counts": [4, 10, 6]},
            "calibration": [
                {"age_lo": 30.0, "age_hi": 35.0, "n": 50, "median": 34.0, "p10": 28.0,
                 "p90": 41.0},
                {"age_lo": 35.0, "age_hi": 40.0, "n": 60, "median": 38.0, "p10": 31.0,
                 "p90": 45.0},
            ],
        },
    }


def test_render_success_html_names_regions_anatomically(prediction):
    html = render_success_html(prediction, {"siqr_pct": 88.4, "siqr_grade": "B+"}, n_top_regions=2)
    assert "+1.7 years" in html
    top_display = regions()[LABELS[3]]["display"]
    assert top_display in html
    # The atlas label is a join key, not something a reader should ever see.
    assert LABELS[3] not in html
    # ...and the smallest-|z| regions are dropped by n_top_regions=2.
    assert regions()[LABELS[0]]["display"] not in html


def test_render_success_html_includes_the_new_sections(prediction):
    html = render_success_html(prediction, {"siqr_pct": 88.4, "siqr_grade": "B+"})
    for heading in ("Your result, explained", "Where you sit", "Network profile"):
        assert heading in html
    assert "62nd" in html  # cohort percentile tile
    assert "<svg" in html  # charts, not just tables


def test_render_success_html_survives_a_missing_population_block(prediction):
    """Older jobs' `prediction.json` predates `population` — the report must
    still render rather than 500 when someone opens an archived result."""
    prediction.pop("population")
    html = render_success_html(prediction, {})
    assert "+1.7 years" in html


def test_results_url_note_only_when_given(prediction):
    assert "interactive version" not in render_success_html(prediction, {})
    html = render_success_html(prediction, {}, results_url="https://example.org/jobs/x/view")
    assert "https://example.org/jobs/x/view" in html


def test_render_failure_html_includes_user_message():
    html = render_failure_html("Your scan's image quality was too low.")
    assert "too low" in html


def test_write_pdf_produces_valid_pdf(tmp_path: Path):
    out = write_pdf(render_failure_html("test"), tmp_path / "report.pdf")
    assert out.read_bytes().startswith(b"%PDF")


def test_write_pdf_of_a_full_report(tmp_path: Path, prediction):
    """The charts are inline SVG and WeasyPrint has to actually rasterise
    them — a malformed path or an unsupported attribute fails here, not in
    the HTML assertions above."""
    html = render_success_html(prediction, {"siqr_pct": 88.4, "siqr_grade": "B+"})
    out = write_pdf(html, tmp_path / "full.pdf")
    assert out.read_bytes().startswith(b"%PDF")
    assert out.stat().st_size > 10_000
