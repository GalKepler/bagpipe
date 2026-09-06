"""The public landing page served at `GET /` — replaces the old bare-form
`upload_page.py`. Implements `docs/design-brief.md`: a scrollytelling page
with the cortex pinned in a sticky panel, science/people/privacy sections
before the upload form, and the upload flow itself (identical wire contract
to the old page — same field names, same poll loop, same `?job=` resume) at
the bottom. Same "stdlib templating, no build step" approach as the rest of
`app/`.

Numbers quoted in the science section (per-age-band MAE, cohort size, Cole
slope) are real, taken from CLAUDE.md's 2026-09-03 pre-launch entry and
`config/models/stacked_v26.yaml` — they describe the model as of that date,
not live-queried per request (unlike the results page's own `age_band`,
which *is* computed live in `pipeline/predict.py`). Update them by hand if a
future promotion moves the leaderboard meaningfully.

PEOPLE / CONTACT_EMAIL below are the two things this file cannot get right
without the maintainer: fill in real names, roles, affiliation, and links.
"""

from __future__ import annotations

from string import Template

from bagpipe.app.style import BASE_CSS, FAVICON_LINK, FONTS_LINK, LANDING_CSS

CONTACT_EMAIL = "galkepler@gmail.com"

# TODO(maintainer): roles/bios/links are still placeholders — names are real
# (2026-09-06).
PEOPLE = [
    {
        "name": "Dr. Gal Kepler, Ph.D",
        "role": "TODO — your role",
        "bio": "TODO — one or two sentences on your background and part in this project.",
        "link": "",
    },
    {
        "name": "Prof. Yaniv Assaf, Ph.D",
        "role": "TODO — role",
        "bio": "TODO — one or two sentences on their background and part in this project.",
        "link": "",
    },
]

_IMPORTMAP = """<script type="importmap">
{
  "imports": {
    "three": "https://unpkg.com/three@0.169.0/build/three.module.js",
    "three/addons/": "https://unpkg.com/three@0.169.0/examples/jsm/"
  }
}
</script>"""

_ACCURACY_ROWS = [
    ("18–30", "4.03"),
    ("30–40", "3.95"),
    ("40–50", "6.11"),
    ("50–60", "9.91"),
    ("60–70", "10.71"),
    ("70–90", "11.00"),
]

_PERSON = Template("""
<div class="landing__person">
  <h3>$name</h3>
  <p class="eyebrow">$role</p>
  <p>$bio</p>
  $link_html
</div>
""")


def _people_html() -> str:
    cards = []
    for p in PEOPLE:
        link_html = f'<a href="{p["link"]}">{p["link"]}</a>' if p["link"] else ""
        cards.append(
            _PERSON.substitute(name=p["name"], role=p["role"], bio=p["bio"], link_html=link_html)
        )
    return "\n".join(cards)


def _accuracy_table_html() -> str:
    heads = "".join(f"<th>{band}</th>" for band, _ in _ACCURACY_ROWS)
    cells = "".join(f"<td>&plusmn;{mae}y</td>" for _, mae in _ACCURACY_ROWS)
    return f"""
    <table class="landing__accuracy-table mono">
      <tr><th>Age band</th>{heads}</tr>
      <tr><td>Typical error</td>{cells}</tr>
    </table>
    """


_GAP_BAND = Template("""
<div class="gap-band $sign_class" style="--gap-range: $range;">
  <div class="gap-band__track"></div>
  <div class="gap-band__zero"></div>
  <div class="gap-band__zero-label">0</div>
  <div class="gap-band__interval" style="left: $bar_left%; width: $bar_width%;"></div>
  <div class="gap-band__point" style="left: $point_pct%;"></div>
  <div class="gap-band__label" style="left: $point_pct%;">$sign$value y</div>
</div>
""")


def gap_band_html(value: float, uncertainty: float, range_years: float = 15.0) -> str:
    """The one way a BAG number is ever displayed on this site (design-brief
    §6b / §11 "no bare point estimates, anywhere, ever") — an interval
    centered on `value` with half-width `uncertainty`, plotted against a
    marked zero line spanning +/-`range_years`. Percent positions computed
    server-side so the widget needs no JS to render correctly.
    """
    span = 2 * range_years
    point_pct = 50 + (value / span) * 100
    lo_pct = 50 + ((value - uncertainty) / span) * 100
    hi_pct = 50 + ((value + uncertainty) / span) * 100
    lo_pct, hi_pct, point_pct = (max(2, min(98, p)) for p in (lo_pct, hi_pct, point_pct))
    return _GAP_BAND.substitute(
        sign_class="gap-band--positive" if value >= 0 else "gap-band--negative",
        range=span,
        bar_left=f"{lo_pct:.1f}",
        bar_width=f"{max(hi_pct - lo_pct, 1):.1f}",
        point_pct=f"{point_pct:.1f}",
        sign="+" if value >= 0 else "",
        value=f"{value:.1f}",
    )


