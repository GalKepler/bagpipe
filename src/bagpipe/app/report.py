"""HTML/PDF report rendering — DESIGN.md §6 ("HTML report rendered to PDF
(WeasyPrint)"). One template, stdlib `string.Template` — no templating
dependency needed for a single static layout.

The printed report is the same report as the web page, not a stripped-down
receipt for it: the figures come from `bagpipe.app.charts` and the prose from
`bagpipe.app.narrative`, both shared with `bagpipe.app.results_page`, and
regions are named anatomically (`bagpipe.app.region_names`). What the page
has and this cannot is interaction — the brain viewers and the region
explorer — so the PDF closes with the ranked deviation figure and a table of
the same regions rather than pretending to be navigable.
"""

from __future__ import annotations

import base64
import math
from pathlib import Path
from string import Template

from weasyprint import HTML

from bagpipe.app import charts, region_names
from bagpipe.app import narrative as narrative_mod
from bagpipe.app.landing_page import CONTACT_EMAIL, gap_band_html

_LOGO_PATH = Path(__file__).parent / "static" / "logo-icon-96.png"
_LOGO_DATA_URI = "data:image/png;base64," + base64.b64encode(_LOGO_PATH.read_bytes()).decode()

_PALETTE = charts.PRINT

# Light print palette (dark-ground wastes ink) but the same tokens-as-values
# and mono-for-numbers discipline as the on-screen pages (bagpipe.app.style)
# — a printed report and the web results page should read as one product.
_PAGE = Template("""
<html><head><meta charset="utf-8"><style>
@page { size: A4; margin: 18mm 16mm 16mm; }
body { font-family: 'Instrument Sans', 'Helvetica Neue', sans-serif; color: #14201D;
  font-size: 10.5pt; line-height: 1.5; }
.brand { display: flex; align-items: center; gap: 0.5em; margin-bottom: 1em; }
.brand img { height: 1.8em; width: 1.8em; }
.brand span { font-weight: 500; font-size: 1.1em; }
h1 { font-size: 1.5em; font-weight: 400; margin: 0 0 0.2em; }
h2 { font-size: 1.05em; font-weight: 500; margin: 0 0 0.5em;
  padding-bottom: 0.3em; border-bottom: 1px solid #D8DBD3; }
h3 { font-size: 0.95em; font-weight: 500; margin: 0 0 0.35em; }
section { margin-top: 1.6em; }
section.page-break { break-before: page; }
figure { margin: 0 0 1em; }
figure svg { width: 100%; height: auto; }
figcaption { color: #5C665F; font-size: 0.82em; margin-top: 0.5em; line-height: 1.45; }
p { margin: 0 0 0.6em; }
table { border-collapse: collapse; width: 100%; margin-top: 0.6em; }
th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid #D8DBD3;
  font-size: 0.85em; }
th { color: #5C665F; font-weight: 500; }
td.num { font-family: 'Geist Mono', monospace; text-align: right; white-space: nowrap; }
.big { font-size: 2em; font-weight: 400; font-family: 'Geist Mono', monospace;
  color: #14201D; margin: 0.1em 0 0; }
.muted { color: #5C665F; font-size: 0.9em; }
.stats { display: flex; gap: 0; margin: 1.2em 0 0; border: 1px solid #D8DBD3;
  border-radius: 4px; overflow: hidden; }
.stat { flex: 1 1 0; padding: 0.6em 0.8em; border-right: 1px solid #D8DBD3; }
.stat:last-child { border-right: none; }
.stat__label { margin: 0 0 0.2em; font-family: 'Geist Mono', monospace; font-size: 0.62em;
  letter-spacing: 0.08em; text-transform: uppercase; color: #5C665F; }
.stat__value { margin: 0; font-family: 'Geist Mono', monospace; font-size: 1.15em; }
.stat__note { margin: 0.15em 0 0; font-size: 0.7em; color: #5C665F; }
.narrative__block { margin-bottom: 0.9em; }
.narrative__heading { font-size: 0.95em; font-weight: 500; margin: 0 0 0.3em; }
.narrative__source { font-family: 'Geist Mono', monospace; font-size: 0.7em;
  letter-spacing: 0.05em; text-transform: uppercase; color: #5C665F;
  border-top: 1px solid #D8DBD3; padding-top: 0.5em; margin-top: 0.8em; }
.callout { margin-top: 1em; padding: 0.7em 0.9em; border-left: 3px solid #E0873A;
  background: #F4F5F1; font-size: 0.88em; }
.notice { margin-top: 1.6em; padding: 0.8em 1em; border: 1px solid #D8DBD3;
  border-radius: 4px; color: #5C665F; font-size: 0.8em; }
.interactive { margin-top: 1em; padding: 0.7em 0.9em; border: 1px dashed #D8DBD3;
  border-radius: 4px; color: #5C665F; font-size: 0.82em; }
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
<h1>$headline</h1>
<p class="muted">$subline</p>
$body
<p class="notice">This report provides information about your brain and how
it compares to a reference cohort. It is a wellness and informational report
only, and is not intended to be used or relied on for any other purpose.
Questions — $contact_email.</p>
</body></html>
""")

