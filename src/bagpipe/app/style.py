"""Shared CSS for the public-facing pages (`pages.py`, `results_page.py`,
`report.py`) — one palette/type/animation set so the whole site and the emailed
report read as the same product. Plain CSS custom properties + `<style>`, no
templating/build step (same "stdlib first" reasoning as the rest of `app/`).

Tokens follow `docs/design-brief.md` §3/§4 — dark, warm-green ground, near-
monochrome UI, color reserved for reported data only (never decoration).
`static/js/brand-tokens.js` mirrors the same seven hexes for the WebGL viewers
(CSS custom properties aren't readable from three.js/NiiVue uniforms) — this
file is the source of truth; keep both in sync by hand.
"""

from __future__ import annotations

FONTS_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2'
    "?family=Instrument+Sans:wght@300;400;500;600"
    "&family=Geist+Mono:wght@400;500"
    '&display=swap" rel="stylesheet">'
)

FAVICON_LINK = '<link rel="icon" type="image/x-icon" href="/static/favicon.ico">'

_SELECT_ARROW_SVG = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
    "viewBox='0 0 20 20'%3E%3Cpath d='M5.5 7.5l4.5 4.5 4.5-4.5' "
    "stroke='%23E8E6DF' stroke-width='1.5' fill='none' "
    "stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E"
)

