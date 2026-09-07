// Clickable brain-region map for a single scan's results page. Loads static
// atlas SVGs + manifest (bagpipe.app.static.atlas, generated once from the
// Schaefer400+TianS2 atlas — same atlas the production model trains on),
// colors each region by z-score severity, and shows per-metric z-scores on
// click. Region ids in the SVG (`region-<atlas index>`) look up the manifest
// for `label`, which is the join key into the regional z-score map embedded
// in the page (`Schaefer2018N400n7Tian2020S2__<label>__<metric>` keys,
// matching `bagpipe.app.normative.regional_zscores`).

const ATLAS_PREFIX = "Schaefer2018N400n7Tian2020S2";
const METRICS = [
  { key: "vol_gm", label: "Gray matter" },
  { key: "vol_wm", label: "White matter" },
  { key: "vol_csf", label: "CSF" },
];

const ATLAS_CACHE = {};

// Yeo-7 network colors (Yeo et al. 2011 / FreeSurfer Yeo2011_7Networks_ColorLUT).
const YEO7_COLORS = {
  Vis: "rgb(120, 18, 134)",
  SomMot: "rgb(70, 130, 180)",
  DorsAttn: "rgb(0, 118, 14)",
  SalVentAttn: "rgb(196, 58, 250)",
  Limbic: "rgb(220, 248, 164)",
  Cont: "rgb(230, 148, 34)",
  Default: "rgb(205, 62, 78)",
};

function severityFromZ(z) {
  const az = Math.abs(z);
  if (az >= 2) return "high";
  if (az >= 1) return "mid";
  return "low";
}

// Diverging cool<->warm ramp keyed to z-score, breakpoints at -3,-1,0,1,3 so the
// typical -1..+1 range stays near-neutral and only real outliers stand out.
// Same tokens as everywhere else on the site (docs/design-brief.md §3,
// static/js/brand-tokens.js): cool = below norm, warm = above norm — the
// only saturated colors on the page are ones reporting actual data.
import { TOKENS, hexToRGB255 } from "./js/brand-tokens.js";
import { loadRegionNames, onRegionSelect, selectRegion } from "./js/region-bus.js";

const SOURCE = "brainmap";

const DIVERGE_BREAKPOINTS = [-3, -1, 0, 1, 3];
const DIVERGE_STOPS = [
  hexToRGB255(TOKENS.cool),
  hexToRGB255(TOKENS.cool).map((c, i) => Math.round((c + hexToRGB255(TOKENS.muted)[i]) / 2)),
  hexToRGB255(TOKENS.muted), // neutral
  hexToRGB255(TOKENS.warm).map((c, i) => Math.round((c + hexToRGB255(TOKENS.muted)[i]) / 2)),
  hexToRGB255(TOKENS.warm),
];

function lerpRgb(a, b, t) {
  return [0, 1, 2].map((i) => Math.round(a[i] + (b[i] - a[i]) * t));
}

function zToColor(z) {
  const clamped = Math.max(DIVERGE_BREAKPOINTS[0], Math.min(DIVERGE_BREAKPOINTS[4], z));
  for (let i = 0; i < DIVERGE_BREAKPOINTS.length - 1; i++) {
    const z0 = DIVERGE_BREAKPOINTS[i];
    const z1 = DIVERGE_BREAKPOINTS[i + 1];
    if (clamped <= z1) {
      const [r, g, b] = lerpRgb(DIVERGE_STOPS[i], DIVERGE_STOPS[i + 1], (clamped - z0) / (z1 - z0));
      return `rgb(${r}, ${g}, ${b})`;
    }
  }
  const [r, g, b] = DIVERGE_STOPS[4];
  return `rgb(${r}, ${g}, ${b})`;
}

async function loadAtlas(atlas) {
  if (ATLAS_CACHE[atlas]) return ATLAS_CACHE[atlas];
  const manifest = await fetch(`/static/atlas/${atlas}_manifest.json`).then((r) => r.json());
  ATLAS_CACHE[atlas] = { manifest, svgByView: {} };
  return ATLAS_CACHE[atlas];
}

