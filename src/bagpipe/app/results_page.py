"""The interactive web results page (`GET /jobs/{job_id}/view`) — the
"nicer than a static PDF" view of a finished job's prediction: headline BAG,
global stats, and a clickable brain map (bagpipe.app.static.brainmap.js +
static/atlas/*, generated once from the Schaefer400+TianS2 atlas the
production model trains on). The emailed PDF (`bagpipe.app.report`) stays
static/print-only; this is the richer, browser-only counterpart.
"""

from __future__ import annotations

import json
from string import Template

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

_PAGE = Template("""<!doctype html>
<html><head><meta charset="utf-8"><title>Brain Age Gap — results</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
$favicon_link
$fonts_link
$importmap
<style>$base_css $results_css $brain_viewer_css</style></head>
<body>
<div class="brand"><img src="/static/logo-icon.png" alt=""><span>Bagpipe</span></div>

<div class="results-head">
  <p class="muted">Your results</p>
  <h1>Brain Age Gap: $bag_sign$bag_value years</h1>
  <p class="results-head__meta">Predicted brain age $predicted_age years &middot;
    scan quality $siqr_pct% ($siqr_grade)</p>
  <div class="chips">
    <span class="chip chip--$bag_severity">Brain-age gap
      <strong>$bag_sign$bag_value yrs</strong></span>
  </div>
</div>

<section aria-labelledby="brain3d-heading">
  <div class="section-heading-row">
    <h2 id="brain3d-heading" class="section-heading">3D brain</h2>
    <p class="section-note">GM/WM/CSF deviation from the SNBB cohort norm,
      teal = younger-looking, amber = older-looking</p>
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
<script type="module" src="/static/js/brain-viewers-panel.js"></script>

<section aria-labelledby="brainmap-heading">
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

<script src="/static/brainmap.js"></script>
</body></html>
""")


def _severity(z: float) -> str:
    az = abs(z)
    if az >= 2:
        return "high"
    if az >= 1:
        return "mid"
    return "low"


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
    return _PAGE.substitute(
        favicon_link=FAVICON_LINK,
        fonts_link=FONTS_LINK,
        importmap=_IMPORTMAP,
        base_css=BASE_CSS,
        results_css=RESULTS_CSS,
        brain_viewer_css=BRAIN_VIEWER_CSS,
        bag_sign="+" if bag >= 0 else "",
        bag_value=f"{bag:.1f}",
        bag_severity=_severity(bag),
        predicted_age=f"{prediction['predicted_age']:.1f}",
        siqr_pct=qc_metrics.get("siqr_pct", "n/a"),
        siqr_grade=qc_metrics.get("siqr_grade", "n/a"),
        regional_zscores_json=json.dumps(prediction["regional_zscores"]),
        volume_unavailable_note=volume_unavailable_note,
        volume_available_attr="true" if volume_available else "false",
        job_id=job_id,
    )
