"""The public upload page served at `GET /` — a plain HTML form + vanilla JS
poll loop, no frontend framework/build step (same "stdlib templating, no new
dependency" reasoning as `bagpipe.app.report`). This is the only way a
non-technical member of the public can actually use `/predict`; the JSON API
alone assumes a technical caller.
"""

from __future__ import annotations

from string import Template

from bagpipe.app.style import BASE_CSS, FAVICON_LINK, FONTS_LINK

_PAGE = Template("""<!doctype html>
<html><head><meta charset="utf-8"><title>Brain Age Gap</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
$favicon_link
$fonts_link
$turnstile_script
<style>$base_css</style></head>
<body>
<div class="brand"><img src="/static/logo-icon.png" alt=""><span>Bagpipe</span></div>
<h1>Brain Age Gap report</h1>
<p class="muted">Upload a T1-weighted MRI (NIfTI <code>.nii</code>/<code>.nii.gz</code>,
or a <code>.zip</code> of a DICOM series). Processing takes roughly an hour;
give an email address to get the PDF report when it's done, or leave this
page open and poll below.</p>

<form id="f" class="card">
  <label>Scan file <input type="file" name="file" required></label>
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
<div id="status"></div>
<ol id="steps" class="steps"></ol>

<script>
const f = document.getElementById('f');
const btn = document.getElementById('submit-btn');
const statusEl = document.getElementById('status');
const stepsEl = document.getElementById('steps');

function setStatus(state, html) {
  statusEl.className = 'visible state-' + state;
  statusEl.innerHTML = html;
}

function renderSteps(doneCount, failed) {
  stepsEl.innerHTML = STAGE_ORDER.map((name, i) => {
    const cls = failed && i === doneCount ? 'step--failed'
      : i < doneCount ? 'step--done'
      : i === doneCount ? 'step--current'
      : '';
    return '<li class="step ' + cls + '"><span class="step__icon"></span>'
      + '<span class="step__label">' + (STAGE_LABELS[name] || name) + '</span></li>';
  }).join('');
}

f.addEventListener('submit', async (e) => {
  e.preventDefault();
  btn.disabled = true;
  setStatus('uploading', '<span class="spinner"></span>Uploading...');
  const fd = new FormData(f);
  fd.set('retain_uploads', f.retain_uploads.checked ? 'true' : 'false');
  let resp;
  try {
    resp = await fetch('/predict', { method: 'POST', body: fd });
  } catch (err) {
    btn.disabled = false;
    setStatus('failed', 'Network error: ' + err);
    return;
  }
  if (!resp.ok) {
    btn.disabled = false;
    setStatus('failed', 'Error: ' + (await resp.text()));
    return;
  }
  const { job_id } = await resp.json();
  history.replaceState(null, '', '?job=' + job_id);
  setStatus('queued',
    '<span class="spinner"></span>Queued as ' + job_id
    + '. Processing (this can take about an hour)...');
  poll(job_id);
});

const resumeJobId = new URLSearchParams(location.search).get('job');
if (resumeJobId) {
  f.style.display = 'none';
  setStatus('processing', '<span class="spinner"></span>Resuming status for ' + resumeJobId + '...');
  poll(resumeJobId);
}

const STAGE_ORDER = ['ingest', 'anonymize', 'segment', 'qc_gate', 'extract_features', 'predict', 'report'];
const STAGE_LABELS = {
  ingest: 'reading scan', anonymize: 'defacing', segment: 'CAT12 segmentation (slowest step)',
  qc_gate: 'quality check', extract_features: 'extracting features', predict: 'predicting brain age',
  report: 'building report',
};

async function poll(jobId) {
  const resp = await fetch('/jobs/' + jobId);
  const body = await resp.json();
  const done = body.stages.length;
  if (body.status === 'succeeded') {
    btn.disabled = false;
    renderSteps(done, false);
    setStatus('succeeded',
      'Done. Brain Age Gap: <strong>' + body.result.bag_corrected.toFixed(1) + ' years</strong>'
      + (f.email.value ? ' (also emailed to you). ' : '. ')
      + '<a href="/jobs/' + jobId + '/view">View your interactive results &rarr;</a>');
  } else if (body.status === 'failed') {
    btn.disabled = false;
    renderSteps(done, true);
    setStatus('failed', 'Failed: ' + (body.error ? body.error.user_message : 'unknown error'));
  } else {
    renderSteps(done, false);
    const current = STAGE_ORDER[done];
    const label = current ? (STAGE_LABELS[current] || current) : 'finishing up';
    setStatus('processing',
      '<span class="spinner"></span>Step ' + (done + 1) + '/' + STAGE_ORDER.length
      + ': ' + label + ' ... (checking again in 30s)');
    setTimeout(() => poll(jobId), 30000);
  }
}
</script>
</body></html>
""")

_TURNSTILE_SCRIPT = (
    '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>'
)
_TURNSTILE_WIDGET = Template(
    '<div class="cf-turnstile" data-sitekey="$site_key" style="margin-top:1em"></div>'
)


def render(turnstile_site_key: str | None) -> str:
    if turnstile_site_key:
        script = _TURNSTILE_SCRIPT
        widget = _TURNSTILE_WIDGET.substitute(site_key=turnstile_site_key)
    else:
        script = ""
        widget = ""
    return _PAGE.substitute(
        favicon_link=FAVICON_LINK,
        fonts_link=FONTS_LINK,
        base_css=BASE_CSS,
        turnstile_script=script,
        turnstile_widget=widget,
    )