_PAGE = Template("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Aevantis — Brain Age Gap</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Upload a T1-weighted MRI and see how your brain compares
  to a reference cohort — with the uncertainty shown, not hidden.">
$favicon_link
$fonts_link
$importmap
$turnstile_script
<style>$base_css $landing_css</style></head>
<body>

<nav class="landing__nav">
  <a class="brand" href="#"><img src="/static/logo-icon-96.png" alt=""><span>Aevantis</span></a>
  <div class="landing__nav-links">
    <a href="#science">Science</a>
    <a href="#people">Team</a>
    <a href="#privacy">Privacy</a>
    <a href="#upload">Upload</a>
  </div>
</nav>

<div class="landing__grid">
  <div class="landing__content">

    <section class="landing__section landing__hero">
      <p class="eyebrow">Brain Age Gap</p>
      <h1>Your brain has an age of its own.</h1>
      <p>Upload an MRI and see how yours compares to thousands of others —
      with the uncertainty shown, not hidden.</p>
      <div class="landing__cta-row">
        <button type="button" data-scroll-to="sample">See a sample report</button>
        <button type="button" class="button--secondary"
                data-scroll-to="upload">Upload a scan</button>
      </div>
    </section>

    <section class="landing__section" id="gap">
      <p class="eyebrow">The gap</p>
      <h2>The same age. Two different brains.</h2>
      <div class="landing__gap-pair">
        <div class="landing__gap-item">
          <span class="eyebrow">52 years old</span>
          $gap_example_neg
        </div>
        <div class="landing__gap-item">
          <span class="eyebrow">52 years old</span>
          $gap_example_pos
        </div>
      </div>
    </section>

    <section class="landing__section" id="what-you-get">
      <p class="eyebrow">What you get</p>
      <h2>Three measurements, not a score.</h2>
      <div class="landing__items">
        <div class="landing__item" data-illuminate="tissue">
          <span class="eyebrow">01 — Tissue composition</span>
          <h3>Gray matter, white matter, CSF</h3>
          <p>Regional tissue volumes compared against the reference cohort.</p>
        </div>
        <div class="landing__item" data-illuminate="regions">
          <span class="eyebrow">02 — Regional measures</span>
          <h3>400 cortical + subcortical regions</h3>
          <p>Volume by region, on the Schaefer 2018 / Tian 2020 parcellation.</p>
        </div>
        <div class="landing__item" data-illuminate="bag">
          <span class="eyebrow">03 — Brain age gap</span>
          <h3>Global and regional</h3>
          <p>Predicted age minus chronological age, shown as an interval, never a bare number.</p>
        </div>
      </div>
    </section>

    <section class="landing__section" id="sample">
      <p class="eyebrow">Sample report</p>
      <h2>See it before you upload anything.</h2>
      <p>The brain on the right is driven by an illustrative example —
      not a real participant — so you can see what a report looks like
      before deciding to try it yourself.</p>
      $sample_gap_band
    </section>

    <section class="landing__section landing__section--wide" id="science">
      <p class="eyebrow">The science</p>
      <h2>What this measures, and how well it works.</h2>
      <p><strong>What a brain age gap is.</strong> A model estimates an age
      from brain structure alone; the gap is that estimate minus your
      chronological age. We report it as a measurement with an interval,
      never a score.</p>
      <p><strong>What is measured.</strong> A T1-weighted scan is segmented
      with CAT12 into regional gray matter, white matter, and CSF volumes on
      a 400-region cortical (Schaefer 2018, 7 networks) plus subcortical
      (Tian 2020, S2) parcellation, in standard MNI space. Total
      intracranial volume and sex are regressed out per region — fit
      only on training data — before the model ever sees a volume.</p>
      <p><strong>The model.</strong> A per-region stacked ensemble: one base
      model per brain region learns from that region's own volumes, and a
      meta-model combines their out-of-fold predictions into one age
      estimate. Evaluation always groups scans by participant, so a
      person's repeated scans never span both the training and test sets.</p>
      <p><strong>Calibration, stated honestly.</strong> A linear correction
      (de Lange &amp; Cole, 2017) removes the model's tendency to
      overestimate young brains and underestimate old ones. Right now that
      correction's fitted slope is 0.713, which means it slightly
      <em>amplifies</em> any individual deviation from the population
      trend — a known, calibrated tradeoff, not an error, and part of
      why we show an interval instead of a point.</p>
      <p><strong>Accuracy by age.</strong> Error is not the same at every
      age — most of the reference cohort is 18–40, so the model is
      most precise there and less precise outside it:</p>
      $accuracy_table
      <p class="muted">Typical error (mean absolute error), measured on the
      model's own held-out validation data, as of the last production
      promotion.</p>
      <p><strong>The cohort.</strong> Roughly 4,500 participants and 6,000
      scans from a single research site, including repeated measures.</p>
      <p><strong>The pipeline.</strong> Your upload runs through the exact
      same processing container that produced the training data — the
      same segmentation software, the same version, the same parameters —
      so your result is comparable to the cohort it's measured against, not
      a different pipeline's approximation of it.</p>
      <p><strong>What this doesn't do yet.</strong> Cortical thickness and
      other surface-based measurements are computed for research but aren't
      part of the number your report shows today.</p>
    </section>

    <section class="landing__section landing__section--wide" id="people">
      <p class="eyebrow">Who we are</p>
      <h2>The people behind this.</h2>
      <div class="landing__people">
        $people
      </div>
    </section>

    <section class="landing__section landing__section--wide" id="privacy">
      <p class="eyebrow">Privacy</p>
      <h2>What happens to your scan.</h2>
      <p><strong>Your face is removed before anything else happens.</strong>
      Every upload is defaced immediately, regardless of what you choose
      below, before any other processing step runs.</p>
      <p><strong>Deleted by default.</strong> Unless you check "retain my
      uploaded scan" at upload time, every copy of your imaging data —
      the original file, the intermediate conversion, the defaced version,
      and the raw segmentation output — is removed once your report is
      ready. What stays is the report itself, so your results link and PDF
      keep working.</p>
      <p><strong>Your scan never trains the model.</strong> The age you
      report is self-declared and unverified, so nothing from a public
      upload is ever added to the training data.</p>
      <p><strong>Your results link is the credential.</strong> Anyone with
      your results link can view it — the same model as an unlisted
      share link, not a password-protected account. Don't share it if you
      don't want it seen.</p>
      <p><strong>Retained data isn't kept forever.</strong> If you opt in
      to retention, it is still removed after a limited period.</p>
      <p><strong>Third parties.</strong> Cloudflare handles the network
      connection and a spam challenge on this form; the pages you're
      reading load fonts and a 3D graphics library from public CDNs. There
      is no analytics tracking and no advertising on this site.</p>
      <p>Questions or a deletion request — <a href="mailto:$contact_email">$contact_email</a>.</p>
      <div class="landing__notice">
        This site provides information about your brain and how it compares
        to a reference cohort. It is a wellness and informational report only,
        and is not intended to be used or relied on for any other purpose.
      </div>
    </section>

    <section class="landing__section landing__section--wide" id="upload">
      <p class="eyebrow">Upload</p>
      <h2>Get your report.</h2>
      <p>A T1-weighted MRI, as a NIfTI (<code>.nii</code>/<code>.nii.gz</code>)
      or a <code>.zip</code> of a DICOM series. Processing takes roughly an
      hour — give an email address to get the PDF report when it's
      done, or leave this page open and check below.</p>

      <form id="f" class="card" enctype="multipart/form-data">
        <div class="dropzone" data-dropzone>
          <input type="file" name="file" id="file-input" accept=".nii,.nii.gz,.zip" required>
          <label for="file-input" data-dropzone-label>Drop a scan here, or choose a file</label>
        </div>
        <label>Age <input type="number" name="age" min="18" max="90" step="1" required></label>
        <label>Sex
          <select name="sex" required>
            <option value="F">Female</option>
            <option value="M">Male</option>
          </select>
        </label>
        <label>Email (optional) <input type="email" name="email"></label>
        <label><input type="checkbox" name="retain_uploads"> Retain my uploaded scan
          (otherwise it is deleted once processing finishes)</label>
        $turnstile_widget
        <button type="submit" id="submit-btn">Submit</button>
      </form>
      <div id="status" role="status" aria-live="polite"></div>
      <ol id="steps" class="steps"></ol>
      <p class="landing__notice">Uploads over $max_upload_mb MB are rejected.
      This is informational and not a medical assessment.</p>
    </section>

    <footer class="landing__footer">
      <span>&copy; Aevantis</span>
      <div>
        <a href="#privacy">Privacy</a> &middot;
        <a href="mailto:$contact_email">Contact</a>
      </div>
    </footer>

  </div>
  <div class="landing__brain" id="landing-brain-stage" data-scroll-brain></div>
</div>

<script type="module" src="/static/js/landing.js"></script>
<script type="module" src="/static/js/upload.js"></script>
</body></html>
""")

_TURNSTILE_SCRIPT = (
    '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>'
)
_TURNSTILE_WIDGET = Template(
    '<div class="cf-turnstile" data-sitekey="$site_key" style="margin-top:1em"></div>'
)


def render(turnstile_site_key: str | None, max_upload_size_mb: int = 100) -> str:
    if turnstile_site_key:
        script = _TURNSTILE_SCRIPT
        widget = _TURNSTILE_WIDGET.substitute(site_key=turnstile_site_key)
    else:
        script = ""
        widget = ""
    return _PAGE.substitute(
        favicon_link=FAVICON_LINK,
        importmap=_IMPORTMAP,
        fonts_link=FONTS_LINK,
        base_css=BASE_CSS,
        landing_css=LANDING_CSS,
        turnstile_script=script,
        turnstile_widget=widget,
        gap_example_neg=gap_band_html(-4.0, 3.95),
        gap_example_pos=gap_band_html(6.0, 3.95),
        sample_gap_band=gap_band_html(-2.3, 4.03),
        accuracy_table=_accuracy_table_html(),
        people=_people_html(),
        contact_email=CONTACT_EMAIL,
        max_upload_mb=max_upload_size_mb,
    )
