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

**Implementation note (2026-09-06, later; re-landed 2026-09-08 — see below).**
The single-page scrollytelling spec below buried the hero/gap under ~1,500
words of science and privacy prose. `/` now carries only Hero + The gap +
What you get + Sample report (§8.1-8.4) with the sticky brain panel;
Science, Team, Privacy, and Upload (§8.5-8.7) are their own pages
(`/science`, `/team`, `/privacy`, `/upload`) sharing one nav/footer shell,
single column, no brain panel. Reference: kinstitute.org.il's short visual
landing + dedicated content pages. The sticky-brain layout described below
still applies, just to `/` only.

Split-viewport scrollytelling on desktop: **the brain is pinned in a sticky panel on the right for the full page**, content scrolls past it on the left. One continuous object that changes state — not seven disconnected sections each with its own graphic.

On mobile the brain becomes a sticky top third and content scrolls beneath.

Generous vertical rhythm: 160px between sections desktop, 96px mobile. Hairline rules rather than cards. No box-in-box.

**Implementation note (2026-09-06):** two false starts before landing on this
spec's own design. First attempt used `position: sticky; top: 0; height:
100vh`, which glues the panel to the very top edge of the viewport for its
entire sticky range — reported back as "stuck at the top, can't see it move."
Second attempt (over-)corrected by pulling the brain out of the sticky panel
entirely into a normal-flow hero visual that scrolls away after one viewport
— but that's not what was asked for. Shipped: `.landing__brain` sticky at
`top: 15vh; height: min(60vh, 44vw)` (clear of the top edge, doesn't fill the
whole viewport), releasing near the bottom of the page. Rotation is
click-drag (three.js OrbitControls, wheel-zoom disabled so scrolling over the
canvas isn't captured) rather than scroll-position-driven — independent of
the sticky-vs-normal-flow question.

**Correction (2026-09-08):** the idle auto-rotate described above was
removed the same day it was recovered — it resumed a few seconds after every
drag, so a user could never tell their own drag had done anything (reported
twice as "click-drag doesn't work" before this was traced to the auto-rotate
masking it, not a broken drag). Rotation is now click-drag only, static
otherwise.

**Recovery note (2026-09-08):** the two notes above, and the code implementing
them, were done in a 2026-09-06 session but only ever landed in a `git
stash` — a `pull --ff-only` right after moved `main` forward without the
stash being reapplied, and a later, unrelated session rebuilt the landing
page from the pre-stash single-page version, never knowing the multi-page
split existed. Symptom noticed 2026-09-08: sections all on one page, brain
glued to the top, no click-drag. Recovered from `git stash list` (the stash
itself, plus `git log --all` for the merge commit that recorded stray
untracked files at the same point) and re-applied onto the landing page's
current (2026-09-07) content, which had grown a Sample report section (now
folded into `/`, §8.4) since the original stash was made. Moral: an
uncommitted `git stash` survives a `pull --ff-only` on disk but is invisible
to anyone not looking for it — commit work-in-progress to a branch instead
of stashing across a pull whenever practical.

---

## 6. Signature elements

Spend the boldness in exactly two places and keep everything else silent.

**a. The persistent brain.** A cortical surface with two-tone curvature shading (the gyral/sulcal binary map every neuroimager recognizes), rotating and re-coloring via click-drag orbit only — static until touched (see §5's 2026-09-08 correction; not scroll-driven, no idle auto-rotate). It shows the landing page's illustrative sample regional map (`static/js/landing.js`) plus a colorbar legend, not a data-accurate per-section overlay.

**b. The gap band.** The way a brain age gap is displayed, everywhere it appears. Never a bare number. A horizontal interval centered on the estimate, plotted against a marked zero line, so it is immediately visible whether the interval crosses zero. This is the product's ethical position rendered as a graphic, and it should be as recognizable as a logo.

---

## 7. Motion

Nothing autoplays as video; nothing loops without user input.

- Brain rotation is click-drag only, static otherwise — see §5's 2026-09-08 correction for why idle auto-rotate was removed.
- Sections fade/rise in on scroll into view (`static/js/reveal.js`, shared across all five pages), staggered per section.
- Gap bands draw outward from their center point on reveal.
- `prefers-reduced-motion` disables section-reveal animation (content shows immediately) but leaves click-drag rotation available, since that's user-initiated, not autoplay. Some users will be older; this is a health product.

---

## 8. Sections, per page (see §5's 2026-09-06 note for the page split)

**`/`:**

**1 — Hero**
Brain rotating slowly, ambient. Single claim, no supporting stat block.

> Your brain has an age of its own.
>
> Upload an MRI and see how yours compares to thousands of others — with the uncertainty shown, not hidden.

One button: `See a sample report`. The upload CTA comes later; asking for an MRI before showing anything is the wrong order.

**2 — The gap**
The commercial thesis in one image. Two brains side by side, both labelled 52 years old, one reading +6 and one reading −4, each with its gap band. Almost no copy — this explains the company in two seconds, and prose beneath it would weaken it.

**3 — What you get**
Three items, mono labels: tissue composition (gray matter, white matter, CSF, against reference); regional measures (cortical thickness and volume by region); brain age gap (global and regional).

**4 — Sample report** *(2026-09-07: implemented as its own section on `/`,
carried by an illustrative gap band, rather than the embedded-live real
participant this section originally specified — that's still the eventual
target here.)*
A real, fully interactive result from a consented cohort participant, embedded live — not a screenshot, not a modal. Letting someone touch the product before signing up is the strongest conversion asset and the strongest diligence asset simultaneously. Costs one anonymized record.

**`/science`:**

**5 — The science**
Cohort size stated plainly — it's the moat and investors read it correctly. Model approach, the stacked ensemble, links to publications. This section is the credibility engine; let it be long and figure-rich rather than a footnote.

**`/team`:**

**6 — Who we are**
Faces, real affiliations, institutional context. At this stage the founders *are* the trust signal, doing the work a company's brand would otherwise do.

**`/privacy`:** what gets stripped from the file, when uploads are deleted,
that data stays on our infrastructure, and that nothing is used for research
without separate consent — a real policy page, linked from both `/` and
`/upload`.

**`/upload`:**

**7 — Upload**
*(2026-09-06: `/upload` is single-column, no brain panel — kept simple
rather than loading three.js on the highest-intent, most-conversion-sensitive
page.)* One action. Below it, plainly stated, and linking to `/privacy` for
the detail.

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
