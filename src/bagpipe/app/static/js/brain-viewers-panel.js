// Wires cortex-viewer.js + volume-viewer.js into the results page's "3D
// brain" section (bagpipe.app.results_page). Builds the {regionId: value}
// map both viewers' setRegionValues() expect from the same
// `regional-zscores` JSON script tag brainmap.js reads, via the same
// Schaefer2018N400n7Tian2020S2 atlas manifest — cortex-viewer's mesh is now
// resampled onto this exact atlas (scripts/export_surface_mesh.py), so both
// viewers share one region-id space and get the same map.

import { VolumeViewer } from "./volume-viewer.js";
import { CortexViewer } from "./cortex-viewer.js";

const ATLAS_PREFIX = "Schaefer2018N400n7Tian2020S2";

function readJsonScript(id) {
  const el = document.getElementById(id);
  return el ? JSON.parse(el.textContent) : {};
}

async function loadManifest() {
  const [cortical, subcortical] = await Promise.all([
    fetch("/static/atlas/cortical_manifest.json").then((r) => r.json()),
    fetch("/static/atlas/subcortical_manifest.json").then((r) => r.json()),
  ]);
  return { ...cortical, ...subcortical };
}

function buildRegionValues(manifest, zscores, tissue) {
  const values = {};
  for (const [id, meta] of Object.entries(manifest)) {
    const key = `${ATLAS_PREFIX}__${meta.label}__${tissue}`;
    if (key in zscores) values[id] = zscores[key];
  }
  return values;
}

function init() {
  const root = document.querySelector("[data-brain-viewers]");
  if (!root) return;

  const jobId = root.dataset.jobId;
  const volumeAvailable = root.dataset.volumeAvailable === "true";
  const zscores = readJsonScript("regional-zscores");

  wireTabs(root);

  let volumeViewer = null;
  if (volumeAvailable) {
    volumeViewer = new VolumeViewer(root.querySelector("[data-bv-volume-stage]"), {
      t1Url: `/jobs/${jobId}/volume/t1.nii`,
      atlasUrl: "/atlas/volume.nii",
    });
    wireHover(volumeViewer, root.querySelector("[data-bv-volume-hover]"));
  }

  const cortexViewer = new CortexViewer(root.querySelector("[data-bv-cortex-stage]"), {
    glbUrl: "/static/mesh/cortex.glb",
  });
  wireHover(cortexViewer, root.querySelector("[data-bv-cortex-hover]"));

  let manifest = null;
  let currentTissue = "vol_gm";

  async function applyTissue(tissue) {
    currentTissue = tissue;
    manifest ??= await loadManifest();
    const values = buildRegionValues(manifest, zscores, currentTissue);
    volumeViewer?.setRegionValues(values);
    cortexViewer.setRegionValues(values);
  }

  wireToggleGroup(root.querySelectorAll("[data-bv-tissue] .bv-toggle"), (btn) =>
    applyTissue(btn.dataset.tissue),
  );
  applyTissue(currentTissue);

  const opacityInput = root.querySelector("[data-bv-opacity]");
  if (opacityInput && volumeViewer) {
    opacityInput.addEventListener("input", (e) => {
      volumeViewer.atlasOpacity = Number(e.target.value);
      applyTissue(currentTissue);
    });
  } else if (opacityInput && !volumeAvailable) {
    opacityInput.closest("[data-bv-opacity-row]")?.setAttribute("hidden", "");
  }

  wireScrollRotation(cortexViewer, root);
}

function wireTabs(root) {
  const tabs = root.querySelectorAll("[data-bv-tab]");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.toggle("is-active", t === tab));
      root.querySelectorAll("[data-bv-panel]").forEach((panel) => {
        panel.classList.toggle("is-active", panel.dataset.bvPanel === tab.dataset.bvTab);
      });
    });
  });
}

function wireToggleGroup(buttons, onSelect) {
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => b.classList.toggle("is-active", b === btn));
      onSelect(btn);
    });
  });
}

function wireHover(viewer, labelEl) {
  if (!labelEl) return;
  viewer.addEventListener("regionhover", (e) => {
    const id = e.detail.regionId;
    labelEl.textContent = id == null ? " " : `Region ${id}`;
  });
}

const REDUCED_MOTION = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

function wireScrollRotation(cortexViewer, root) {
  if (REDUCED_MOTION) return;
  function onScroll() {
    const rect = root.getBoundingClientRect();
    const viewport = window.innerHeight || document.documentElement.clientHeight;
    const t = 1 - Math.min(1, Math.max(0, rect.top / viewport));
    cortexViewer.setScrollProgress(t);
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