_STAT = Template("""
<div class="stat"><p class="stat__label">$label</p><p class="stat__value">$value</p>
<p class="stat__note">$note</p></div>""")

_REGION_ROW = Template(
    "<tr><td>$region</td><td>$network</td>"
    '<td class="num">$gm</td><td class="num">$wm</td><td class="num">$csf</td>'
    '<td class="num">$bag</td></tr>'
)


def _figure(svg: str, caption: str) -> str:
    """A chart with nothing to draw returns "" (`bagpipe.app.charts`); its
    caption must go with it rather than float over blank paper."""
    return f"<figure>{svg}<figcaption>{caption}</figcaption></figure>" if svg else ""


def _stats_html(prediction: dict, qc_metrics: dict, band_mae: float) -> str:
    population = prediction.get("population") or {}
    chronological = prediction.get("chronological_age")
    percentile = population.get("bag_percentile")
    tiles = [
        (
            "Your age",
            f"{chronological:.0f}" if chronological is not None else "—",
            "as reported" if chronological is not None else "not provided",
        ),
        ("Predicted brain age", f"{prediction['predicted_age']:.1f}", f"±{band_mae:.1f} y"),
        (
            "Cohort position",
            charts.ordinal(percentile) if percentile is not None else "—",
            f"of {population.get('n', 0):,} people" if percentile is not None else "needs your age",
        ),
        (
            "Scan quality",
            f"{qc_metrics.get('siqr_pct', 'n/a')}%",
            f"grade {qc_metrics.get('siqr_grade', 'n/a')}",
        ),
    ]
    return (
        '<div class="stats">'
        + "".join(_STAT.substitute(label=a, value=b, note=c) for a, b, c in tiles)
        + "</div>"
    )


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
        <p class="callout"><strong>Note:</strong> your predicted age falls outside
        this model's usual reporting range. Most of the model's training data is
        between {support.get("p5", 0):.0f} and {support.get("p95", 0):.0f} years old
        (full range {support.get("min", 0):.0f}-{support.get("max", 0):.0f}) —
        treat this result with extra caution.</p>
        """
    return f"""
    <p>For people around your predicted age ({band["label"]} years), this model's
    typical error is <strong>&plusmn;{band["mae_corrected"]:.1f} years</strong>{fallback_note},
    estimated from {band["n"]} people in the model's own validation data. Error is
    larger for older ages — this is a known limitation of the current model, not a
    problem with your specific scan.</p>
    {out_of_range_note}
    """


def _region_table(scores: list, zscores: dict, regional_bag: dict, n_top_regions: int) -> str:
    """The ranked regions as a table, one row per region and one column per
    tissue — the figure above it shows the shape, this carries the numbers
    for anyone who wants to check them. Named anatomically, with the atlas
    label dropped entirely: it is a join key, and the interactive report is
    where someone would go to look a region up.

    `regional_bag` (keyed the same way as `zscores`' `label`) is a distinct
    number from the GM/WM/CSF z-scores: those say how far a region's raw
    tissue value sits from the cohort norm, this says what age that region's
    own model predicts — years, not standard deviations.
    """
    top = region_names.top_deviations(scores, n=n_top_regions)

    def z_for(label: str, metric: str) -> str:
        value = zscores.get(f"{region_names.ATLAS_PREFIX}__{label}__{metric}")
        return "—" if value is None else f"{value:+.2f}"

    def bag_for(label: str) -> str:
        value = (regional_bag.get(label) or {}).get("bag_corrected")
        return "—" if value is None else f"{value:+.1f}y"

    rows = "\n".join(
        _REGION_ROW.substitute(
            region=score.display,
            network=score.network_display,
            gm=z_for(score.label, "vol_gm"),
            wm=z_for(score.label, "vol_wm"),
            csf=z_for(score.label, "vol_csf"),
            bag=bag_for(score.label),
        )
        for score in top
    )
    return f"""
    <table>
    <tr><th>Region</th><th>Network</th><th>GM</th><th>WM</th><th>CSF</th><th>BAG</th></tr>
    {rows}
    </table>
    <p class="muted">GM/WM/CSF are standard deviations from the reference cohort's average
    for someone of your predicted age, sex and head size. BAG is that region's own predicted
    age minus your chronological age, in years — from a much smaller, less regularized model
    than the headline number above, so individual regions can swing by decades even when the
    overall result is unremarkable.</p>
    """


def render_success_html(
    prediction: dict, qc_metrics: dict, n_top_regions: int = 10, results_url: str | None = None
) -> str:
    """`prediction` is `predict/prediction.json`'s dict; `qc_metrics` is the
    `qc_gate` stage's recorded metrics (SIQR score/grade, TIV, and the wider
    QC profile from `cat12_parse.parse_quality`). `results_url`, when given,
    points the reader at the interactive version of this same report.
    """
    zscores = prediction.get("regional_zscores", {})
    scores = region_names.describe(zscores)
    gm_scores = [s for s in scores if s.metric == "vol_gm"]
    networks = region_names.by_network(scores)
    population = prediction.get("population") or {}
    bag = prediction["bag_corrected"]

    band = prediction.get("age_band") or {}
    band_mae = band.get("mae_corrected")
    if band_mae is None or math.isnan(band_mae):
        band_mae = 5.0

    narrative = narrative_mod.generate(prediction, qc_metrics)
    narrative_source = (
        f"Written from your results by {narrative.model}"
        if narrative.source == "llm"
        else "Generated from your results. Not written or reviewed by a clinician."
    )

    bag_distribution_svg = (
        charts.bag_distribution(
            population["bag_histogram"], bag, population.get("bag_percentile"), _PALETTE
        )
        if population.get("bag_histogram")
        else ""
    )
    cohort_figures = _figure(
        bag_distribution_svg,
        "Every person in the reference cohort has a gap of their own — most are within a few "
        "years of zero. Your bin is the highlighted one; a gap only means something relative "
        "to this spread.",
    ) + _figure(
        charts.calibration(
            population.get("calibration", []),
            prediction.get("chronological_age"),
            prediction["predicted_age"],
            _PALETTE,
        ),
        "How the model behaves across ages. The shaded band holds the middle 80% of the "
        "cohort's predictions at each age; the dashed diagonal is a perfect prediction. The "
        "band widens and the median flattens with age — the model pulls predictions toward the "
        "middle of its training range, which is why an older reader's result carries more "
        "uncertainty.",
    )

    interactive_note = ""
    if results_url:
        interactive_note = f"""
        <p class="interactive">This report has an interactive version, where you can rotate
        the 3D brain, click any region for its numbers, and search all
        {len(gm_scores)} of them: <strong>{results_url}</strong></p>
        """

    body = f"""
    <p class="big">{bag:+.1f} years</p>
    {gap_band_html(bag, band_mae)}
    {_stats_html(prediction, qc_metrics, band_mae)}

    <section>
      <h2>Your result, explained</h2>
      {narrative_mod.sections_html(narrative)}
      <p class="narrative__source">{narrative_source}</p>
    </section>

    <section>
      <h2>Where you sit</h2>
      {cohort_figures}
      {_accuracy_caveat_html(prediction)}
    </section>

    <section class="page-break">
      <h2>Network profile</h2>
      {_figure(
          charts.network_profile(networks, _PALETTE),
          "Each bar averages dozens of regions belonging to one functional network, which makes "
          "it far steadier than any single region's value. Note the axis: network means live in "
          "a much narrower range than individual regions do.")}
      {_figure(
          charts.zscore_spread(gm_scores, _PALETTE),
          "Your whole regional profile at once, against the bell curve you would get from "
          "chance alone. Measure hundreds of things and some land beyond two standard "
          "deviations even in a completely ordinary brain.")}
    </section>

    <section class="page-break">
      <h2>Regions furthest from the norm</h2>
      {_figure(
          charts.deviation_ranking(
              region_names.top_deviations(scores, n=n_top_regions), _PALETTE,
              limit=n_top_regions),
          "Anything inside the shaded band is within the range two thirds of the cohort falls "
          "in — a region topping this list is not by itself a finding.")}
      {_region_table(scores, zscores, prediction.get("regional_bag") or {}, n_top_regions)}
      {interactive_note}
    </section>
    """
    return _PAGE.substitute(
        logo_uri=_LOGO_DATA_URI,
        headline="Brain Age Gap",
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
