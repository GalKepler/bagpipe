// Single source of truth for the design tokens in docs/design-brief.md §3.
// Shared by cortex-viewer.js, volume-viewer.js, and their CSS chrome
// (bagpipe.app.style.BRAIN_VIEWER_CSS) so the surface and volumetric views
// read as one product, not two libraries with two palettes.

export const TOKENS = {
  ground: "#0B0F0E",
  surface: "#141A18",
  line: "#232B28",
  bone: "#E8E6DF",
  muted: "#8A928E",
  warm: "#E0873A", // diverging positive — "older"
  cool: "#3FA89A", // diverging negative — "younger"
};

/** [r,g,b,a] in 0..1, as niivue's options/colormap tables expect. */
export function hexToRGBA1(hex, alpha = 1) {
  const n = parseInt(hex.slice(1), 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255, alpha];
}

/** [r,g,b] in 0..255, as niivue's label-LUT R/G/B arrays expect. */
export function hexToRGB255(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
