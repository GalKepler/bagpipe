// The region explorer — searchable, groupable, sortable navigation across
// all 432 regions, replacing the ten-row "largest deviations" table that
// used to be the only regional detail in the report.
//
// Two things make it worth its weight over a table. Regions get their
// anatomical names here (static/atlas/region_names.json, derived by
// scripts/build_region_names.py) rather than atlas labels like `LH_Vis_23`.
// And selection is shared with the brain map and the 3D viewer through
// region-bus.js, so the list and the anatomy stay pointed at the same place.
//
// The mini bar in each row is drawn against a fixed ±3σ axis with the ±1σ
// band shaded, so a row's bar is comparable with every other row's and an
// ordinary value is visibly ordinary — a sorted list of numbers alone
// invites reading rank 1 as remarkable when it usually isn't.

import { TOKENS } from "./brand-tokens.js";
import { loadRegionNames, onRegionSelect, selectRegion } from "./region-bus.js";

const ATLAS_PREFIX = "Schaefer2018N400n7Tian2020S2";
const SOURCE = "explorer";
const Z_LIMIT = 3;

const METRIC_LABELS = {
  vol_gm: "Gray matter",
  vol_wm: "White matter",
  vol_csf: "CSF",
  thickness: "Cortical thickness",
  gyrification: "Gyrification",
  sulcal_depth: "Sulcal depth",
  fractal_dimension: "Fractal dimension",
  area: "Surface area",
  bag: "Brain age gap",
};
const METRIC_ORDER = Object.keys(METRIC_LABELS);

// "bag" isn't a z-score (it's the region's own predicted age minus yours,
// in years, from the stacked model's per-region base learner — a different
// quantity from how far the region's raw tissue value sits from the
// cohort norm) — its own axis limit and unit keep the shared bar/color
// helpers below meaningful for both.
const METRIC_SCALE = {
  bag: { limit: 15, unit: "y" },
};
const DEFAULT_SCALE = { limit: Z_LIMIT, unit: "σ" };
function scaleFor(metric) {
  return METRIC_SCALE[metric] || DEFAULT_SCALE;
}

// Each region's BAG comes from a base learner fit on just that region's own
// three tissue features — far less regularized than the full stacked
// meta-learner behind the headline number, so individual regions swing much
// wider (tens of years isn't unusual) even though the global BAG is a few
// years. Shown as-is (not clipped) per maintainer decision, with this note
// so a reader doesn't mistake a single region's swing for the model's
// overall accuracy.
const METRIC_NOTES = {
  bag: "Each region's brain age gap comes from a much smaller, less " +
    "regularized model than the headline number above — individual regions " +
    "can swing by decades even when the overall result is unremarkable. " +
    "Read these as which regions the model weighs as older or younger, not " +
    "as accuracy on the same footing as the headline BAG.",
};

// `meta` is the secondary attribute each row shows: whatever the current
// grouping is NOT already saying, so a row inside "Default mode" reads
// "Frontal" rather than repeating its group's own name 91 times.
const GROUPINGS = {
  network: { label: "Network", key: (r) => r.networkDisplay, meta: (r) => r.lobe },
  lobe: { label: "Lobe", key: (r) => r.lobe, meta: (r) => r.networkDisplay },
  hemisphere: {
    label: "Hemisphere",
    key: (r) => (r.hemisphere === "L" ? "Left" : "Right"),
    meta: (r) => r.networkDisplay,
  },
  none: { label: "Nothing (flat list)", key: () => null, meta: (r) => r.networkDisplay },
};

const SORTS = {
  deviation: { label: "Largest deviation", cmp: (a, b) => Math.abs(b.z) - Math.abs(a.z) },
  above: { label: "Most above norm", cmp: (a, b) => b.z - a.z },
  below: { label: "Most below norm", cmp: (a, b) => a.z - b.z },
  name: { label: "Name (A–Z)", cmp: (a, b) => a.display.localeCompare(b.display) },
};

function zColor(z) {
  return z >= 0 ? TOKENS.warm : TOKENS.cool;
}

function zOpacity(z, limit = Z_LIMIT) {
  return (0.35 + 0.65 * Math.min(Math.abs(z) / limit, 1)).toFixed(2);
}

