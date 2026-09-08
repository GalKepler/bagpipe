// Wiring for the landing page's cortex viewer. The brain is a single
// instance, pinned in a sticky panel on the right for the whole page
// (docs/design-brief.md §5 — see style.py's `.landing__brain` for the
// sticky positioning itself). Rotation is user-driven (click-drag orbit,
// see cortex-viewer.js's OrbitControls), not scroll-tied.
//
// Scroll reveals live in reveal.js (shared with every other page); CTA
// buttons are plain <a href> links, not JS-driven smooth-scroll.

import { CortexViewer } from "./cortex-viewer.js";

// Tiny deterministic PRNG (mulberry32) rather than Math.random() — this is
// the illustrative "sample report" brain the landing page's copy promises
// (not a real participant), and a fixed seed means every visitor sees the
// same demonstration instead of a different-looking pattern per pageload.
function mulberry32(seed) {
  return function () {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function syntheticRegionValues(regionIds) {
  const rand = mulberry32(20260906);
  const values = {};
  for (const id of regionIds) {
    // Smooth-ish spread rather than pure noise: most regions near zero,
    // a handful of clear outliers — reads like a real regional BAG map
    // rather than static.
    const magnitude = rand() < 0.25 ? rand() * 3 : rand() * 0.8;
    values[id] = (rand() < 0.5 ? -1 : 1) * magnitude;
  }
  return values;
}

const stage = document.querySelector("[data-scroll-brain]");
if (stage) {
  const viewer = new CortexViewer(stage, { glbUrl: "/static/mesh/cortex.glb" });
  viewer.addEventListener("ready", async () => {
    const regions = await fetch("/static/mesh/regions.json").then((r) => r.json());
    viewer.setRegionValues(syntheticRegionValues(Object.values(regions)));
  });
}
