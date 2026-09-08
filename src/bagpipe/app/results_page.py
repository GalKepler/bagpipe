"""The interactive web results page (`GET /jobs/{job_id}/view`).

The richer counterpart to the emailed PDF (`bagpipe.app.report`): the same
numbers, the same figures — both surfaces render `bagpipe.app.charts` and
`bagpipe.app.narrative` — plus the three things a page can do that paper
cannot. A clickable brain map and 3D viewers over the Schaefer400+TianS2
atlas the production model trains on, and a searchable/groupable explorer
across all 432 regions, all three sharing one selection through
`static/js/region-bus.js`.

Region names throughout are the anatomical ones from
`static/atlas/region_names.json` (`scripts/build_region_names.py`), never the
raw atlas labels — `LH_Vis_23` is a join key, not something to show a person
reading about their own brain.
"""

from __future__ import annotations

import json
import math
from string import Template

from bagpipe.app import charts, region_names
from bagpipe.app import narrative as narrative_mod
from bagpipe.app.pages import CONTACT_EMAIL, gap_band_html
from bagpipe.app.style import BASE_CSS, BRAIN_VIEWER_CSS, FAVICON_LINK, FONTS_LINK, RESULTS_CSS

# unpkg pins for the 3D-viewer ES modules — cortex-viewer.js / volume-viewer.js
# import bare specifiers ("three", "@niivue/niivue"), so every page that loads
# them needs this same import map. Versions must stay in lockstep with
# scripts/export_surface_mesh.py's assumptions (draco geometry) and with each
# other (three + three/addons/ from the same three release).
_IMPORTMAP = """<script type="importmap">
{
  "imports": {
    "three": "https://unpkg.com/three@0.169.0/build/three.module.js",
    "three/addons/": "https://unpkg.com/three@0.169.0/examples/jsm/",
    "@niivue/niivue": "https://esm.sh/@niivue/niivue@0.69.0"
  }
}
</script>"""

_SECTIONS = [
    ("summary", "Summary"),
    ("meaning", "Explained"),
    ("cohort", "Where you sit"),
    ("brain3d", "3D brain"),
    ("brainmap", "Brain map"),
    ("networks", "Networks"),
    ("regions", "Regions"),
]