async function loadViewSvg(atlas, view) {
  const cached = await loadAtlas(atlas);
  if (!cached.svgByView[view]) {
    cached.svgByView[view] = await fetch(`/static/atlas/${atlas}_${view}.svg`).then((r) => r.text());
  }
  return cached.svgByView[view];
}

function readJsonScript(id) {
  const el = document.getElementById(id);
  return el ? JSON.parse(el.textContent) : {};
}

function zKey(label, metricKey) {
  return `${ATLAS_PREFIX}__${label}__${metricKey}`;
}

function paintRegions(container, manifest, zscores, tissue, colorMode) {
  container.querySelectorAll('path[id^="region-"]').forEach((path) => {
    const index = path.id.replace("region-", "");
    const meta = manifest[index];
    if (!meta) {
      path.style.fill = "var(--color-border)";
      return;
    }
    if (colorMode === "network") {
      path.style.fill = YEO7_COLORS[meta.network] || "var(--color-border)";
      return;
    }
    const z = zscores[zKey(meta.label, tissue)];
    path.style.fill = z === undefined ? "var(--color-border)" : zToColor(z);
  });
}

function renderDeviationLegend(legendEl) {
  legendEl.hidden = false;
  // Built from zToColor's own stops rather than a hand-written gradient: the
  // legend was a hardcoded blue-to-red ramp while the regions were painted
  // teal-to-amber, so the key did not describe the map it belonged to.
  const gradient = DIVERGE_BREAKPOINTS.map(
    (z, i) => `${zToColor(z)} ${(i / (DIVERGE_BREAKPOINTS.length - 1)) * 100}%`
  ).join(", ");
  legendEl.innerHTML = `
    <div class="colorbar">
      <div class="colorbar__row">
        <span class="colorbar__label">Below norm</span>
        <div class="colorbar__track" style="background: linear-gradient(to right, ${gradient})"></div>
        <span class="colorbar__label">Above norm</span>
      </div>
      <div class="colorbar__ticks">
        <span>&minus;3&sigma;</span><span>&minus;1&sigma;</span><span>0</span><span>+1&sigma;</span><span>+3&sigma;</span>
      </div>
    </div>
  `;
}

function renderLegend(legendEl, colorMode, atlas) {
  if (colorMode === "deviation") {
    renderDeviationLegend(legendEl);
    return;
  }
  legendEl.hidden = false;
  if (atlas !== "cortical") {
    legendEl.innerHTML =
      '<p class="brainmap__legend-note">Subcortical ROIs (Tian S2) aren\'t assigned to a functional network.</p>';
    return;
  }
  legendEl.innerHTML = Object.entries(YEO7_COLORS)
    .map(
      ([network, color]) =>
        `<span class="legend-swatch"><span class="legend-swatch__dot" style="background:${color}"></span>${network}</span>`
    )
    .join("");
}

function renderDetail(detailEl, meta, zscores, names) {
  const rows = METRICS.map(({ key, label }) => {
    const z = zscores[zKey(meta.label, key)];
    if (z === undefined) return "";
    const sev = severityFromZ(z);
    return `
      <div class="zscore-row">
        <span class="zscore-row__label">${label}</span>
        <span class="badge badge--${sev}">${z >= 0 ? "+" : ""}${z.toFixed(2)}&sigma;</span>
      </div>
    `;
  }).join("");

  // The atlas label (`LH_Vis_23`) is a join key, not a name — show the
  // anatomical name from region_names.json and keep the label only as the
  // small print, for anyone matching this against the atlas itself.
  const named = names?.regions?.[meta.label];
  const title = named ? named.display : meta.label;
  const network = named
    ? names.networks[named.network]?.display || named.network
    : meta.network;

  detailEl.innerHTML = `
    <h3 class="brainmap__detail-title">${title}</h3>
    <p class="brainmap__detail-network">${meta.hemisphere === "L" ? "Left" : "Right"} hemisphere
      ${network ? "&middot; " + network : ""}
      ${named && named.coverage < 0.6 ? "&middot; spans two areas" : ""}</p>
    ${rows || '<p class="brainmap__detail-placeholder">No z-score for this region.</p>'}
    <p class="brainmap__detail-label">${meta.label}</p>
  `;
}

