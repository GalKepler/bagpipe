"""HTML/PDF report rendering — DESIGN.md §6 ("HTML report rendered to PDF
(WeasyPrint)"). One template, stdlib `string.Template` — no templating
dependency needed for a single static layout.
"""

from __future__ import annotations

import base64
from pathlib import Path
from string import Template

from weasyprint import HTML

_LOGO_PATH = Path(__file__).parent / "static" / "logo-icon-96.png"
_LOGO_DATA_URI = "data:image/png;base64," + base64.b64encode(_LOGO_PATH.read_bytes()).decode()

_PAGE = Template("""
<html><head><meta charset="utf-8"><style>
body { font-family: sans-serif; color: #134E4A; margin: 2.5em; }
.brand { display: flex; align-items: center; gap: 0.5em; margin-bottom: 1em; }
.brand img { height: 1.8em; width: 1.8em; }
.brand span { font-weight: bold; font-size: 1.1em; }
h1 { font-size: 1.4em; }
table { border-collapse: collapse; width: 100%; margin-top: 1em; }
th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid #CCFBF1; }
.big { font-size: 1.8em; font-weight: bold; color: #0891B2; }
.muted { color: #4B7373; font-size: 0.9em; }
</style></head>
<body>
<div class="brand"><img src="$logo_uri"><span>Bagpipe</span></div>
<h1>Brain Age Gap Report</h1>
<p class="big">$headline</p>
<p class="muted">$subline</p>
$body
</body></html>
""")

_ZSCORE_ROW = Template("<tr><td>$region</td><td>$zscore</td></tr>")


def render_success_html(prediction: dict, qc_metrics: dict, n_top_regions: int = 10) -> str:
    """`prediction` is `predict/prediction.json`'s dict; `qc_metrics` is the
    `qc_gate` stage's recorded metrics (SIQR score/grade, TIV, and the wider
    QC profile from `cat12_parse.parse_quality`).
    """
    zscores = prediction["regional_zscores"]
    top = sorted(zscores.items(), key=lambda kv: abs(kv[1]), reverse=True)[:n_top_regions]
    rows = "\n".join(_ZSCORE_ROW.substitute(region=region, zscore=f"{z:+.2f}") for region, z in top)
    body = f"""
    <table>
    <tr><th>Predicted brain age</th><td>{prediction["predicted_age"]:.1f} years</td></tr>
    <tr><th>Brain Age Gap (corrected)</th><td>{prediction["bag_corrected"]:+.1f} years</td></tr>
    <tr><th>Scan quality (SIQR)</th>
        <td>{qc_metrics.get("siqr_pct", "n/a")}% ({qc_metrics.get("siqr_grade", "n/a")})</td></tr>
    </table>
    <h2>Regions with the largest deviation from population norms</h2>
    <table><tr><th>Region</th><th>z-score</th></tr>
    {rows}
    </table>
    """
    return _PAGE.substitute(
        logo_uri=_LOGO_DATA_URI,
        headline=f"Brain Age Gap: {prediction['bag_corrected']:+.1f} years",
        subline="Predicted vs. chronological age, adjusted for known model bias.",
        body=body,
    )


def render_failure_html(user_message: str) -> str:
    body = (
        f'<p>{user_message}</p><p class="muted">No further data was retained from this upload.</p>'
    )
    return _PAGE.substitute(
        logo_uri=_LOGO_DATA_URI,
        headline="We couldn't generate your report",
        subline="",
        body=body,
    )


def write_pdf(html: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html).write_pdf(out_path)
    return out_path
