# Arborvia — landing page design brief

Working name: **Arborvia**. From *arbor vitae*, the branching white matter of the cerebellum — named "tree of life" by anatomists centuries ago. Dendrites are named from the Greek for tree too. The brain is described in arboreal language at two independent scales; the brand doesn't impose the metaphor, it inherits it.

---

## 1. What this page is

A wellness product. A person uploads a T1-weighted MRI and receives a report on their brain: tissue volumes and cortical measures compared against a reference cohort, plus a global and regional brain age gap.

**Positioning: wellness and informational, not medical.** No diagnosis, no screening, no risk prediction. This constrains the copy hard — see §10.

**The page has two jobs at once.** Convert a curious person into an upload, and convince an investor this is a company. These don't conflict if the rigor is the story: nobody in consumer neuro shows calibrated uncertainty, and that is the differentiator, not a caveat.

**Reference class:** Neko Health, Function Health, Oura's data pages. High-end preventive health. Not generic SaaS, not a lab page, not a clinic.

---

## 2. Aesthetic thesis

Ground the design in the vernacular of the subject rather than in a generic health-tech look.

A neuroimaging figure has one consistent grammar: **a desaturated anatomical ground with a single saturated overlay, confined strictly to where the data is.** Gray brain, hot colormap on top, nothing colored that isn't measured.

Make that the rule for the entire page. The interface is near-monochrome. Color appears **only** where a number is being reported. Buttons, nav, footers, headings — all bone-on-dark. A teal or amber pixel anywhere on the page means "this is data."

This gives the design its discipline and its distinctiveness for free, and it means the brain visualization and the UI share one visual logic instead of sitting awkwardly together.

---

## 3. Color

Dark ground, but warm and green-shifted rather than neutral black — pulled from the arbor vitae, not stated literally.

| Token | Hex | Use |
|---|---|---|
| `ground` | `#0B0F0E` | Page background |
| `surface` | `#141A18` | Raised panels, cards, upload dropzone |
| `line` | `#232B28` | Hairline dividers, borders |
| `bone` | `#E8E6DF` | Primary text, wordmark, all UI |
| `muted` | `#8A928E` | Secondary text, labels, captions |
| `warm` | `#E0873A` | Data only — positive gap, "older" |
| `cool` | `#3FA89A` | Data only — negative gap, "younger" |

Notes:

- `warm`/`cool` are the diverging colormap and the *only* saturated colors on the site. Deliberately amber↔teal rather than red↔blue: no danger connotation, no cultural valence, and readable for the most common color vision deficiencies.
- Interactive states use `bone` at varying opacity, never an accent color. The primary button is bone-filled with dark text.
- Ship a light mode eventually, but design dark first — it's what makes neuroimaging data look like it's worth paying for.

---

## 4. Typography

Skip the serif. A display serif on a dark ground is the current default for premium health brands and reads as borrowed. The vernacular of scientific instruments is **grotesque plus monospace**, and that pairing is both more grounded here and less worn.

- **Display and body:** Söhne (Klim) if there's budget; otherwise **Instrument Sans** — slightly narrow, has a spine, doesn't read as Inter.
- **Data and labels:** a mono for every number, coordinate, region name, unit, and eyebrow label. **Söhne Mono**, or free: **Geist Mono**.

The mono is doing real work, not decoration: it marks the boundary between prose and measurement, which is the same boundary the color rule enforces.

**Scale.** Set the display large and *light*, tracked tight — not bold. Large light weight reads as instrument; large bold reads as SaaS.

| Role | Size | Weight | Tracking |
|---|---|---|---|
| Hero | 72–96px | 300 | −3% |
| Section head | 40px | 300 | −2% |
| Body | 18px | 400 | 0 |
| Data value | 32–56px | 400, mono | −1% |
| Label / eyebrow | 12px | 500, mono, uppercase | +8% |

Prose measure capped at 64ch. Tabular figures everywhere.

---

## 5. Layout

Split-viewport scrollytelling on desktop: **the brain is pinned in a sticky panel on the right for the full page**, content scrolls past it on the left. One continuous object that changes state — not seven disconnected sections each with its own graphic.

On mobile the brain becomes a sticky top third and content scrolls beneath.

Generous vertical rhythm: 160px between sections desktop, 96px mobile. Hairline rules rather than cards. No box-in-box.

---

## 6. Signature elements

Spend the boldness in exactly two places and keep everything else silent.

