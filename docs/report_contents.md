# What the report shows

The public app produces one result in two forms: an **interactive results
page** (`GET /jobs/{job_id}/view`, `bagpipe.app.results_page`) and an
**emailed PDF** (`bagpipe.app.report`). They are the same report. Every
figure and every paragraph is rendered by shared code — `bagpipe.app.charts`
and `bagpipe.app.narrative` — so the two cannot drift; what the page adds is
interaction (3D viewers, a clickable brain map, a searchable region
explorer), not extra content.

This page documents what each part shows, where its numbers come from, and
the constraints that shape it.

---

## 1. Region names

The atlas the production model trains on labels its regions `LH_Vis_23` and
`pGP-lh`. Those are join keys. Nothing user-facing ever shows one.

`src/bagpipe/app/static/atlas/region_names.json` maps every one of the 432
regions to an anatomical name, a functional network, a lobe, and a
hemisphere. It is generated once by `scripts/build_region_names.py` and
committed; nothing at runtime needs nibabel or the annot files.

- **Cortex (400 Schaefer parcels).** The name is *derived*, not hand-written:
  `container/atlas/{lh,rh}.schaefer2018_400p_7n.annot` and
  `container/atlas/{lh,rh}.aparc_DK40.freesurfer.annot` label the same 164k
  fsaverage surface, so each parcel's anatomical name is the modal
  Desikan-Killiany label over its vertices. The overlap fraction is kept as
  `coverage` (median 0.82). Below 0.60 the parcel genuinely straddles two
  gyri and gets a two-part name ("Left insula / supramarginal gyrus"), which
  the UI flags as `approx.` rather than presenting as exact.
- **Subcortex (32 Tian S2 regions).** Expanded from Tian's documented
  abbreviation scheme (`aHIP` → anterior hippocampus, `THA-VA` →
  ventroanterior thalamus).
- Parcels landing in the same gyrus are numbered within (hemisphere,
  anatomy), so display names are unique — the explorer and the report table
  would otherwise be ambiguous.

Re-run `uv run python scripts/build_region_names.py` only if the atlas files
change.

Server-side consumers go through `bagpipe.app.region_names`; the browser
fetches the same JSON via `static/js/region-bus.js`.

---

## 2. Cohort context

`bagpipe.app.pipeline.predict._population_context` computes, from the
production model's own held-out `predictions` rows (the same rows that fit
the Cole corrector and the per-age-band MAE, so nothing can disagree):

| Field | What it is |
|---|---|
| `bag_percentile` | Where the reader's corrected gap falls in the cohort's gap distribution |
| `bag_histogram` | Counts per bin over a robust (1st–99th percentile) symmetric range |
| `calibration` | Per 5-year age bin: cohort median and 10th/90th percentile of predicted age |
| `bag_mean`, `bag_sd`, `n` | Distribution summary |

**Privacy.** The reference cohort is real SNBB data and this payload is
served to a public browser, so it is aggregate only: bin counts and
percentiles over at least `MIN_BAND_N` (10) subjects. No per-subject row —
not even an anonymous (age, prediction) pair — leaves the machine. Age bins
below the threshold are dropped rather than plotted, both because their
percentiles are noise and because a thin bin starts to describe individuals.

An empty `calibration` (a cohort too small to fill any bin) is a valid
outcome: the chart returns `""` and both surfaces omit the figure entirely
rather than framing an empty box.

---

## 3. Figures

All five live in `bagpipe.app.charts` as pure functions returning inline SVG
strings. Server-rendered rather than drawn by a JS library for one reason:
WeasyPrint has no JS, so a client-drawn figure is one the PDF could never
have. The palette is passed in (`charts.DARK` for the page, `charts.PRINT`
for the report) rather than read from CSS custom properties.

| Figure | Answers |
|---|---|
| `bag_distribution` | "Is my gap unusual?" — the cohort's whole gap distribution with the reader's bin highlighted |
| `calibration` | "How well does this model work at my age?" — the cohort's predicted-vs-chronological band per age bin, with the reader's point on it. The band fanning out and the median flattening with age is the model's biggest limitation, made visible instead of asserted in a caveat |
| `network_profile` | "What is the shape of my result?" — mean deviation per Yeo-7 network plus subcortex. Deliberately on its own narrow axis: a network mean over ~57 parcels is a far tighter quantity than one parcel's z, and the report must never let those look alike |
| `zscore_spread` | "Are my outliers more than chance?" — the reader's regional z-scores against the standard normal. With 432 regions about 20 land beyond ±2σ in a completely ordinary brain, and the overlay says so |
| `deviation_ranking` | "Which regions are furthest out?" — a diverging lollipop over a shaded ±1σ band, so a region topping the list is visibly ordinary when it is |

---

## 4. Prose

`bagpipe.app.narrative` writes the three explanatory sections ("What this
means", "Your regional pattern", "How to read this").

Two implementations, one interface:

- `_template_narrative` — deterministic, offline, always available. Composes
  the paragraphs from numbers the report already computed.
- `_llm_narrative` — **not yet wired to a provider.** It returns `None`
  today, so `generate()` falls through to the template and the report renders
  identically whether or not a key is ever configured.

To wire the LLM path: read provider/model/key from `app.narrative` in
`config/local.yaml`, render `narrative.PROMPT_TEMPLATE` with
`build_context(...)`, and return a `Narrative` with `source="llm"`. Two
things it must keep doing:

1. **Send only `build_context`'s output.** That dict is deliberately the
   whole prompt payload: derived statistics and readable region names, no
   imaging, no identifiers, no raw feature values, no file paths (there is a
   test asserting this).
2. **Stay inside `generate`'s try/except**, so a provider outage degrades the
   prose rather than failing an hour-long job at its last stage.

`narrative.COPY_RULES` is the constraint list both implementations are
written against, and the one an LLM prompt carries verbatim. The report is a
wellness product (`docs/design-brief.md` §1/§10): no diagnosis, no risk
prediction, no bare point estimates, no single region treated as meaningful
on its own.

Either way, the rendered block is labelled with its source — the reader is
told the text was generated and not reviewed by a clinician.

---

## 5. Interaction (results page only)

Three widgets show the same 432 regions:

- the SVG brain map (`static/brainmap.js`),
- the 3D surface/volume viewers (`static/js/brain-viewers-panel.js`),
- the region explorer (`static/js/region-explorer.js`) — search, group by
  network/lobe/hemisphere, sort, filter to beyond ±2σ, expand a row for all
  tissue metrics.

They share one selection through `static/js/region-bus.js` (a `CustomEvent`
on `document`, no framework, no store). Selecting a region anywhere selects
it everywhere: the brain map switches between the cortical and subcortical
atlas if needed, and the explorer clears a filter that would otherwise hide
the region the reader just clicked on the anatomy.

The PDF closes with the ranked-deviation figure and a table of the same
regions instead of pretending to be navigable, and prints the results-page
URL (`app.public_base_url`) so a reader holding only the attachment can
reach the interactive version.