_BASE_CSS_TEMPLATE = """
:root {
  --ground: #0B0F0E;
  --surface: #141A18;
  --line: #232B28;
  --bone: #E8E6DF;
  --muted: #8A928E;
  --warm: #E0873A;   /* data only — positive gap, "older" */
  --cool: #3FA89A;    /* data only — negative gap, "younger" */
  --destructive: #E0653A;
}

* { box-sizing: border-box; }

html { overflow-x: hidden; }

body {
  font-family: 'Instrument Sans', sans-serif;
  color: var(--bone);
  background: var(--ground);
  line-height: 1.5;
  font-size: 16px;
  /* No overflow-x here (html's above already stops the horizontal
     scrollbar): setting overflow-x on BOTH html and body makes body's
     overflow-y compute to `auto` too (CSS's visible/non-visible coupling
     rule), which turns body into the nearest scroll-container ancestor for
     every `position: sticky` descendant instead of the real page scroller —
     the sticky element then never re-triggers on window scroll and just
     scrolls away with the content (confirmed live: a landing__brain with
     `position: sticky` moved 1:1 with scroll instead of sticking). */
  font-variant-numeric: tabular-nums;
}

.prose { max-width: 34em; margin: 3em auto; padding: 0 1.25em; }

input[type="file"] { min-width: 0; }

h1, h2 {
  font-family: 'Instrument Sans', sans-serif;
  font-weight: 300;
  letter-spacing: -0.02em;
}

.eyebrow {
  font-family: 'Geist Mono', monospace;
  font-size: 0.75em;
  font-weight: 500;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}

.mono { font-family: 'Geist Mono', monospace; }

.brand { display: flex; align-items: center; gap: 0.6em; text-decoration: none;
  color: var(--bone); }
.brand img { height: 2em; width: 2em; }
.brand span { font-family: 'Instrument Sans', sans-serif; font-weight: 500; font-size: 1.15em; }

.card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 0.75em;
  padding: 1.5em;
}

label { display: block; margin-top: 1.1em; font-weight: 500; }
input, select {
  font-size: 1em;
  font-family: inherit;
  padding: 0.5em;
  margin-top: 0.3em;
  border: 1px solid var(--line);
  border-radius: 0.4em;
  background: var(--ground);
  color: var(--bone);
  width: 100%;
  max-width: 100%;
}
select {
  appearance: none;
  -webkit-appearance: none;
  padding-right: 2em;
  background-image: url("__SELECT_ARROW_SVG__");
  background-repeat: no-repeat;
  background-position: right 0.6em center;
  background-size: 1.1em;
}
input:focus, select:focus, button:focus-visible, a:focus-visible {
  outline: 2px solid var(--bone);
  outline-offset: 2px;
}
input[type="checkbox"] { width: auto; }

a { color: var(--bone); }

button {
  margin-top: 1.5em;
  font-size: 1em;
  font-family: 'Instrument Sans', sans-serif;
  font-weight: 500;
  padding: 0.7em 1.6em;
  min-height: 44px;
  border: 1px solid var(--bone);
  border-radius: 8px;
  background: var(--bone);
  color: var(--ground);
  cursor: pointer;
  transition: opacity 200ms ease, transform 150ms ease;
}
button:hover:not(:disabled) { opacity: 0.85; }
button:active:not(:disabled) { transform: scale(0.98); }
button:disabled { background: var(--line); border-color: var(--line); color: var(--muted);
  cursor: not-allowed; }

.button--secondary {
  background: transparent;
  color: var(--bone);
  border: 1px solid var(--line);
}
.button--secondary:hover:not(:disabled) { border-color: var(--bone); opacity: 1; }

.muted { color: var(--muted); font-size: 0.9em; }

#status {
  margin-top: 1.5em;
  padding: 1em;
  border-radius: 0.5em;
  display: none;
  border: 1px solid var(--line);
}
#status.visible { display: block; animation: fade-in 250ms ease; }
#status a { color: var(--bone); font-weight: 500; text-decoration: underline; }
#status.state-uploading, #status.state-queued, #status.state-processing {
  background: var(--surface); }
#status.state-succeeded { background: var(--surface); border-color: var(--cool); }
#status.state-failed { background: var(--surface); border-color: var(--destructive); }

.spinner {
  display: inline-block;
  width: 1em;
  height: 1em;
  border: 2px solid rgba(232,230,223,0.2);
  border-top-color: currentColor;
  border-radius: 50%;
  margin-right: 0.5em;
  vertical-align: -0.15em;
  animation: spin 800ms linear infinite;
}

.big { font-size: 1.8em; font-weight: 400; font-family: 'Geist Mono', monospace; }

.steps { list-style: none; margin: 1em 0 0; padding: 0; display: grid; gap: 0.5em; }
.step { display: flex; align-items: center; gap: 0.6em; font-size: 0.9em; }
.step__icon {
  flex: none;
  width: 1.3em;
  height: 1.3em;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75em;
  font-weight: 700;
  border: 2px solid var(--line);
  color: transparent;
}
.step--done .step__icon { background: var(--bone); border-color: var(--bone);
  color: var(--ground); }
.step--done .step__icon::after { content: "\\2713"; }
.step--current .step__icon { border-color: var(--bone); }
.step--current .step__label { font-weight: 600; }
.step--failed .step__icon { background: var(--destructive); border-color: var(--destructive);
  color: var(--ground); }
.step--failed .step__icon::after { content: "!"; }
.step__label { color: var(--muted); }
.step--current .step__label, .step--done .step__label, .step--failed .step__label {
  color: var(--bone); }

table { border-collapse: collapse; width: 100%; margin-top: 1em; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line);
  font-family: 'Geist Mono', monospace; font-size: 0.9em; }
th { color: var(--muted); font-weight: 500; }

/* The gap band — docs/design-brief.md §6b. A brain age gap is never shown as
   a bare number: a horizontal interval centered on the estimate, plotted
   against a marked zero line, so it's immediately visible whether the
   interval crosses zero. Used on the landing page, the results page, and
   the PDF report — the one way this product ever displays a BAG. */
.gap-band {
  --gap-range: 15;       /* years spanned edge-to-edge */
  position: relative;
  width: 100%;
  max-width: 22em;
  height: 2.4em;
  margin-top: 0.6em;
}
.gap-band__track {
  position: absolute;
  top: 1.1em;
  left: 0;
  right: 0;
  height: 1px;
  background: var(--line);
}
.gap-band__zero {
  position: absolute;
  top: 0.5em;
  left: 50%;
  width: 1px;
  height: 1.2em;
  background: var(--muted);
}
.gap-band__interval {
  position: absolute;
  top: 0.95em;
  height: 5px;
  border-radius: 999px;
  background: var(--cool);
}
.gap-band--positive .gap-band__interval { background: var(--warm); }
.gap-band__point {
  position: absolute;
  top: 0.7em;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--bone);
  transform: translateX(-50%);
}
.gap-band__label {
  position: absolute;
  top: -0.3em;
  transform: translateX(-50%);
  font-family: 'Geist Mono', monospace;
  font-size: 0.85em;
  white-space: nowrap;
}
.gap-band__zero-label {
  position: absolute;
  top: 1.6em;
  left: 50%;
  transform: translateX(-50%);
  font-family: 'Geist Mono', monospace;
  font-size: 0.7em;
  color: var(--muted);
}

@keyframes fade-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: none; }
}
@keyframes spin { to { transform: rotate(360deg); } }

@media (prefers-reduced-motion: reduce) {
  #status.visible { animation: none; }
  .spinner { animation: none; border-top-color: rgba(232,230,223,0.2); }
  button { transition: none; }
}
"""

