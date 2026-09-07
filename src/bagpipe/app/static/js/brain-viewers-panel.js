// Wires cortex-viewer.js + volume-viewer.js into the results page's "3D
// brain" section (bagpipe.app.results_page). Builds the {regionId: value}
// map both viewers' setRegionValues() expect from the same
// `regional-zscores` JSON script tag brainmap.js reads, via the same
// Schaefer2018N400n7Tian2020S2 atlas manifest — cortex-viewer's mesh is now
// resampled onto this exact atlas (scripts/export_surface_mesh.py), so both
// viewers share one region-id space and get the same map.

import { VolumeViewer } from "./volume-viewer.js";
import { CortexViewer } from "./cortex-viewer.js";
import { loadRegionNames, selectRegion } from "./region-bus.js";

const ATLAS_PREFIX = "Schaefer2018N400n7Tian2020S2";
const SOURCE = "brain3d";

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
    wireHover(volumeViewer, root.querySelector("[data-bv-volume-hover]"), root, "volume");
  }

  const cortexViewer = new CortexViewer(root.querySelector("[data-bv-cortex-stage]"), {
    glbUrl: "/static/mesh/cortex.glb",
    interactive: true, // drag-to-rotate — this panel is persistent, not a scroll-hero
  });
  wireHover(cortexViewer, root.querySelector("[data-bv-cortex-hover]"), root, "cortex");

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

// Hovering the 3D brain used to read out "Region 217". Both viewers key on
// the atlas ROIid, and region_names.json is indexed by atlas label, so the
// manifests bridge the two — the same join the brain map already does.
async function buildIdToName() {
  const [manifest, names] = await Promise.all([loadManifest(), loadRegionNames()]);
  const byId = {};
  for (const [id, meta] of Object.entries(manifest)) {
    const named = names.regions[meta.label];
    if (named) byId[id] = { display: named.display, label: meta.label };
  }
  return byId;
}

let idToNamePromise = null;

function wireHover(viewer, labelEl, root, which) {
  if (!labelEl) return;
  idToNamePromise ??= buildIdToName();
  let names = {};
  let hoveredId = null;
  idToNamePromise.then((map) => {
    names = map;
  });

  viewer.addEventListener("regionhover", (e) => {
    hoveredId = e.detail.regionId;
    const named = hoveredId == null ? null : names[hoveredId];
    labelEl.textContent = named
      ? named.display
      : hoveredId == null
        ? " "
        : `Region ${hoveredId}`;
  });

  // Clicking the anatomy selects it everywhere else on the page. The viewers
  // expose hover but not click, so the stage element carries the click and
  // the last hover says what was under the cursor — no viewer change needed.
  const stage = root.querySelector(`[data-bv-${which}-stage]`);
  stage?.addEventListener("click", () => {
    const named = hoveredId == null ? null : names[hoveredId];
    if (named) selectRegion(named.label, SOURCE);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
