"""HTML/PDF report rendering — DESIGN.md §6 ("HTML report rendered to PDF
(WeasyPrint)"). One template, stdlib `string.Template` — no templating
dependency needed for a single static layout.
"""

from __future__ import annotations

import base64
from pathlib import Path
from string import Template

from weasyprint import HTML

from bagpipe.app.landing_page import CONTACT_EMAIL, gap_band_html

_LOGO_PATH = Path(__file__).parent / "static" / "logo-icon-96.png"
_LOGO_DATA_URI = "data:image/png;base64," + base64.b64encode(_LOGO_PATH.read_bytes()).decode()

# Light print palette (dark-ground wastes ink) but the same tokens-as-values
# and mono-for-numbers discipline as the on-screen pages (bagpipe.app.style)
# — a printed report and the web results page should read as one product.
_PAGE = Template("""
<html><head><meta charset="utf-8"><style>
body { font-family: 'Instrument Sans', 'Helvetica Neue', sans-serif; color: #14201D;
  margin: 2.5em; }
.brand { display: flex; align-items: center; gap: 0.5em; margin-bottom: 1em; }
.brand img { height: 1.8em; width: 1.8em; }
.brand span { font-weight: 500; font-size: 1.1em; }
h1 { font-size: 1.4em; font-weight: 400; }
h2 { font-size: 1.1em; font-weight: 400; }
table { border-collapse: collapse; width: 100%; margin-top: 1em; }
th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid #D8DBD3;
  font-family: 'Geist Mono', monospace; font-size: 0.9em; }
.big { font-size: 1.8em; font-weight: 400; font-family: 'Geist Mono', monospace; color: #14201D; }
.muted { color: #5C665F; font-size: 0.9em; }
.notice { margin-top: 1.5em; padding: 0.8em 1em; border: 1px solid #D8DBD3;
  border-radius: 4px; color: #5C665F; font-size: 0.85em; }
/* Gap band (docs/design-brief.md §6b) — same widget as the web results
   page's .gap-band, print-palette colors substituted for the dark-theme
   CSS vars gap_band_html()'s markup normally relies on. */
.gap-band { position: relative; width: 100%; max-width: 22em; height: 2.4em;
  margin-top: 0.6em; }
.gap-band__track { position: absolute; top: 1.1em; left: 0; right: 0; height: 1px;
  background: #D8DBD3; }
.gap-band__zero { position: absolute; top: 0.5em; left: 50%; width: 1px; height: 1.2em;
  background: #5C665F; }
.gap-band__interval { position: absolute; top: 0.95em; height: 5px; border-radius: 999px;
  background: #3FA89A; }
.gap-band--positive .gap-band__interval { background: #E0873A; }
.gap-band__point { position: absolute; top: 0.7em; width: 9px; height: 9px; border-radius: 50%;
  background: #14201D; transform: translateX(-50%); }
.gap-band__label { position: absolute; top: -0.3em; transform: translateX(-50%);
  font-family: 'Geist Mono', monospace; font-size: 0.85em; white-space: nowrap; }
.gap-band__zero-label { position: absolute; top: 1.6em; left: 50%; transform: translateX(-50%);
  font-family: 'Geist Mono', monospace; font-size: 0.7em; color: #5C665F; }
</style></head>
<body>
<div class="brand"><img src="$logo_uri"><span>Aevantis</span></div>
<h1>Brain Age Gap Report</h1>
<p class="big">$headline</p>
<p class="muted">$subline</p>
$body
<p class="notice">This report provides information about your brain and how
it compares to a reference cohort. It is a wellness and informational report
only, and is not intended to be used or relied on for any other purpose.
Questions — $contact_email.</p>
</body></html>
""")

_ZSCORE_ROW = Template("<tr><td>$region</td><td>$zscore</td></tr>")


def _accuracy_caveat_html(prediction: dict) -> str:
    """Plain-language accuracy caveat for the report reader — the model's
    error is strongly age-dependent (roughly triples from the youngest to
    the oldest band on its own held-out validation data), and the headline
    number above carries no uncertainty on its own. `age_band` is computed
    at request time from the production model's own `predictions` rows
    (see `bagpipe.app.pipeline.predict._band_mae`), never hardcoded.
    """
    band = prediction.get("age_band")
    if not band:
        return ""
    fallback_note = (
        " (too few validation subjects in your exact age band — showing the "
        "model's overall typical error instead)"
        if band.get("is_fallback")
        else ""
    )
    out_of_range_note = ""
    if prediction.get("age_out_of_range"):
        support = prediction.get("training_support", {})
        out_of_range_note = f"""
        <p class="muted"><strong>Note:</strong> your predicted age falls outside
        this model's usual reporting range. Most of the model's training data is
        between {support.get("p5", 0):.0f} and {support.get("p95", 0):.0f} years old
        (full range {support.get("min", 0):.0f}-{support.get("max", 0):.0f}) —
        treat this result with extra caution.</p>
        """
    return f"""
    <h2>How accurate is this?</h2>
    <p>For people around your predicted age ({band["label"]} years), this model's
    typical error is <strong>&plusmn;{band["mae_corrected"]:.1f} years</strong>{fallback_note},
    estimated from {band["n"]} people in the model's own validation data. Error is
    larger for older ages — this is a known limitation of the current model, not a
    problem with your specific scan.</p>
    {out_of_range_note}
    """


def render_success_html(prediction: dict, qc_metrics: dict, n_top_regions: int = 10) -> str:
    """`prediction` is `predict/prediction.json`'s dict; `qc_metrics` is the
    `qc_gate` stage's recorded metrics (SIQR score/grade, TIV, and the wider
    QC profile from `cat12_parse.parse_quality`).
    """
    zscores = prediction["regional_zscores"]
    top = sorted(zscores.items(), key=lambda kv: abs(kv[1]), reverse=True)[:n_top_regions]
    rows = "\n".join(_ZSCORE_ROW.substitute(region=region, zscore=f"{z:+.2f}") for region, z in top)
    band = prediction.get("age_band")
    band_cell = (
        f"<tr><th>Typical error for your age group</th>"
        f"<td>&plusmn;{band['mae_corrected']:.1f} years (n={band['n']})</td></tr>"
        if band
        else ""
    )
    band_mae = band["mae_corrected"] if band else 5.0
    body = f"""
    {gap_band_html(prediction["bag_corrected"], band_mae)}
    <table>
    <tr><th>Predicted brain age</th><td>{prediction["predicted_age"]:.1f} years</td></tr>
    <tr><th>Brain Age Gap (corrected)</th><td>{prediction["bag_corrected"]:+.1f} years</td></tr>
    {band_cell}
    <tr><th>Scan quality (SIQR)</th>
        <td>{qc_metrics.get("siqr_pct", "n/a")}% ({qc_metrics.get("siqr_grade", "n/a")})</td></tr>
    </table>
    {_accuracy_caveat_html(prediction)}
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
        contact_email=CONTACT_EMAIL,
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
        contact_email=CONTACT_EMAIL,
    )


def write_pdf(html: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html).write_pdf(out_path)
    return out_path