BASE_CSS = _BASE_CSS_TEMPLATE.replace("__SELECT_ARROW_SVG__", _SELECT_ARROW_SVG)

# Overrides the narrow single-column BASE_CSS body width for the results page
# (brain map + region detail need a wide two-column layout), plus the
# clickable-brain-map widget itself.
RESULTS_CSS = """
.results-page { max-width: 64em; margin: 3em auto; padding: 0 1.25em; }

.results-head { margin-bottom: 1.5em; }
.results-head h1 { margin-bottom: 0.2em; }
.results-head__meta { color: var(--muted); font-size: 0.95em; }

/* Uncertainty is deliberately NOT visually de-emphasised relative to the
   headline number: the model's typical error is 4y for a 25-year-old and 11y
   for a 70-year-old, so a bare "-11.5 years" reads as far more precise than
   it is. Sized down only enough to keep the headline scannable. */
.results-head__uncertainty {
  font-size: 0.55em;
  font-weight: 400;
  color: var(--muted);
  white-space: nowrap;
  margin-left: 0.35em;
}
.results-head__caveat {
  color: var(--muted);
  font-size: 0.95em;
  line-height: 1.5;
  max-width: 60ch;
  margin-top: 0.6em;
}
.results-head__caveat--warning {
  color: var(--bone);
  background: var(--surface);
  border-left: 3px solid var(--warm);
  padding: 0.7em 0.9em;
  border-radius: 4px;
}

.section-heading { font-family: 'Instrument Sans', sans-serif; font-weight: 300;
  font-size: 1.5em; margin: 2em 0 0.75em; }
.section-heading-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5em;
}
.section-heading-row .section-heading { margin: 2em 0 0; }
.section-note { color: var(--muted); font-size: 0.9em; margin: 0 0 0.75em; }

.button-group { display: inline-flex; gap: 0.3em; flex-wrap: wrap; }
.toggle {
  background: var(--surface);
  border: 1px solid var(--line);
  color: var(--bone);
  font-size: 0.72em;
  font-family: 'Geist Mono', monospace;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 0.45em 0.9em;
  border-radius: 0.4em;
  cursor: pointer;
  transition: background-color 150ms ease, border-color 150ms ease;
}
.toggle:hover { border-color: var(--bone); }
.toggle.is-active {
  background: var(--bone);
  border-color: var(--bone);
  color: var(--ground);
}

.brainmap { display: grid; gap: 1em; margin-bottom: 2em; }
.brainmap__controls {
  display: flex;
  flex-wrap: wrap;
  gap: 1em;
  justify-content: space-between;
  align-items: center;
}
.brainmap__legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6em 1em;
  align-items: center;
  min-height: 1.6em;
}
.brainmap__legend[hidden] { display: none; }
.brainmap__legend-note { color: var(--muted); font-size: 0.85em; margin: 0; }
.legend-swatch { display: inline-flex; align-items: center; gap: 0.4em; font-size: 0.8em; }
.legend-swatch__dot { width: 0.7em; height: 0.7em; border-radius: 999px; flex: none; }

.colorbar { display: grid; gap: 0.3em; width: 100%; max-width: 28em; }
.colorbar__row { display: flex; align-items: center; gap: 0.6em; }
.colorbar__label { font-size: 0.78em; color: var(--muted); white-space: nowrap; }
.colorbar__track {
  flex: 1;
  height: 0.6em;
  border-radius: 999px;
  border: 1px solid var(--line);
}
.colorbar__ticks {
  display: flex;
  justify-content: space-between;
  font-size: 0.68em;
  color: var(--muted);
  padding: 0 0.05em;
}

.brainmap__body {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(16em, 1fr);
  gap: 1.25em;
  align-items: start;
}
.brainmap__svg { display: flex; gap: 0.75em; }
.brainmap__hemi {
  flex: 1 1 0;
  min-width: 0;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 0.75em;
  padding: 0.5em;
}
.brainmap__hemi-label {
  margin: 0 0 0.35em;
  font-size: 0.78em;
  font-weight: 500;
  color: var(--muted);
  text-align: center;
}
.brainmap__hemi-svg svg { width: 100%; height: auto; display: block; }
.brainmap__svg path {
  cursor: pointer;
  stroke: var(--surface);
  stroke-width: 1;
  transition: opacity 100ms ease;
}
.brainmap__svg path:hover { opacity: 0.75; }
.brainmap__svg path.is-selected { stroke: var(--bone); stroke-width: 2; }

.brainmap__detail {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 0.75em;
  padding: 1.25em;
  min-height: 12em;
}
.brainmap__detail-placeholder { color: var(--muted); font-size: 0.9em; margin: 0; }
.brainmap__detail-title {
  font-family: 'Instrument Sans', sans-serif;
  font-size: 1.05em;
  margin: 0 0 0.5em;
}
.brainmap__detail-network { color: var(--muted); font-size: 0.85em; margin: 0 0 0.75em; }
.zscore-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5em 0;
  border-bottom: 1px solid var(--line);
  font-family: 'Geist Mono', monospace;
  font-size: 0.9em;
}
.zscore-row:last-child { border-bottom: none; }
.zscore-row__label { font-weight: 500; font-family: 'Instrument Sans', sans-serif; }

@media (max-width: 800px) {
  .brainmap__body { grid-template-columns: 1fr; }
  .brainmap__svg { flex-direction: column; }
}

/* ---- Sticky section nav ------------------------------------------------
   The results page is now long enough that a reader who wants "the regions"
   should not have to scroll past three figures to find them. */
.section-nav {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  gap: 0.4em;
  flex-wrap: wrap;
  padding: 0.7em 0;
  margin-bottom: 1.5em;
  background: color-mix(in srgb, var(--ground) 92%, transparent);
  backdrop-filter: blur(6px);
  border-bottom: 1px solid var(--line);
}
.section-nav a {
  font-family: 'Geist Mono', monospace;
  font-size: 0.7em;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
  text-decoration: none;
  padding: 0.35em 0.7em;
  border-radius: 0.4em;
  border: 1px solid transparent;
}
.section-nav a:hover { color: var(--bone); border-color: var(--line); }

/* ---- Summary tiles ---------------------------------------------------- */
.results-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(9.5em, 1fr));
  gap: 1px;
  background: var(--line);
  border: 1px solid var(--line);
  border-radius: 0.75em;
  overflow: hidden;
  margin: 1.5em 0;
}
.stat-tile { background: var(--surface); padding: 1em 1.1em; }
.stat-tile__label {
  margin: 0 0 0.35em;
  font-family: 'Geist Mono', monospace;
  font-size: 0.65em;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}
.stat-tile__value {
  margin: 0;
  font-family: 'Geist Mono', monospace;
  font-size: 1.5em;
  font-weight: 400;
  line-height: 1.1;
}
.stat-tile__note { margin: 0.3em 0 0; font-size: 0.75em; color: var(--muted); }

/* ---- Figures ----------------------------------------------------------
   Charts come from bagpipe.app.charts as inline SVG, already carrying the
   dark palette's colors; the card is just the frame and the caption. */
.chart-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 0.75em;
  padding: 1.1em 1.2em 0.9em;
  margin-bottom: 1.25em;
}
.chart-card .chart { display: block; width: 100%; height: auto; overflow: visible; }
.chart-card__caption {
  margin: 0.8em 0 0;
  color: var(--muted);
  font-size: 0.85em;
  line-height: 1.5;
  max-width: 68ch;
}
.chart-grid { display: grid; gap: 1.25em; grid-template-columns: 1fr; }

/* ---- Narrative prose (bagpipe.app.narrative) -------------------------- */
.narrative {
  background: var(--surface);
  border: 1px solid var(--line);
  border-left: 3px solid var(--bone);
  border-radius: 0.75em;
  padding: 1.4em 1.5em;
  margin-bottom: 1.5em;
}
.narrative__block + .narrative__block { margin-top: 1.4em; }
.narrative__heading {
  margin: 0 0 0.5em;
  font-family: 'Instrument Sans', sans-serif;
  font-weight: 500;
  font-size: 0.95em;
  letter-spacing: 0.01em;
}
.narrative p { margin: 0 0 0.7em; max-width: 68ch; line-height: 1.6; font-size: 0.95em; }
.narrative p:last-child { margin-bottom: 0; }
.narrative__source {
  margin-top: 1.4em;
  padding-top: 0.8em;
  border-top: 1px solid var(--line);
  font-family: 'Geist Mono', monospace;
  font-size: 0.7em;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--muted);
}

/* ---- Region explorer (static/js/region-explorer.js) -------------------
   BASE_CSS styles every `button` as a bone-filled CTA and every `label` as a
   block with top margin (the upload form's needs). The explorer is built out
   of the same elements used as list rows and inline controls, so it resets
   those first rather than fighting them rule by rule. */
.explorer { display: grid; gap: 1em; margin-bottom: 2em; }
.explorer button, .explorer label { margin: 0; }
.explorer button { min-height: 0; font-weight: 400; transition: background-color 120ms ease; }
.explorer input, .explorer select { margin-top: 0; }
.explorer__controls {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6em 0.9em;
  align-items: center;
}
.explorer__search {
  flex: 1 1 14em;
  width: auto;
  min-width: 12em;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 0.4em;
  color: var(--bone);
  font-family: 'Instrument Sans', sans-serif;
  font-size: 0.9em;
  padding: 0.55em 0.8em;
}
.explorer__search:focus { outline: none; border-color: var(--bone); }
.explorer__field { display: inline-flex; align-items: center; gap: 0.4em; }
.explorer__field-label,
.explorer__checkbox {
  font-family: 'Geist Mono', monospace;
  font-size: 0.68em;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--muted);
}
.explorer__field select {
  width: auto;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 0.4em;
  color: var(--bone);
  font-family: 'Instrument Sans', sans-serif;
  font-size: 0.85em;
  padding: 0.4em 1.8em 0.4em 0.6em;
}
.explorer__checkbox {
  display: inline-flex;
  align-items: center;
  gap: 0.4em;
  cursor: pointer;
  text-transform: none;   /* "±2σ" must not be uppercased into "±2Σ" */
}
.explorer__count { font-family: 'Geist Mono', monospace; font-size: 0.72em; color: var(--muted); }
.explorer__list {
  max-height: 34em;
  overflow-y: auto;
  border: 1px solid var(--line);
  border-radius: 0.75em;
  background: var(--surface);
}
.explorer__empty { color: var(--muted); font-size: 0.9em; padding: 1.5em; margin: 0; }
.explorer__note {
  color: var(--muted);
  font-size: 0.78em;
  line-height: 1.5;
  margin: 0.6em 0 0;
}

.region-group + .region-group { border-top: 1px solid var(--line); }
.region-group__head {
  display: flex;
  align-items: baseline;
  gap: 0.7em;
  width: 100%;
  background: none;
  border: none;
  color: var(--bone);
  cursor: pointer;
  padding: 0.7em 1em;
  text-align: left;
  position: sticky;
  top: 0;
  background: var(--surface);
  z-index: 1;
}
.region-group__head:hover { background: color-mix(in srgb, var(--bone) 6%, var(--surface)); }
.region-group__caret { color: var(--muted); font-size: 0.8em; }
.region-group__name {
  font-family: 'Instrument Sans', sans-serif;
  font-weight: 500;
  font-size: 0.92em;
  flex: 1 1 auto;
}
.region-group__stat {
  font-family: 'Geist Mono', monospace;
  font-size: 0.7em;
  color: var(--muted);
  white-space: nowrap;
}

.region-list { list-style: none; margin: 0; padding: 0; }
.region-row + .region-row {
  border-top: 1px solid color-mix(in srgb, var(--line) 60%, transparent);
}
.region-row.is-selected { background: color-mix(in srgb, var(--bone) 8%, var(--surface)); }
.region-row__button {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 8.5em 7em 4.2em;
  align-items: center;
  gap: 0.8em;
  width: 100%;
  background: none;
  border: none;
  color: var(--bone);
  cursor: pointer;
  padding: 0.5em 1em;
  text-align: left;
  font-family: 'Instrument Sans', sans-serif;
  font-size: 0.88em;
}
.region-row__button:hover { background: color-mix(in srgb, var(--bone) 5%, transparent); }
.region-row__name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.region-row__approx {
  margin-left: 0.4em;
  font-family: 'Geist Mono', monospace;
  font-size: 0.7em;
  color: var(--muted);
}
.region-row__meta {
  font-size: 0.8em;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.region-row__bar { width: 100%; height: 12px; display: block; }
.region-row__value {
  font-family: 'Geist Mono', monospace;
  font-size: 0.82em;
  text-align: right;
}
.region-row__detail { padding: 0 1em 0.9em 1em; }
.region-row__detail-line { margin: 0 0 0.6em; color: var(--muted); font-size: 0.82em; }
.region-row__chips { display: flex; flex-wrap: wrap; gap: 0.5em; }
.region-row__chip {
  display: inline-flex;
  gap: 0.45em;
  align-items: baseline;
  background: var(--ground);
  border: 1px solid var(--line);
  border-radius: 0.4em;
  padding: 0.3em 0.6em;
}
.region-row__chip-label { font-size: 0.75em; color: var(--muted); }
.region-row__chip-value { font-family: 'Geist Mono', monospace; font-size: 0.78em; }

.brainmap__detail-label {
  margin: 0.9em 0 0;
  font-family: 'Geist Mono', monospace;
  font-size: 0.7em;
  color: var(--muted);
}

@media (max-width: 700px) {
  .region-row__button { grid-template-columns: minmax(0, 1fr) 5.5em 4em; }
  .region-row__meta { display: none; }
}

.results-footer {
  margin-top: 3em;
  padding-top: 1.2em;
  border-top: 1px solid var(--line);
  font-size: 0.85em;
}
.results-footer p { margin: 0 0 0.6em; max-width: 68ch; line-height: 1.6; }
.results-footer a { color: var(--bone); }

@media (prefers-reduced-motion: reduce) {
  .region-row, .region-group__head { transition: none; }
}
"""