_PAGE = Template("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Brain Age Gap — results</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
$favicon_link
$fonts_link
$importmap
<style>$base_css $results_css $brain_viewer_css</style></head>
<body>
<div class="results-page">
<a class="brand" href="/"><img src="/static/logo-icon-96.png" alt=""><span>Aevantis</span></a>

<nav class="section-nav" aria-label="Sections of this report">$section_nav</nav>

<div class="results-head" id="summary">
  <p class="muted">Your results</p>
  <h1>Brain Age Gap: $bag_sign$bag_value years
    <span class="results-head__uncertainty">&plusmn;$band_mae yrs</span></h1>
  $gap_band
  <p class="results-head__caveat">For people around your predicted age ($band_label years),
    this model's typical error is &plusmn;$band_mae years$band_fallback_note, estimated
    from $band_n people in the model's own validation data. Error is larger for older
    ages — a known limitation of the current model, not a problem with your scan.</p>
  $out_of_range_note
</div>

<div class="results-summary">$summary_tiles</div>

<section aria-labelledby="meaning-heading" id="meaning">
  <div class="section-heading-row">
    <h2 id="meaning-heading" class="section-heading">Your result, explained</h2>
  </div>
  <div class="narrative">$narrative_html
    <p class="narrative__source">$narrative_source</p>
  </div>
</section>

<section aria-labelledby="cohort-heading" id="cohort">
  <div class="section-heading-row">
    <h2 id="cohort-heading" class="section-heading">Where you sit</h2>
    <p class="section-note">your result against the $cohort_n people this model was validated on</p>
  </div>
  <div class="chart-grid">$cohort_figures</div>
</section>

<section aria-labelledby="brain3d-heading" id="brain3d">
  <div class="section-heading-row">
    <h2 id="brain3d-heading" class="section-heading">3D brain</h2>
    <p class="section-note">GM/WM/CSF deviation from the SNBB cohort norm,
      teal = below the norm, amber = above &middot; hover to name a region, click to select it</p>
  </div>
  <div class="brain-viewers" data-brain-viewers data-job-id="$job_id"
       data-volume-available="$volume_available_attr">
    <div class="brain-viewers__tabs" role="tablist">
      <button type="button" class="brain-viewers__tab is-active"
              data-bv-tab="volume">Volume</button>
      <button type="button" class="brain-viewers__tab" data-bv-tab="surface">Surface</button>
    </div>

    <div class="brain-viewers__panel is-active" data-bv-panel="volume">
      <div class="brain-viewers__stage" data-bv-volume-stage>
        <div class="brain-viewers__hover"><span data-bv-volume-hover>&nbsp;</span></div>
      </div>
      $volume_unavailable_note
    </div>

    <div class="brain-viewers__panel" data-bv-panel="surface">
      <div class="brain-viewers__stage" data-bv-cortex-stage>
        <div class="brain-viewers__hover"><span data-bv-cortex-hover>&nbsp;</span></div>
      </div>
    </div>

    <div class="brain-viewers__controls">
      <div class="bv-group" data-bv-tissue>
        <button type="button" class="bv-toggle is-active" data-tissue="vol_gm">GM</button>
        <button type="button" class="bv-toggle" data-tissue="vol_wm">WM</button>
        <button type="button" class="bv-toggle" data-tissue="vol_csf">CSF</button>
      </div>
      <label class="bv-slider-row" data-bv-opacity-row>
        Overlay <input type="range" min="0" max="1" step="0.05" value="0.75" data-bv-opacity>
      </label>
    </div>
  </div>
</section>

<script id="regional-zscores" type="application/json">$regional_zscores_json</script>
<script id="regional-bag" type="application/json">$regional_bag_json</script>
<script type="module" src="/static/js/brain-viewers-panel.js"></script>

<section aria-labelledby="brainmap-heading" id="brainmap">
  <div class="section-heading-row">
    <h2 id="brainmap-heading" class="section-heading">Brain map</h2>
    <p class="section-note">click a region for its GM/WM/CSF z-scores vs. the SNBB cohort norm</p>
  </div>
  <div class="brainmap" data-brainmap>
    <div class="brainmap__controls">
      <div class="button-group" data-brainmap-tissue>
        <button type="button" class="toggle is-active" data-tissue="vol_gm">GM</button>
        <button type="button" class="toggle" data-tissue="vol_wm">WM</button>
        <button type="button" class="toggle" data-tissue="vol_csf">CSF</button>
      </div>
      <div class="button-group" data-brainmap-atlas>
        <button type="button" class="toggle is-active" data-atlas="cortical">Cortex</button>
        <button type="button" class="toggle" data-atlas="subcortical">Subcortex</button>
      </div>
      <div class="button-group" data-brainmap-surface>
        <button type="button" class="toggle is-active" data-surface="lateral">Lateral</button>
        <button type="button" class="toggle" data-surface="medial">Medial</button>
      </div>
      <div class="button-group" data-brainmap-color>
        <button type="button" class="toggle is-active" data-color="deviation">Deviation</button>
        <button type="button" class="toggle" data-color="network">Network</button>
      </div>
    </div>
    <div class="brainmap__legend" data-brainmap-legend hidden></div>
    <div class="brainmap__body">
      <div class="brainmap__svg" data-brainmap-svg aria-label="Clickable brain region map">
        <div class="brainmap__hemi" data-hemi="left">
          <p class="brainmap__hemi-label">Left</p>
          <div class="brainmap__hemi-svg" data-hemi-svg="left"></div>
        </div>
        <div class="brainmap__hemi" data-hemi="right">
          <p class="brainmap__hemi-label">Right</p>
          <div class="brainmap__hemi-svg" data-hemi-svg="right"></div>
        </div>
      </div>
      <div class="brainmap__detail" data-brainmap-detail>
        <p class="brainmap__detail-placeholder">Click a region to see its z-scores.</p>
      </div>
    </div>
  </div>
</section>

<script type="module" src="/static/brainmap.js"></script>

<section aria-labelledby="networks-heading" id="networks">
  <div class="section-heading-row">
    <h2 id="networks-heading" class="section-heading">Network profile</h2>
    <p class="section-note">the shape of your result in eight numbers instead of 432</p>
  </div>
  <div class="chart-grid">$network_figures</div>
</section>

<section aria-labelledby="regions-heading" id="regions">
  <div class="section-heading-row">
    <h2 id="regions-heading" class="section-heading">Regions</h2>
    <p class="section-note">all $n_regions regions &middot; selecting one here highlights it on
      the brain map above, and vice versa</p>
  </div>
  <div class="explorer" data-region-explorer>
    <div class="explorer__controls">
      <input type="search" class="explorer__search" data-explorer-search
             placeholder="Search regions, networks, lobes…" aria-label="Search regions">
      <div class="button-group" data-explorer-metric></div>
      <label class="explorer__field">
        <span class="explorer__field-label">Group by</span>
        <select data-explorer-group aria-label="Group regions by"></select>
      </label>
      <label class="explorer__field">
        <span class="explorer__field-label">Sort</span>
        <select data-explorer-sort aria-label="Sort regions by"></select>
      </label>
      <label class="explorer__checkbox">
        <input type="checkbox" data-explorer-outliers> only beyond &plusmn;2&sigma;
      </label>
      <span class="explorer__count" data-explorer-count></span>
    </div>
    <p class="explorer__note" data-explorer-note hidden></p>
    <div class="explorer__list" data-explorer-list></div>
  </div>
  $ranking_figure
</section>

<footer class="results-footer">
  <p><a href="/jobs/$job_id/report.pdf">Download this report as a PDF</a></p>
  <p class="muted">This report provides information about your brain and how it compares to a
    reference cohort. It is a wellness and informational report only, and is not intended to be
    used or relied on for any other purpose. Questions — $contact_email.</p>
</footer>

</div>
<script type="module" src="/static/js/region-explorer.js"></script>
</body></html>
""")

_STAT_TILE = Template("""
<div class="stat-tile">
  <p class="stat-tile__label">$label</p>
  <p class="stat-tile__value">$value</p>
  <p class="stat-tile__note">$note</p>
</div>""")


def _summary_tiles(prediction: dict, qc_metrics: dict, band: dict) -> str:
    """The four numbers a reader wants before any figure: what they told us,
    what the model said, where that sits, and whether the scan was any good.
    """
    population = prediction.get("population") or {}
    chronological = prediction.get("chronological_age")
    percentile = population.get("bag_percentile")

    tiles = [
        (
            "Your age",
            f"{chronological:.0f}" if chronological is not None else "—",
            "as reported at upload" if chronological is not None else "not provided",
        ),
        (
            "Predicted brain age",
            f"{prediction['predicted_age']:.1f}",
            f"±{band['mae_corrected']:.1f} y typical error",
        ),
        (
            "Cohort position",
            charts.ordinal(percentile) if percentile is not None else "—",
            (
                f"percentile of {population.get('n', 0):,} people"
                if percentile is not None
                else "needs your age to place you"
            ),
        ),
        (
            "Scan quality",
            f"{qc_metrics.get('siqr_pct', 'n/a')}%",
            f"grade {qc_metrics.get('siqr_grade', 'n/a')}",
        ),
    ]
    return "".join(
        _STAT_TILE.substitute(label=label, value=value, note=note) for label, value, note in tiles
    )


def _figure(svg: str, caption: str) -> str:
    """A chart with nothing to draw returns "" (`bagpipe.app.charts`), and an
    empty framed card with a caption under it is worse than no section at
    all — so the card only exists when the figure does."""
    if not svg:
        return ""
    return (
        f'<figure class="chart-card">{svg}'
        f'<figcaption class="chart-card__caption">{caption}</figcaption></figure>'
    )


def _network_blurbs(rows: list[dict]) -> str:
    """One sentence naming the most and least deviating network in plain
    language — the chart's own axis labels are network names, and a reader
    who has never met "salience / ventral attention" needs the gloss."""
    if len(rows) < 2:
        return ""
    ordered = sorted(rows, key=lambda r: r["mean_z"])
    lowest, highest = ordered[0], ordered[-1]
    blurb = highest["blurb"].rstrip(".")
    return (
        f" Furthest above the norm here is {highest['display'].lower()} "
        f"({blurb[0].lower() + blurb[1:]}); furthest below, "
        f"{lowest['display'].lower()}."
    )


def render(prediction: dict, qc_metrics: dict, job_id: str, volume_available: bool) -> str:
    """`prediction` is `predict/prediction.json`'s dict; `qc_metrics` is the
    `qc_gate` stage's recorded metrics. `volume_available` gates the NiiVue
    volumetric panel — the T1 only exists on disk if the uploader opted into
    retention (`bagpipe.app.queue._delete_imaging` deletes it otherwise).
    """
    bag = prediction["bag_corrected"]
    if volume_available:
        volume_unavailable_note = ""
    else:
        volume_unavailable_note = (
            '<p class="brain-viewers__note">Volumetric view isn\'t available for this '
            "scan — it's only kept if you opted into data retention when you uploaded.</p>"
        )

    # Per-age-band accuracy caveat (see bagpipe.app.pipeline.predict._band_mae)
    # — computed at request time from the production model's own held-out
    # predictions, always shown alongside the headline BAG number so a lay
    # reader doesn't mistake it for a precise measurement.
    band = prediction.get("age_band") or {
        "label": "n/a",
        "n": 0,
        "mae_corrected": float("nan"),
        "is_fallback": True,
    }
    band_mae = 5.0 if math.isnan(band["mae_corrected"]) else band["mae_corrected"]
    band_fallback_note = (
        " (too few validation subjects in your exact age band — showing the "
        "model's overall typical error instead)"
        if band.get("is_fallback")
        else ""
    )
    out_of_range_note = ""
    if prediction.get("age_out_of_range"):
        support = prediction.get("training_support", {})
        out_of_range_note = (
            '<p class="results-head__caveat results-head__caveat--warning">'
            "<strong>Note:</strong> your predicted age falls outside this model's usual "
            f"reporting range. Most training data is between {support.get('p5', 0):.0f} and "
            f"{support.get('p95', 0):.0f} years old (full range "
            f"{support.get('min', 0):.0f}-{support.get('max', 0):.0f}) — treat this result "
            "with extra caution.</p>"
        )

    zscores = prediction.get("regional_zscores", {})
    scores = region_names.describe(zscores)
    gm_scores = [s for s in scores if s.metric == "vol_gm"]
    networks = region_names.by_network(scores)
    population = prediction.get("population") or {}
    palette = charts.DARK

    narrative = narrative_mod.generate(prediction, qc_metrics)
    narrative_source = (
        f"Written from your results by {narrative.model}"
        if narrative.source == "llm"
        else "Generated from your results. Not written or reviewed by a clinician."
    )

    bag_distribution_svg = (
        charts.bag_distribution(
            population["bag_histogram"], bag, population.get("bag_percentile"), palette
        )
        if population.get("bag_histogram")
        else ""
    )
    cohort_figures = _figure(
        bag_distribution_svg,
        "Every person in the reference cohort has a gap of their own — most are within a few "
        "years of zero. Your bin is the highlighted one. A gap only means something relative "
        "to this spread.",
    ) + _figure(
        charts.calibration(
            population.get("calibration", []),
            prediction.get("chronological_age"),
            prediction["predicted_age"],
            palette,
        ),
        "How the model behaves across ages. The shaded band holds the middle 80% of the "
        "cohort's predictions at each age; the dashed diagonal is a perfect prediction. The "
        "band widens and the median flattens with age — the model pulls predictions toward the "
        "middle of its training range, which is why an older reader's result carries more "
        "uncertainty.",
    )

    network_figures = _figure(
        charts.network_profile(networks, palette),
        "Each bar averages dozens of regions belonging to one functional network, which makes "
        "it far steadier than any single region's value. Note the axis: network means live in a "
        "much narrower range than individual regions do." + _network_blurbs(networks),
    ) + _figure(
        charts.zscore_spread(gm_scores, palette),
        "Your whole regional profile at once, against the bell curve you would get from chance "
        "alone. Measure hundreds of things and some land beyond two standard deviations even in "
        "a completely ordinary brain — this is the figure that says whether your outliers are "
        "more than that.",
    )

    ranking_figure = _figure(
        charts.deviation_ranking(region_names.top_deviations(scores, n=10), palette),
        "The ten regions furthest from the reference norm, for gray matter. Anything inside the "
        "shaded band is within the range two thirds of the cohort falls in — a region topping "
        "this list is not by itself a finding.",
    )

    return _PAGE.substitute(
        favicon_link=FAVICON_LINK,
        fonts_link=FONTS_LINK,
        importmap=_IMPORTMAP,
        base_css=BASE_CSS,
        results_css=RESULTS_CSS,
        brain_viewer_css=BRAIN_VIEWER_CSS,
        section_nav="".join(f'<a href="#{slug}">{name}</a>' for slug, name in _SECTIONS),
        bag_sign="+" if bag >= 0 else "",
        bag_value=f"{bag:.1f}",
        gap_band=gap_band_html(bag, band_mae),
        summary_tiles=_summary_tiles(prediction, qc_metrics, {**band, "mae_corrected": band_mae}),
        narrative_html=narrative_mod.sections_html(narrative),
        narrative_source=narrative_source,
        cohort_n=f"{population.get('n', 0):,}",
        cohort_figures=cohort_figures,
        network_figures=network_figures,
        ranking_figure=ranking_figure,
        n_regions=len(gm_scores) or len({s.label for s in scores}),
        regional_zscores_json=json.dumps(zscores),
        regional_bag_json=json.dumps(prediction.get("regional_bag") or {}),
        volume_unavailable_note=volume_unavailable_note,
        volume_available_attr="true" if volume_available else "false",
        job_id=job_id,
        band_label=band["label"],
        band_n=band["n"],
        band_mae=f"{band_mae:.1f}",
        band_fallback_note=band_fallback_note,
        out_of_range_note=out_of_range_note,
        contact_email=CONTACT_EMAIL,
    )