**a. The persistent brain.** A cortical surface with two-tone curvature shading (the gyral/sulcal binary map every neuroimager recognizes), rotating and re-coloring as the page scrolls. Regions illuminate in the diverging map only when that section is discussing them.

**b. The gap band.** The way a brain age gap is displayed, everywhere it appears. Never a bare number. A horizontal interval centered on the estimate, plotted against a marked zero line, so it is immediately visible whether the interval crosses zero. This is the product's ethical position rendered as a graphic, and it should be as recognizable as a logo.

---

## 7. Motion

Scroll-linked only. Nothing autoplays, nothing loops.

- Brain rotation and region illumination driven by scroll position, so it feels responsive rather than like a video.
- Numbers count up once on entry, then rest.
- Gap bands draw outward from their center point.
- `prefers-reduced-motion` gets a fully static page with the brain at a fixed, well-chosen angle. Some users will be older; this is a health product.

---

## 8. Sections, in order

**1 — Hero**
Brain rotating slowly, ambient. Single claim, no supporting stat block.

> Your brain has an age of its own.
>
> Upload an MRI and see how yours compares to thousands of others — with the uncertainty shown, not hidden.

One button: `See a sample report`. The upload CTA comes later; asking for an MRI before showing anything is the wrong order.

**2 — The gap**
The commercial thesis in one image. Two brains side by side, both labelled 52 years old, one reading +6 and one reading −4, each with its gap band. Almost no copy — this explains the company in two seconds, and prose beneath it would weaken it.

**3 — What you get**
Regions illuminate in sequence as this scrolls. Three items, mono labels:
tissue composition (gray matter, white matter, CSF, against reference); regional measures (cortical thickness and volume by region); brain age gap (global and regional).

**4 — Sample report**
A real, fully interactive result from a consented cohort participant, embedded live — not a screenshot, not a modal. Letting someone touch the product before signing up is the strongest conversion asset and the strongest diligence asset simultaneously. Costs one anonymized record.

**5 — The science**
Cohort size stated plainly — it's the moat and investors read it correctly. Model approach, the stacked ensemble, links to publications. This section is the credibility engine; let it be long and figure-rich rather than a footnote.

**6 — Who we are**
Faces, real affiliations, institutional context. At this stage the founders *are* the trust signal, doing the work a company's brand would otherwise do.

**7 — Upload**
Brain returns to full presence. One action. Below it, plainly stated: what gets stripped from the file, when uploads are deleted, that data stays on our infrastructure, and that nothing is used for research without separate consent.

---

## 9. Components

**Primary button** — bone fill, `ground` text, 8px radius, no shadow.
**Secondary** — 1px `line` border, bone text, transparent fill.
**Upload dropzone** — `surface` fill, dashed `line` border, mono helper text naming accepted formats. Empty state is an invitation, not an apology.
**Data card** — no border, `surface` fill, mono label above, large value below, gap band beneath where applicable.
**Region tooltip** — `surface`, mono, region name plus value plus percentile. Appears on hover over the brain.

---

## 10. Copy guardrails

Wellness positioning is a hard constraint on language, and violating it is what turns a wellness product into a regulated device.

**Never appears on the site:** diagnose, detect, screen, risk, disease, disorder, Alzheimer's, dementia, patient, clinical, treatment, prevent, medical advice.

**Use instead:** measure, compare, report, observe, reference range, percentile, participant, information.

The distinction that matters: *"provides information about your brain"* is wellness. *"assesses your brain health"* is a claim. Stay on the first side of that line in every headline, button, and tooltip.

Every result surface states plainly that this is informational and not a medical assessment — designed in, not buried in a footer.

Get formal regulatory advice before launch. This brief is a design document, not legal guidance.

---

## 11. Anti-patterns

No scores out of 100. No green/amber/red. No gamification, streaks, or badges. No "improve your brain age." No stock photography of smiling people or glowing blue neural networks. No gradient mesh, no glassmorphism. No rotating 3D hero that ignores scroll. No bare point estimates, anywhere, ever.

---

## 12. Split of work

**Claude Design:** everything in §3–§9 — layout, type, color, section composition, component states, the gap band as a graphic.

**Code (three.js / NiiVue):** the cortical surface itself, curvature shading, scroll-linked illumination, the results viewer.

**Order matters.** Rough the brain in code first, even unstyled, and see how it actually reads on a dark ground at hero scale. Designing a hero around an imagined brain risks a layout the real geometry won't sit in.