# The 3D surface (cortex-viewer.js) + volumetric (volume-viewer.js) pair now
# shares the page-level tokens directly (both palettes are the same dark
# system per docs/design-brief.md) — the --bv-* aliases just point at the
# global custom properties so brand-tokens.js's hex mirror stays the only
# duplication left, for the WebGL side where CSS vars aren't reachable.
BRAIN_VIEWER_CSS = """
.brain-viewers {
  --bv-ground: var(--ground);
  --bv-surface: var(--surface);
  --bv-line: var(--line);
  --bv-bone: var(--bone);
  --bv-muted: var(--muted);
  --bv-warm: var(--warm);
  --bv-cool: var(--cool);

  background: var(--bv-ground);
  color: var(--bv-bone);
  border-radius: 0.75em;
  padding: 1.25em;
  margin-bottom: 2em;
  border: 1px solid var(--bv-line);
}

.brain-viewers button:focus-visible {
  outline: 2px solid var(--bv-bone);
  outline-offset: 1px;
}

.brain-viewers__tabs {
  display: inline-flex;
  gap: 0.3em;
  margin-bottom: 1em;
}
.brain-viewers__tab {
  background: transparent;
  border: 1px solid var(--bv-line);
  color: var(--bv-muted);
  font-family: 'Geist Mono', monospace;
  font-size: 0.72em;
  font-weight: 500;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 0.5em 1em;
  border-radius: 0.4em;
  cursor: pointer;
  margin-top: 0;
  transition: color 150ms ease, border-color 150ms ease;
}
.brain-viewers__tab:hover:not(:disabled) { color: var(--bv-bone); background: transparent;
  opacity: 1; }
.brain-viewers__tab.is-active {
  color: var(--bv-ground);
  background: var(--bv-bone);
  border-color: var(--bv-bone);
}
.brain-viewers__tab.is-active:hover:not(:disabled) {
  color: var(--bv-ground);
  background: var(--bv-bone);
}

.brain-viewers__panel { display: none; }
.brain-viewers__panel.is-active { display: block; }

.brain-viewers__stage {
  position: relative;
  width: 100%;
  height: 32em;
  background: var(--bv-ground);
  border: 1px solid var(--bv-line);
  border-radius: 0.5em;
  overflow: hidden;
}

.brain-viewers__controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1.25em;
  margin-top: 0.9em;
  font-family: 'Geist Mono', monospace;
  font-size: 0.78em;
}

.bv-group { display: inline-flex; gap: 0.3em; }
.bv-toggle {
  background: var(--bv-surface);
  border: 1px solid var(--bv-line);
  color: var(--bv-muted);
  font-family: 'Geist Mono', monospace;
  font-size: 0.72em;
  font-weight: 500;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 0.4em 0.8em;
  border-radius: 0.35em;
  cursor: pointer;
  margin-top: 0;
  transition: color 150ms ease, border-color 150ms ease;
}
.bv-toggle:hover:not(:disabled) {
  color: var(--bv-bone);
  border-color: var(--bv-muted);
  background: var(--bv-surface);
  opacity: 1;
}
.bv-toggle.is-active {
  color: var(--bv-ground);
  background: var(--bv-bone);
  border-color: var(--bv-bone);
}
.bv-toggle.is-active:hover:not(:disabled) {
  color: var(--bv-ground);
  background: var(--bv-bone);
}

.bv-slider-row { display: inline-flex; align-items: center; gap: 0.6em; color: var(--bv-muted); }
.bv-slider-row input[type="range"] {
  -webkit-appearance: none;
  width: 8em;
  height: 2px;
  background: var(--bv-line);
  border-radius: 999px;
  margin-top: 0;
}
.bv-slider-row input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 0.85em;
  height: 0.85em;
  border-radius: 50%;
  background: var(--bv-bone);
  cursor: pointer;
}
.bv-slider-row input[type="range"]::-moz-range-thumb {
  width: 0.85em;
  height: 0.85em;
  border: none;
  border-radius: 50%;
  background: var(--bv-bone);
  cursor: pointer;
}

.brain-viewers__hover {
  position: absolute;
  top: 0.75em;
  left: 0.9em;
  font-family: 'Geist Mono', monospace;
  font-size: 0.72em;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--bv-muted);
  pointer-events: none;
}
.brain-viewers__hover strong { color: var(--bv-bone); font-weight: 500; }

.brain-viewers__note {
  color: var(--bv-muted);
  font-size: 0.8em;
  margin-top: 0.75em;
}

@media (max-width: 800px) {
  .brain-viewers__stage { height: 22em; }
}
"""

