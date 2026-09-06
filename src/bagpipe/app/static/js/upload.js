// Upload form + status poll loop for the landing page's #upload section.
// Same wire contract as the old upload_page.py's inline script (moved out
// verbatim, not rewritten) — field names, `?job=` resume, 30s poll interval.

const f = document.getElementById("f");
const btn = document.getElementById("submit-btn");
const statusEl = document.getElementById("status");
const stepsEl = document.getElementById("steps");

function setStatus(state, html) {
  statusEl.className = "visible state-" + state;
  statusEl.innerHTML = html;
}

const STAGE_ORDER = ["ingest", "anonymize", "segment", "qc_gate", "extract_features", "predict", "report"];
const STAGE_LABELS = {
  ingest: "reading scan",
  anonymize: "defacing",
  segment: "CAT12 segmentation (slowest step)",
  qc_gate: "quality check",
  extract_features: "extracting features",
  predict: "predicting brain age",
  report: "building report",
};

function renderSteps(doneCount, failed) {
  stepsEl.innerHTML = STAGE_ORDER.map((name, i) => {
    const cls = failed && i === doneCount
      ? "step--failed"
      : i < doneCount
        ? "step--done"
        : i === doneCount
          ? "step--current"
          : "";
    return (
      '<li class="step ' + cls + '"><span class="step__icon"></span>' +
      '<span class="step__label">' + (STAGE_LABELS[name] || name) + "</span></li>"
    );
  }).join("");
}

if (f) {
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    btn.disabled = true;
    setStatus("uploading", '<span class="spinner"></span>Uploading...');
    const fd = new FormData(f);
    fd.set("retain_uploads", f.retain_uploads.checked ? "true" : "false");
    let resp;
    try {
      resp = await fetch("/predict", { method: "POST", body: fd });
    } catch (err) {
      btn.disabled = false;
      setStatus("failed", "Network error: " + err);
      return;
    }
    if (!resp.ok) {
      btn.disabled = false;
      setStatus("failed", "Error: " + (await resp.text()));
      return;
    }
    const { job_id } = await resp.json();
    history.replaceState(null, "", "?job=" + job_id);
    setStatus(
      "queued",
      '<span class="spinner"></span>Queued as ' + job_id + ". Processing (this can take about an hour)..."
    );
    poll(job_id);
  });

  const resumeJobId = new URLSearchParams(location.search).get("job");
  if (resumeJobId) {
    f.style.display = "none";
    setStatus("processing", '<span class="spinner"></span>Resuming status for ' + resumeJobId + "...");
    poll(resumeJobId);
  }
}

let pollFailures = 0;
const MAX_POLL_FAILURES = 5;

async function poll(jobId) {
  let resp, body;
  try {
    resp = await fetch("/jobs/" + jobId);
    body = await resp.json();
  } catch (err) {
    body = null;
  }
  if (!resp || !resp.ok || !body || !Array.isArray(body.stages)) {
    pollFailures++;
    if (pollFailures >= MAX_POLL_FAILURES) {
      btn.disabled = false;
      setStatus(
        "failed",
        "Lost contact with the server while checking status. Your job may still be " +
          "processing — reload this page (it will resume from the URL) to check again."
      );
      return;
    }
    setStatus("processing", '<span class="spinner"></span>Still checking status... (retrying)');
    setTimeout(() => poll(jobId), 30000);
    return;
  }
  pollFailures = 0;

  const done = body.stages.length;
  if (body.status === "succeeded") {
    btn.disabled = false;
    renderSteps(done, false);
    setStatus(
      "succeeded",
      "Done. Brain Age Gap: <strong>" + body.result.bag_corrected.toFixed(1) + " years</strong>" +
        (f.email.value ? " (also emailed to you). " : ". ") +
        '<a href="/jobs/' + jobId + '/view">View your interactive results &rarr;</a>' +
        ' &middot; <a href="/jobs/' + jobId + '/report.pdf">Download PDF report</a>'
    );
  } else if (body.status === "failed") {
    btn.disabled = false;
    renderSteps(done, true);
    setStatus("failed", "Failed: " + (body.error ? body.error.user_message : "unknown error"));
  } else if (body.status === "queued") {
    renderSteps(0, false);
    setStatus(
      "queued",
      '<span class="spinner"></span>Waiting in queue for a free processing slot... (checking again in 30s)'
    );
    setTimeout(() => poll(jobId), 30000);
  } else {
    renderSteps(done, false);
    const current = STAGE_ORDER[done];
    const label = current ? (STAGE_LABELS[current] || current) : "finishing up";
    setStatus(
      "processing",
      '<span class="spinner"></span>Step ' + (done + 1) + "/" + STAGE_ORDER.length + ": " + label +
        " ... (checking again in 30s)"
    );
    setTimeout(() => poll(jobId), 30000);
  }
}

// Drag-and-drop feedback + chosen-filename label for the dropzone. Purely
// cosmetic — the underlying <input type="file"> still does the real work.
const dropzone = document.querySelector("[data-dropzone]");
if (dropzone) {
  const input = dropzone.querySelector('input[type="file"]');
  const label = dropzone.querySelector("[data-dropzone-label]");
  const defaultLabel = label.textContent;
  input.addEventListener("change", () => {
    label.textContent = input.files[0] ? input.files[0].name : defaultLabel;
  });
  ["dragenter", "dragover"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("is-dragover");
    })
  );
  ["dragleave", "drop"].forEach((evt) =>
    dropzone.addEventListener(evt, () => dropzone.classList.remove("is-dragover"))
  );
}