function fmt(z, unit = "σ") {
  const digits = unit === "y" ? 1 : 2;
  return `${z >= 0 ? "+" : ""}${z.toFixed(digits)}${unit}`;
}

/** `{"<atlas>__<label>__<metric>": z}` -> `{metric: {label: z}}` plus the
 *  metrics actually present, so a future surface-metric model needs no
 *  change here. */
function indexZscores(raw) {
  const byMetric = {};
  for (const [column, z] of Object.entries(raw)) {
    const parts = column.split("__");
    if (parts.length !== 3 || parts[0] !== ATLAS_PREFIX) continue;
    const [, label, metric] = parts;
    (byMetric[metric] ||= {})[label] = z;
  }
  const metrics = METRIC_ORDER.filter((m) => byMetric[m]);
  return { byMetric, metrics };
}

function buildRows(names, byMetric, metric) {
  const values = byMetric[metric] || {};
  return Object.entries(values)
    .map(([label, z]) => {
      const meta = names.regions[label];
      if (!meta) return null;
      return {
        label,
        z,
        display: meta.display,
        short: meta.short,
        anatomy: meta.anatomy,
        network: meta.network,
        networkDisplay: names.networks[meta.network]?.display || meta.network,
        lobe: meta.lobe,
        hemisphere: meta.hemisphere,
        structure: meta.structure,
        coverage: meta.coverage,
        haystack: `${meta.display} ${meta.short} ${meta.lobe} ${
          names.networks[meta.network]?.display || ""
        } ${label}`.toLowerCase(),
      };
    })
    .filter(Boolean);
}

function barSvg(z, limit = Z_LIMIT) {
  const clamped = Math.max(-limit, Math.min(limit, z));
  const centre = 50;
  const half = (clamped / limit) * 50;
  const x = half >= 0 ? centre : centre + half;
  const width = Math.max(Math.abs(half), 0.6);
  const bandHalf = 50 / limit; // one unit of scale either side of centre
  return `
    <svg class="region-row__bar" viewBox="0 0 100 12" preserveAspectRatio="none" aria-hidden="true">
      <rect x="0" y="5" width="100" height="2" fill="var(--line)" fill-opacity="0.5"/>
      <rect x="${centre - bandHalf}" y="1" width="${bandHalf * 2}" height="10"
            fill="var(--line)"/>
      <line x1="${centre}" y1="0" x2="${centre}" y2="12" stroke="var(--muted)" stroke-width="0.6"/>
      <rect x="${x}" y="3.5" width="${width}" height="5" rx="0.5"
            fill="${zColor(z)}" fill-opacity="${zOpacity(z, limit)}"/>
    </svg>`;
}

function rowHtml(row, metric, metrics, byMetric, meta) {
  const scale = scaleFor(metric);
  const others = metrics
    .map((m) => {
      const value = byMetric[m]?.[row.label];
      if (value === undefined) return "";
      const mScale = scaleFor(m);
      return `<span class="region-row__chip"><span class="region-row__chip-label">${
        METRIC_LABELS[m] || m
      }</span><span class="region-row__chip-value" style="color:${zColor(value)}">${fmt(
        value,
        mScale.unit
      )}</span></span>`;
    })
    .join("");

  // Below 60% overlap the parcel genuinely straddles two gyri and its name
  // says so ("Insula / supramarginal gyrus"); flag it rather than let a
  // hedged name read as a confident one.
  const approx =
    row.coverage < 0.6
      ? '<span class="region-row__approx" title="This parcel straddles two anatomical areas">approx.</span>'
      : "";

  return `
    <li class="region-row" data-region="${row.label}">
      <button type="button" class="region-row__button" aria-expanded="false">
        <span class="region-row__name">${row.display}${approx}</span>
        <span class="region-row__meta">${meta(row)}</span>
        ${barSvg(row.z, scale.limit)}
        <span class="region-row__value" style="color:${zColor(row.z)}">${fmt(
          row.z,
          scale.unit
        )}</span>
      </button>
      <div class="region-row__detail" hidden>
        <p class="region-row__detail-line">${row.anatomy} · ${
          row.hemisphere === "L" ? "left" : "right"
        } hemisphere · ${row.lobe.toLowerCase()}</p>
        <div class="region-row__chips">${others}</div>
      </div>
    </li>`;
}

function outlierThreshold(scale) {
  return scale.unit === "y" ? scale.limit / 3 : 2;
}

