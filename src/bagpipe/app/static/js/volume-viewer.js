// Standalone NiiVue volumetric viewer — orthogonal (axial/coronal/sagittal)
// MPR of a T1 with a regional atlas overlay, colored on the same diverging
// scale as cortex-viewer.js. Same API shape as CortexViewer on purpose
// (setRegionValues/regionhover) so the surface and volumetric views read as
// one component pair, not two unrelated libraries.
//
// Usage:
//   import { VolumeViewer } from "./volume-viewer.js";
//   const viewer = new VolumeViewer(containerEl, {
//     t1Url: "/jobs/<id>/volume/t1.nii.gz",
//     atlasUrl: "/static-data/atlas/schaefer2018n400n7tian2020s2.nii.gz",
//   });
//   viewer.addEventListener("regionhover", (e) => console.log(e.detail.regionId));
//   viewer.setRegionValues({ 12: 1.4, 40: -0.8 });

import { Niivue, SLICE_TYPE, MULTIPLANAR_TYPE, SHOW_RENDER } from "@niivue/niivue";
import { TOKENS, hexToRGBA1, hexToRGB255 } from "./brand-tokens.js";

const DIVERGE_NEGATIVE = hexToRGB255(TOKENS.cool);
const DIVERGE_CENTER = hexToRGB255(TOKENS.bone);
const DIVERGE_POSITIVE = hexToRGB255(TOKENS.warm);

export class VolumeViewer extends EventTarget {
  constructor(container, options = {}) {
    super();
    this.container = container;
    this.t1Url = options.t1Url;
    this.atlasUrl = options.atlasUrl;
    this.atlasOpacity = options.atlasOpacity ?? 0.75;

    this._atlasMaxId = 0;
    this._hoveredRegionId = null;
    this._ready = false;

    this.nv = new Niivue({
      backColor: hexToRGBA1(TOKENS.ground),
      crosshairColor: hexToRGBA1(TOKENS.warm),
      fontColor: hexToRGBA1(TOKENS.muted),
      selectionBoxColor: hexToRGBA1(TOKENS.bone, 0.3),
      show3Dcrosshair: true,
      isColorbar: false,
      multiplanarLayout: MULTIPLANAR_TYPE.GRID,
      multiplanarShowRender: SHOW_RENDER.NEVER, // orthogonal slices only, no 3D render pane
      dragMode: "pan",
    });
    this._onPointerMove = this._handlePointerMove.bind(this);
    this._onPointerLeave = () => this._setHoveredRegion(null);

    this._load();
  }

  // -- public API ----------------------------------------------------

  /** map: {regionId: number} — regions absent from map stay plain T1 (no overlay). */
  async setRegionValues(map) {
    if (!this._ready) await this._readyPromise;
    this._applyRegionValues(map);
  }

  // Called both by the public setRegionValues (guarded above) and by
  // _load() itself once volumes are in — going through the guarded method
  // there would deadlock, since _readyPromise's own resolution chain is
  // what calls this.
  _applyRegionValues(map) {
    const entries = Object.entries(map ?? {}).map(([id, v]) => [Number(id), Number(v)]);
    const scale = entries.reduce((max, [, v]) => Math.max(max, Math.abs(v)), 0) || 1;
    const lut = new Map(entries);

    const n = this._atlasMaxId + 1; // indices 0..max, inclusive
    const R = new Array(n).fill(0);
    const G = new Array(n).fill(0);
    const B = new Array(n).fill(0);
    const A = new Array(n).fill(0); // no data => fully transparent => T1 shows through
    for (let id = 0; id <= this._atlasMaxId; id++) {
      const value = lut.get(id);
      if (value === undefined) continue;
      const [r, g, b] = divergingRGB(value, scale);
      R[id] = r;
      G[id] = g;
      B[id] = b;
      A[id] = Math.round(this.atlasOpacity * 255);
    }

    this._atlasLayer.setColormapLabel({ R, G, B, A, I: [...Array(n).keys()] });
    this.nv.updateGLVolume();
  }

  dispose() {
    this.nv.canvas.removeEventListener("pointermove", this._onPointerMove);
    this.nv.canvas.removeEventListener("pointerleave", this._onPointerLeave);
    this._resizeObserver?.disconnect();
  }

  // -- setup -----------------------------------------------------------

  _makeCanvas() {
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.display = "block";
    this.container.appendChild(canvas);
    this._resizeObserver = new ResizeObserver(() => this.nv.resizeListener());
    this._resizeObserver.observe(this.container);
    return canvas;
  }

  async _load() {
    await this.nv.attachToCanvas(this._makeCanvas());
    this.nv.setSliceType(SLICE_TYPE.MULTIPLANAR);
    this.nv.canvas.addEventListener("pointermove", this._onPointerMove);
    this.nv.canvas.addEventListener("pointerleave", this._onPointerLeave);

    this._readyPromise = this.nv
      .loadVolumes([
        { url: this.t1Url, colormap: "gray", opacity: 1 },
        { url: this.atlasUrl, colormap: "gray", opacity: this.atlasOpacity },
      ])
      .then(() => {
        this._atlasLayer = this.nv.volumes[1];
        this._atlasMaxId = Math.round(this._atlasLayer.global_max ?? 0);
        // start with no overlay: every region transparent until setRegionValues fills it in
        this._applyRegionValues({});
        this._ready = true;
        this.dispatchEvent(new CustomEvent("ready"));
      })
      .catch((err) => this.dispatchEvent(new CustomEvent("error", { detail: err })));
    await this._readyPromise;
  }

  // -- interaction -------------------------------------------------------

  _handlePointerMove(event) {
    if (!this._ready || !this._atlasLayer) return;
    const pos = this.nv.getNoPaddingNoBorderCanvasRelativeMousePosition(event, this.nv.gl.canvas);
    if (!pos) {
      this._setHoveredRegion(null);
      return;
    }
    const dpr = this.nv.uiData.dpr || 1;
    const frac = this.nv.canvasPos2frac([pos.x * dpr, pos.y * dpr]);
    if (frac[0] < 0) {
      // canvasPos2frac returns [-1,-1,-1] outside any tile
      this._setHoveredRegion(null);
      return;
    }
    // frac2vox(frac, 1) looks broken for overlay layers — NVImage.dims is
    // only populated on the background image (index 0), not overlays; see
    // niivue's convertFrac2Vox, which indexes nvImage.dims directly and
    // throws for the atlas layer. T1 and the atlas share one voxel grid
    // (that's the point of loading them together), so vox from the
    // background image indexes the atlas layer correctly too.
    const vox = this.nv.frac2vox(frac);
    const value = Math.round(this._atlasLayer.getValue(vox[0], vox[1], vox[2]));
    this._setHoveredRegion(value > 0 ? value : null);
  }

  _setHoveredRegion(regionId) {
    if (regionId === this._hoveredRegionId) return;
    this._hoveredRegionId = regionId;
    this.dispatchEvent(new CustomEvent("regionhover", { detail: { regionId } }));
  }
}

function divergingRGB(value, scale) {
  const t = Math.max(-1, Math.min(1, value / scale));
  const [from, to] = t < 0 ? [DIVERGE_CENTER, DIVERGE_NEGATIVE] : [DIVERGE_CENTER, DIVERGE_POSITIVE];
  const f = Math.abs(t);
  return [lerp(from[0], to[0], f), lerp(from[1], to[1], f), lerp(from[2], to[2], f)];
}

function lerp(a, b, t) {
  return Math.round(a + (b - a) * t);
}
