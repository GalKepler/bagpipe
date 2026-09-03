"""Shared CSS for the public-facing pages (`upload_page.py`, `report.py`) —
one palette/type/animation set so the upload flow and the emailed report
read as the same product. Plain CSS custom properties + `<style>`, no
templating/build step (same "stdlib first" reasoning as the rest of `app/`).
"""

from __future__ import annotations

FONTS_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Figtree:wght@500;600;700'
    '&family=Noto+Sans:wght@400;500;600&display=swap" rel="stylesheet">'
)

FAVICON_LINK = '<link rel="icon" type="image/x-icon" href="/static/favicon.ico">'

_SELECT_ARROW_SVG = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
    "viewBox='0 0 20 20'%3E%3Cpath d='M5.5 7.5l4.5 4.5 4.5-4.5' "
    "stroke='%23134E4A' stroke-width='1.5' fill='none' "
    "stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E"
)

_BASE_CSS_TEMPLATE = """
:root {
  --color-primary: #0891B2;
  --color-secondary: #22D3EE;
  --color-accent: #16A34A;
  --color-background: #F0FDFA;
  --color-foreground: #134E4A;
  --color-muted: #E8F1F6;
  --color-border: #CCFBF1;
  --color-destructive: #DC2626;
  --color-surface: #FFFFFF;
}

* { box-sizing: border-box; }

html { overflow-x: hidden; }

body {
  font-family: 'Noto Sans', sans-serif;
  color: var(--color-foreground);
  background: var(--color-background);
  max-width: 34em;
  margin: 3em auto;
  padding: 0 1.25em;
  line-height: 1.5;
  font-size: 16px;
  overflow-x: hidden;
}

input[type="file"] { min-width: 0; }

h1, h2 {
  font-family: 'Figtree', sans-serif;
  font-weight: 700;
}

.brand {
  display: flex;
  align-items: center;
  gap: 0.6em;
  margin-bottom: 1.5em;
}
.brand img { height: 2.5em; width: 2.5em; }
.brand span {
  font-family: 'Figtree', sans-serif;
  font-weight: 700;
  font-size: 1.3em;
}

.card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 0.75em;
  padding: 1.5em;
}

label { display: block; margin-top: 1.1em; font-weight: 600; font-family: 'Figtree', sans-serif; }
input, select {
  font-size: 1em;
  padding: 0.5em;
  margin-top: 0.3em;
  border: 1px solid var(--color-border);
  border-radius: 0.4em;
  background: var(--color-surface);
  color: var(--color-foreground);
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
input:focus, select:focus, button:focus-visible {
  outline: 3px solid var(--color-secondary);
  outline-offset: 1px;
}
input[type="checkbox"] { width: auto; }

button {
  margin-top: 1.5em;
  font-size: 1em;
  font-family: 'Figtree', sans-serif;
  font-weight: 600;
  padding: 0.7em 1.6em;
  min-height: 44px;
  border: none;
  border-radius: 0.5em;
  background: var(--color-primary);
  color: #FFFFFF;
  cursor: pointer;
  transition: background-color 200ms ease, transform 150ms ease;
}
button:hover:not(:disabled) { background: #067387; }
button:active:not(:disabled) { transform: scale(0.98); }
button:disabled { background: var(--color-muted); color: #7C9A9A; cursor: not-allowed; }

.muted { color: #4B7373; font-size: 0.9em; }

#status {
  margin-top: 1.5em;
  padding: 1em;
  border-radius: 0.5em;
  display: none;
}
#status.visible { display: block; animation: fade-in 250ms ease; }
#status a { color: var(--color-primary); font-weight: 600; }
#status.state-uploading, #status.state-queued, #status.state-processing {
  background: var(--color-muted);
}
#status.state-succeeded { background: #DCFCE7; color: #14532D; }
#status.state-failed { background: #FEE2E2; color: #7F1D1D; }

.spinner {
  display: inline-block;
  width: 1em;
  height: 1em;
  border: 2px solid rgba(0,0,0,0.15);
  border-top-color: currentColor;
  border-radius: 50%;
  margin-right: 0.5em;
  vertical-align: -0.15em;
  animation: spin 800ms linear infinite;
}

.big { font-size: 1.8em; font-weight: 700; font-family: 'Figtree', sans-serif; }

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
  border: 2px solid var(--color-border);
  color: transparent;
}
.step--done .step__icon { background: var(--color-accent); border-color: var(--color-accent); color: #fff; }
.step--done .step__icon::after { content: "✓"; }
.step--current .step__icon { border-color: var(--color-primary); }
.step--current .step__label { font-weight: 700; }
.step--failed .step__icon { background: var(--color-destructive); border-color: var(--color-destructive); color: #fff; }
.step--failed .step__icon::after { content: "!"; }
.step__label { color: #4B7373; }
.step--current .step__label, .step--done .step__label, .step--failed .step__label { color: var(--color-foreground); }

table { border-collapse: collapse; width: 100%; margin-top: 1em; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--color-border); }

@keyframes fade-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: none; }
}
@keyframes spin { to { transform: rotate(360deg); } }

@media (prefers-reduced-motion: reduce) {
  #status.visible { animation: none; }
  .spinner { animation: none; border-top-color: rgba(0,0,0,0.15); }
  button { transition: none; }
}
"""