# The landing page's own layout (design-brief §5): brain pinned sticky in
# the right column on `/`, vertically centered rather than glued to the top
# edge (an earlier `top:0; height:100vh` attempt read as "stuck"). The other
# four pages (`/science`, `/team`, `/privacy`, `/upload`) share the same
# nav/footer shell but use `.landing__grid--plain` — single column, no brain
# panel. Sections use hairline rules rather than cards, per the brief's
# near-monochrome discipline.
LANDING_CSS = """
.landing { max-width: 100%; }
.landing__grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 44vw;
  align-items: start;
}
/* Content-only pages (science/team/privacy/upload) — no brain panel, no
   second column. */
.landing__grid--plain { grid-template-columns: 1fr; }
.landing__grid--plain .landing__content { max-width: 80ch; margin: 0 auto; }
.landing__content { max-width: 100vw; padding: 0 6vw; }
.landing__brain {
  position: sticky;
  top: 15vh;
  height: min(60vh, 44vw);
  margin: 0 6vw 0 0;
  border: 1px solid var(--line);
  border-radius: 0.75em;
  cursor: grab;
}
.landing__brain:active { cursor: grabbing; }

.landing__nav {
  position: fixed;
  top: 0; left: 0; right: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.1em 6vw;
  background: linear-gradient(var(--ground), rgba(11,15,14,0));
  pointer-events: none;
}
.landing__nav > * { pointer-events: auto; }
.landing__nav-links { display: flex; gap: 1.5em; font-family: 'Geist Mono', monospace;
  font-size: 0.8em; }
.landing__nav-links a { text-decoration: none; color: var(--muted); }
.landing__nav-links a:hover { color: var(--bone); }
.landing__nav-links a[aria-current="page"] { color: var(--bone); }

section.landing__section {
  padding: 160px 0;
  border-top: 1px solid var(--line);
  max-width: 64ch;
}
section.landing__section:first-of-type { border-top: none; }
.landing__section--wide { max-width: none; }

.landing__hero { padding-top: 30vh; min-height: 100vh; }
.landing__hero h1 { font-size: clamp(2.4em, 6vw, 5.5em); margin: 0.3em 0; }
.landing__hero p { font-size: 1.15em; color: var(--muted); max-width: 34ch; }
.landing__cta-row { display: flex; gap: 1em; flex-wrap: wrap; margin-top: 1.5em; }

/* Scroll reveal (static/js/reveal.js) — a section starts faded/offset and
   settles in once it crosses the viewport, staggered per-section via the
   --i custom property. */
.reveal {
  opacity: 0;
  transform: translateY(16px);
  transition: opacity 500ms ease, transform 500ms ease;
  transition-delay: calc(var(--i, 0) * 80ms);
}
.reveal.is-visible { opacity: 1; transform: none; }

/* Gap bands draw outward from center once their section reveals (brief §7). */
.reveal .gap-band__interval { transform: scaleX(0); transform-origin: center; }
.reveal.is-visible .gap-band__interval { animation: gap-draw 600ms ease-out forwards; }
@keyframes gap-draw { to { transform: scaleX(1); } }

@media (prefers-reduced-motion: reduce) {
  .reveal, .reveal.is-visible { opacity: 1; transform: none; transition: none; }
  .reveal .gap-band__interval, .reveal.is-visible .gap-band__interval {
    animation: none; transform: none;
  }
}

.landing__section h2 { font-size: 2em; margin-bottom: 0.6em; }
.landing__section p { color: var(--muted); font-size: 1.05em; }
.landing__section p + p { margin-top: 1em; }

.landing__gap-pair { display: flex; gap: 3em; flex-wrap: wrap; margin-top: 2em; }
.landing__gap-item { flex: 1 1 12em; }
.landing__gap-item .eyebrow { display: block; margin-bottom: 0.5em; }

.landing__items { display: grid; gap: 2em; margin-top: 1.5em; }
.landing__item .eyebrow { display: block; margin-bottom: 0.3em; }
.landing__item h3 { font-weight: 400; margin: 0 0 0.3em; }

.landing__accuracy-table { width: 100%; margin-top: 1.5em; }
.landing__accuracy-table th, .landing__accuracy-table td { text-align: center; }
.landing__accuracy-table td:first-child, .landing__accuracy-table th:first-child {
  text-align: left; }

.landing__people { display: grid; gap: 2.5em; margin-top: 2em;
  grid-template-columns: repeat(auto-fit, minmax(14em, 1fr)); }
.landing__person h3 { font-weight: 400; margin: 0 0 0.15em; }
.landing__person .eyebrow { display: block; margin-bottom: 0.6em; }
.landing__person p { font-size: 0.95em; }
.landing__person a { color: var(--bone); font-size: 0.85em; font-family: 'Geist Mono', monospace; }

.dropzone {
  position: relative;
  border: 1px dashed var(--line);
  border-radius: 0.5em;
  padding: 1.5em;
  text-align: center;
  background: var(--ground);
}
.dropzone input[type="file"] {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}
.dropzone label {
  margin: 0;
  color: var(--muted);
  font-family: 'Geist Mono', monospace;
  font-size: 0.85em;
  pointer-events: none;
}
.dropzone.is-dragover { border-color: var(--bone); }

.landing__notice {
  margin-top: 1.5em;
  padding: 1em 1.25em;
  border: 1px solid var(--line);
  border-radius: 0.5em;
  font-size: 0.9em;
  color: var(--muted);
}

.landing__footer {
  padding: 96px 0 3em;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: 0.85em;
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 1em;
}
.landing__footer a { color: var(--muted); }
.landing__footer a:hover { color: var(--bone); }

@media (max-width: 900px) {
  /* Brief §5: "on mobile the brain becomes a sticky top third and content
     scrolls beneath" — a side-by-side column doesn't fit a narrow screen. */
  .landing__grid { grid-template-columns: 1fr; }
  .landing__brain {
    position: sticky;
    top: 0;
    height: 34vh;
    margin: 0;
    border-radius: 0;
    border-left: none;
    border-right: none;
    order: -1;
  }
  .landing__hero { padding-top: 4vh; }
  .landing__content { padding: 0 5vw; }
  section.landing__section { padding: 96px 0; max-width: none; }
}

@media (prefers-reduced-motion: reduce) {
  .landing__nav { position: absolute; }
}
"""
