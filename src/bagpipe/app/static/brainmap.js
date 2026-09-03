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

// Diverging blue<->red ramp keyed to z-score, breakpoints at -3,-1,0,1,3 so the
// typical -1..+1 range stays near-neutral and only real outliers stand out.
const DIVERGE_BREAKPOINTS = [-3, -1, 0, 1, 3];
const DIVERGE_STOPS = [
  [28, 92, 171], // below norm
  [134, 182, 239],
  [217, 213, 197], // neutral
  [235, 169, 159],
  [171, 58, 69], // above norm
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
  legendEl.innerHTML = `
    <div class="colorbar">
      <div class="colorbar__row">
        <span class="colorbar__label">Below norm</span>
        <div class="colorbar__track" style="background: linear-gradient(to right, rgb(28,92,171), rgb(134,182,239) 33.3%, rgb(217,213,197) 50%, rgb(235,169,159) 66.6%, rgb(171,58,69))"></div>
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

function renderDetail(detailEl, meta, zscores) {
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

  detailEl.innerHTML = `
    <h3 class="brainmap__detail-title">${meta.label}</h3>
    <p class="brainmap__detail-network">${meta.hemisphere === "L" ? "Left" : "Right"} hemisphere
      ${meta.network && meta.network !== "subcortex" ? "&middot; " + meta.network + " network" : ""}</p>
    ${rows || '<p class="brainmap__detail-placeholder">No z-score for this region.</p>'}
  `;
}

function initBrainmap() {
  const root = document.querySelector("[data-brainmap]");
  if (!root) return;

  const zscores = readJsonScript("regional-zscores");
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

  svgContainer.addEventListener("click", async (event) => {
    const path = event.target.closest('path[id^="region-"]');
    if (!path) return;
    const { manifest } = await loadAtlas(currentAtlas);
    const meta = manifest[path.id.replace("region-", "")];
    if (!meta) return;

    if (selectedPath) selectedPath.classList.remove("is-selected");
    path.classList.add("is-selected");
    selectedPath = path;
    renderDetail(detailEl, meta, zscores);
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