BASE_CSS = _BASE_CSS_TEMPLATE.replace("__SELECT_ARROW_SVG__", _SELECT_ARROW_SVG)

# Overrides the narrow single-column BASE_CSS body width for the results page
# (brain map + region detail need a wide two-column layout), plus the
# clickable-brain-map widget itself.
RESULTS_CSS = """
body { max-width: 64em; }

.results-head { margin-bottom: 1.5em; }
.results-head h1 { margin-bottom: 0.2em; }
.results-head__meta { color: #4B7373; font-size: 0.95em; }

.chips { display: flex; flex-wrap: wrap; gap: 0.5em; margin-top: 1em; }
.chip {
  display: inline-flex;
  align-items: center;
  gap: 0.4em;
  padding: 0.4em 0.9em;
  border-radius: 999px;
  font-size: 0.9em;
  font-weight: 600;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
}
.chip--low { color: var(--color-foreground); }
.chip--mid { color: #92400E; background: #FEF3C7; border-color: #FDE68A; }
.chip--high { color: #7F1D1D; background: #FEE2E2; border-color: #FECACA; }

.badge {
  display: inline-block;
  padding: 0.2em 0.6em;
  border-radius: 999px;
  font-size: 0.85em;
  font-weight: 700;
}
.badge--low { background: var(--color-muted); color: var(--color-foreground); }
.badge--mid { background: #FEF3C7; color: #92400E; }
.badge--high { background: #FEE2E2; color: #7F1D1D; }

.section-heading { font-family: 'Figtree', sans-serif; font-size: 1.2em; margin: 2em 0 0.75em; }
.section-heading-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5em;
}
.section-heading-row .section-heading { margin: 2em 0 0; }
.section-note { color: #4B7373; font-size: 0.9em; margin: 0 0 0.75em; }

.button-group { display: inline-flex; gap: 0.3em; flex-wrap: wrap; }
.toggle {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  color: var(--color-foreground);
  font-size: 0.85em;
  font-weight: 600;
  font-family: 'Figtree', sans-serif;
  padding: 0.45em 0.9em;
  border-radius: 0.4em;
  cursor: pointer;
  transition: background-color 150ms ease, border-color 150ms ease;
}
.toggle:hover { border-color: var(--color-primary); }
.toggle.is-active {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: #fff;
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
.brainmap__legend-note { color: #4B7373; font-size: 0.85em; margin: 0; }
.legend-swatch { display: inline-flex; align-items: center; gap: 0.4em; font-size: 0.8em; }
.legend-swatch__dot { width: 0.7em; height: 0.7em; border-radius: 999px; flex: none; }

.colorbar { display: grid; gap: 0.3em; width: 100%; max-width: 28em; }
.colorbar__row { display: flex; align-items: center; gap: 0.6em; }
.colorbar__label { font-size: 0.78em; color: #4B7373; white-space: nowrap; }
.colorbar__track {
  flex: 1;
  height: 0.6em;
  border-radius: 999px;
  border: 1px solid var(--color-border);
}
.colorbar__ticks {
  display: flex;
  justify-content: space-between;
  font-size: 0.68em;
  color: #4B7373;
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
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 0.75em;
  padding: 0.5em;
}
.brainmap__hemi-label {
  margin: 0 0 0.35em;
  font-size: 0.78em;
  font-weight: 600;
  color: #4B7373;
  text-align: center;
}
.brainmap__hemi-svg svg { width: 100%; height: auto; display: block; }
.brainmap__svg path {
  cursor: pointer;
  stroke: var(--color-surface);
  stroke-width: 1;
  transition: opacity 100ms ease;
}
.brainmap__svg path:hover { opacity: 0.75; }
.brainmap__svg path.is-selected { stroke: var(--color-foreground); stroke-width: 2; }

.brainmap__detail {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 0.75em;
  padding: 1.25em;
  min-height: 12em;
}
.brainmap__detail-placeholder { color: #4B7373; font-size: 0.9em; margin: 0; }
.brainmap__detail-title {
  font-family: 'Figtree', sans-serif;
  font-size: 1.05em;
  margin: 0 0 0.5em;
}
.brainmap__detail-network { color: #4B7373; font-size: 0.85em; margin: 0 0 0.75em; }
.zscore-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5em 0;
  border-bottom: 1px solid var(--color-border);
}
.zscore-row:last-child { border-bottom: none; }
.zscore-row__label { font-weight: 600; }

@media (max-width: 800px) {
  .brainmap__body { grid-template-columns: 1fr; }
  .brainmap__svg { flex-direction: column; }
}
"""