function groupSummary(rows, scale) {
  const mean = rows.reduce((sum, r) => sum + r.z, 0) / rows.length;
  const beyond = rows.filter((r) => Math.abs(r.z) >= outlierThreshold(scale)).length;
  return { mean, beyond };
}

export function initRegionExplorer() {
  const root = document.querySelector("[data-region-explorer]");
  if (!root) return;

  const raw = JSON.parse(document.getElementById("regional-zscores")?.textContent || "{}");
  const { byMetric, metrics } = indexZscores(raw);

  // Regional BAG isn't a z-score column (`bagpipe.app.pipeline.predict.
  // _regional_bag`) — a separate script tag, keyed directly by region
  // label rather than the atlas__label__metric triple the others use.
  const bag = JSON.parse(document.getElementById("regional-bag")?.textContent || "{}");
  const bagValues = Object.fromEntries(
    Object.entries(bag).map(([label, v]) => [label, v.bag_corrected])
  );
  if (Object.keys(bagValues).length) {
    byMetric.bag = bagValues;
    metrics.push("bag");
  }
  if (!metrics.length) return;

  const searchEl = root.querySelector("[data-explorer-search]");
  const groupEl = root.querySelector("[data-explorer-group]");
  const sortEl = root.querySelector("[data-explorer-sort]");
  const outliersEl = root.querySelector("[data-explorer-outliers]");
  const metricEl = root.querySelector("[data-explorer-metric]");
  const listEl = root.querySelector("[data-explorer-list]");
  const countEl = root.querySelector("[data-explorer-count]");
  const noteEl = root.querySelector("[data-explorer-note]");

  metricEl.innerHTML = metrics
    .map(
      (m, i) =>
        `<button type="button" class="toggle${i === 0 ? " is-active" : ""}" data-metric="${m}">${
          METRIC_LABELS[m] || m
        }</button>`
    )
    .join("");
  groupEl.innerHTML = Object.entries(GROUPINGS)
    .map(([k, g]) => `<option value="${k}">${g.label}</option>`)
    .join("");
  sortEl.innerHTML = Object.entries(SORTS)
    .map(([k, s]) => `<option value="${k}">${s.label}</option>`)
    .join("");

  const state = {
    names: null,
    metric: metrics[0],
    group: "network",
    sort: "deviation",
    query: "",
    outliersOnly: false,
    selected: null,
    collapsed: new Set(),
  };

  function visibleRows() {
    const rows = buildRows(state.names, byMetric, state.metric);
    const query = state.query.trim().toLowerCase();
    const outlierAt = outlierThreshold(scaleFor(state.metric));
    return rows
      .filter((r) => (!query || r.haystack.includes(query)))
      .filter((r) => (!state.outliersOnly || Math.abs(r.z) >= outlierAt))
      .sort(SORTS[state.sort].cmp);
  }

  function render() {
    const note = METRIC_NOTES[state.metric];
    noteEl.textContent = note || "";
    noteEl.hidden = !note;

    const rows = visibleRows();
    countEl.textContent = rows.length
      ? `${rows.length} region${rows.length === 1 ? "" : "s"}`
      : "no regions match";

    if (!rows.length) {
      listEl.innerHTML =
        '<p class="explorer__empty">Nothing matches that filter. Clear the search, or turn off “only beyond ±2σ”.</p>';
      return;
    }

    const grouping = { ...GROUPINGS[state.group] };
    if (state.group === "network") {
      grouping.order = Object.values(state.names.networks).map((n) => n.display);
    } else if (state.group === "hemisphere") {
      grouping.order = ["Left", "Right"];
    }
    if (state.group === "none") {
      listEl.innerHTML = `<ul class="region-list">${rows
        .map((r) => rowHtml(r, state.metric, metrics, byMetric, grouping.meta))
        .join("")}</ul>`;
    } else {
      const groups = new Map();
      for (const row of rows) {
        const key = grouping.key(row);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(row);
      }
      // Group order is fixed by the atlas (networks in region_names.json's own
      // order, everything else alphabetically), not by which region happens to
      // sort first — otherwise changing the sort reshuffles the sections too.
      const ordered = [...groups.entries()].sort(([a], [b]) => {
        const rank = grouping.order || [];
        const ia = rank.indexOf(a);
        const ib = rank.indexOf(b);
        if (ia !== -1 || ib !== -1) return (ia === -1 ? 1e9 : ia) - (ib === -1 ? 1e9 : ib);
        return a.localeCompare(b);
      });
      listEl.innerHTML = ordered
        .map(([name, groupRows]) => {
          const scale = scaleFor(state.metric);
          const { mean, beyond } = groupSummary(groupRows, scale);
          const collapsed = state.collapsed.has(name);
          return `
            <section class="region-group" data-group="${name}">
              <button type="button" class="region-group__head" aria-expanded="${!collapsed}">
                <span class="region-group__caret" aria-hidden="true">${collapsed ? "▸" : "▾"}</span>
                <span class="region-group__name">${name}</span>
                <span class="region-group__stat">${groupRows.length} regions</span>
                <span class="region-group__stat">mean <span style="color:${zColor(mean)}">${fmt(
                  mean,
                  scale.unit
                )}</span></span>
                <span class="region-group__stat">${beyond} beyond &plusmn;${outlierThreshold(
                  scale
                )}${scale.unit}</span>
              </button>
              <ul class="region-list"${collapsed ? " hidden" : ""}>${groupRows
                .map((r) => rowHtml(r, state.metric, metrics, byMetric, grouping.meta))
                .join("")}</ul>
            </section>`;
        })
        .join("");
    }
    if (state.selected) highlight(state.selected, false);
  }

  function highlight(label, scroll) {
    root.querySelectorAll(".region-row.is-selected").forEach((el) => {
      el.classList.remove("is-selected");
      el.querySelector(".region-row__detail").hidden = true;
      el.querySelector(".region-row__button").setAttribute("aria-expanded", "false");
    });
    const el = root.querySelector(`.region-row[data-region="${label}"]`);
    if (!el) return;
    el.classList.add("is-selected");
    el.querySelector(".region-row__detail").hidden = false;
    el.querySelector(".region-row__button").setAttribute("aria-expanded", "true");
    if (scroll) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  listEl.addEventListener("click", (event) => {
    const head = event.target.closest(".region-group__head");
    if (head) {
      const name = head.parentElement.dataset.group;
      state.collapsed.has(name) ? state.collapsed.delete(name) : state.collapsed.add(name);
      render();
      return;
    }
    const button = event.target.closest(".region-row__button");
    if (!button) return;
    const label = button.parentElement.dataset.region;
    state.selected = state.selected === label ? null : label;
    if (state.selected) {
      highlight(label, false);
      selectRegion(label, SOURCE);
    } else {
      render();
    }
  });

  searchEl.addEventListener("input", () => {
    state.query = searchEl.value;
    render();
  });
  groupEl.addEventListener("change", () => {
    state.group = groupEl.value;
    render();
  });
  sortEl.addEventListener("change", () => {
    state.sort = sortEl.value;
    render();
  });
  outliersEl.addEventListener("change", () => {
    state.outliersOnly = outliersEl.checked;
    render();
  });
  metricEl.addEventListener("click", (event) => {
    const button = event.target.closest("[data-metric]");
    if (!button) return;
    metricEl.querySelectorAll(".toggle").forEach((b) => b.classList.toggle("is-active", b === button));
    state.metric = button.dataset.metric;
    render();
  });

  onRegionSelect(({ label, source }) => {
    if (source === SOURCE) return;
    state.selected = label;
    // A region picked on the brain map may be filtered out of the current
    // view; drop the filters that would hide it rather than silently doing
    // nothing when the user clicks anatomy and expects the list to follow.
    const known = state.names.regions[label];
    if (known && (state.query || state.outliersOnly)) {
      const stillVisible = visibleRows().some((r) => r.label === label);
      if (!stillVisible) {
        state.query = "";
        searchEl.value = "";
        state.outliersOnly = false;
        outliersEl.checked = false;
      }
    }
    if (known) state.collapsed.delete(GROUPINGS[state.group].key({
      networkDisplay: state.names.networks[known.network]?.display || known.network,
      lobe: known.lobe,
      hemisphere: known.hemisphere,
    }));
    render();
    highlight(label, true);
  });

  loadRegionNames().then((names) => {
    state.names = names;
    render();
  });
}

document.addEventListener("DOMContentLoaded", initRegionExplorer);
