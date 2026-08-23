from pathlib import Path

from bagpipe.app.report import render_failure_html, render_success_html, write_pdf


def test_render_success_html_includes_bag_and_top_region():
    prediction = {
        "predicted_age": 42.3,
        "bag_corrected": 1.7,
        "regional_zscores": {"region_a": 0.1, "region_b": -3.2, "region_c": 1.0},
    }
    html = render_success_html(prediction, {"siqr_pct": 88.4, "siqr_grade": "B+"}, n_top_regions=2)
    assert "+1.7 years" in html
    assert "region_b" in html
    assert "region_a" not in html  # smallest |z| dropped by n_top_regions=2


def test_render_failure_html_includes_user_message():
    html = render_failure_html("Your scan's image quality was too low.")
    assert "too low" in html


def test_write_pdf_produces_valid_pdf(tmp_path: Path):
    out = write_pdf(render_failure_html("test"), tmp_path / "report.pdf")
    assert out.read_bytes().startswith(b"%PDF")