function initBrainmap() {
  const root = document.querySelector("[data-brainmap]");
  if (!root) return;

  const zscores = readJsonScript("regional-zscores");
  let regionNames = null;
  loadRegionNames().then((names) => {
    regionNames = names;
  });
  const svgContainer = root.querySelector("[data-brainmap-svg]");
  const detailEl = root.querySelector("[data-brainmap-detail]");
  const legendEl = root.querySelector("[data-brainmap-legend]");
  const hemiContainers = {
    left: svgContainer.querySelector('[data-hemi-svg="left"]'),
    right: svgContainer.querySelector('[data-hemi-svg="right"]'),
  };

  const tissueButtons = root.querySelectorAll("[data-tissue]");
  const atlasButtons = root.querySelectorAll("[data-atlas]");
  const surfaceButtons = root.querySelectorAll("[data-surface]");
  const colorButtons = root.querySelectorAll("[data-color]");

  let currentTissue = "vol_gm";
  let currentAtlas = "cortical";
  let currentSurface = "lateral";
  let currentColorMode = "deviation";
  let selectedPath = null;

  async function render() {
    const { manifest } = await loadAtlas(currentAtlas);
    await Promise.all(
      ["left", "right"].map(async (hemi) => {
        const container = hemiContainers[hemi];
        container.innerHTML = await loadViewSvg(currentAtlas, `${hemi}_${currentSurface}`);
        const svg = container.querySelector("svg");
        if (svg) {
          svg.removeAttribute("width");
          svg.removeAttribute("height");
        }
        paintRegions(container, manifest, zscores, currentTissue, currentColorMode);
      })
    );
    renderLegend(legendEl, currentColorMode, currentAtlas);
    selectedPath = null;
    detailEl.innerHTML = '<p class="brainmap__detail-placeholder">Click a region to see its z-scores.</p>';
  }

  async function select(meta, path) {
    if (selectedPath) selectedPath.classList.remove("is-selected");
    if (path) {
      path.classList.add("is-selected");
      selectedPath = path;
    } else {
      selectedPath = null;
    }
    renderDetail(detailEl, meta, zscores, regionNames);
  }

  svgContainer.addEventListener("click", async (event) => {
    const path = event.target.closest('path[id^="region-"]');
    if (!path) return;
    const { manifest } = await loadAtlas(currentAtlas);
    const meta = manifest[path.id.replace("region-", "")];
    if (!meta) return;
    await select(meta, path);
    selectRegion(meta.label, SOURCE);
  });

  // A region picked in the explorer (or the 3D viewer) has to be findable
  // here even when it lives in the other atlas — switching to it is what a
  // reader expects from clicking a subcortical row while the cortex is shown.
  onRegionSelect(async ({ label, source }) => {
    if (source === SOURCE) return;
    const targetAtlas = label.includes("-lh") || label.includes("-rh") ? "subcortical" : "cortical";
    if (targetAtlas !== currentAtlas) {
      currentAtlas = targetAtlas;
      atlasButtons.forEach((b) => b.classList.toggle("is-active", b.dataset.atlas === targetAtlas));
      await render();
    }
    const { manifest } = await loadAtlas(currentAtlas);
    const entry = Object.entries(manifest).find(([, meta]) => meta.label === label);
    if (!entry) return;
    const [index, meta] = entry;
    // The parcel may not be on the currently-shown surface (a medial region
    // while "Lateral" is selected); the detail panel still updates, which is
    // the part carrying the numbers.
    const path = svgContainer.querySelector(`path[id="region-${index}"]`);
    await select(meta, path);
  });

  function wireToggle(buttons, onSelect) {
    buttons.forEach((btn) =>
      btn.addEventListener("click", () => {
        buttons.forEach((b) => b.classList.toggle("is-active", b === btn));
        onSelect(btn);
        render();
      })
    );
  }
  wireToggle(tissueButtons, (btn) => (currentTissue = btn.dataset.tissue));
  wireToggle(atlasButtons, (btn) => (currentAtlas = btn.dataset.atlas));
  wireToggle(surfaceButtons, (btn) => (currentSurface = btn.dataset.surface));
  wireToggle(colorButtons, (btn) => (currentColorMode = btn.dataset.color));

  render();
}

document.addEventListener("DOMContentLoaded", initBrainmap);