# The 3D surface (cortex-viewer.js) + volumetric (volume-viewer.js) pair —
# its own dark sub-theme straight from docs/design-brief.md §3/§9, not the
# light BASE_CSS palette. Keeps color meaning consistent with the brain
# renders themselves ("a teal or amber pixel means 'this is data'") rather
# than fighting the surrounding light page. Hex values here MUST match
# static/js/brand-tokens.js — that file is the source of truth for the JS
# side, this block mirrors it for CSS chrome.
BRAIN_VIEWER_CSS = """
.brain-viewers {
  --bv-ground: #0B0F0E;
  --bv-surface: #141A18;
  --bv-line: #232B28;
  --bv-bone: #E8E6DF;
  --bv-muted: #8A928E;
  --bv-warm: #E0873A;
  --bv-cool: #3FA89A;

  background: var(--bv-ground);
  color: var(--bv-bone);
  border-radius: 0.75em;
  padding: 1.25em;
  margin-bottom: 2em;
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
  font-family: 'Noto Sans', sans-serif;
  font-size: 0.72em;
  font-weight: 500;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 0.5em 1em;
  border-radius: 0.4em;
  cursor: pointer;
  transition: color 150ms ease, border-color 150ms ease;
}
/* :hover/:not(:disabled) here to out-specificity BASE_CSS's generic
   `button:hover:not(:disabled) { background: #067387 }` (light-theme
   cyan) — without it that rule wins on hover and the dark panel's own
   buttons flash light-theme colors under the cursor. */
.brain-viewers__tab:hover:not(:disabled) { color: var(--bv-bone); background: transparent; }
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
  font-family: 'Noto Sans', sans-serif;
  font-size: 0.78em;
}

.bv-group { display: inline-flex; gap: 0.3em; }
.bv-toggle {
  background: var(--bv-surface);
  border: 1px solid var(--bv-line);
  color: var(--bv-muted);
  font-size: 0.72em;
  font-weight: 500;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 0.4em 0.8em;
  border-radius: 0.35em;
  cursor: pointer;
  transition: color 150ms ease, border-color 150ms ease;
}
.bv-toggle:hover:not(:disabled) {
  color: var(--bv-bone);
  border-color: var(--bv-muted);
  background: var(--bv-surface);
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
  font-family: 'Noto Sans', sans-serif;
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
