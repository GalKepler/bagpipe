// Standalone three.js cortical surface viewer. Loads cortex.glb (see
// scripts/export_surface_mesh.py / static/mesh/README.md for the file's
// vertex-attribute layout: _curvature float [0,1], _region_id uint16).
//
// Usage:
//   import { CortexViewer } from "./cortex-viewer.js";
//   const viewer = new CortexViewer(containerEl, { glbUrl: "../mesh/cortex.glb" });
//   viewer.addEventListener("regionhover", (e) => console.log(e.detail.regionId));
//   viewer.setRegionValues({ 12: 1.4, 40: -0.8 });
//   viewer.setScrollProgress(0.5);

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { TOKENS } from "./brand-tokens.js";

const BACKGROUND_COLOR = new THREE.Color(TOKENS.ground);
const SULCUS_COLOR = new THREE.Color(TOKENS.line); // desaturated dark, curvature -> 0
const GYRUS_COLOR = new THREE.Color(TOKENS.muted); // desaturated light, curvature -> 1
const DIVERGE_NEGATIVE = new THREE.Color(TOKENS.cool);
const DIVERGE_CENTER = new THREE.Color(TOKENS.bone);
const DIVERGE_POSITIVE = new THREE.Color(TOKENS.warm);
const DRACO_DECODER_PATH = "https://www.gstatic.com/draco/versioned/decoders/1.5.7/";

const REDUCED_MOTION_QUERY =
  typeof window !== "undefined" && window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)")
    : null;

const tmpColor = new THREE.Color();

export class CortexViewer extends EventTarget {
  constructor(container, options = {}) {
    super();
    this.container = container;
    this.glbUrl = options.glbUrl ?? "cortex.glb";
    this.reducedMotion = REDUCED_MOTION_QUERY ? REDUCED_MOTION_QUERY.matches : false;

    this._vertexRegionIds = null; // Uint16Array, length = vertex count
    this._baseColors = null; // Float32Array, length = vertex count * 3
    this._mesh = null;
    this._hoveredRegionId = null;
    this._scrollT = 0;
    this._disposed = false;

    this._initScene();
    this._initInteraction();
    this._observeResize();
    this._load();
    this._animate = this._animate.bind(this);
    this._raf = requestAnimationFrame(this._animate);
  }

  // -- public API ----------------------------------------------------

  /** map: {regionId: number} — regions absent from map stay curvature-shaded. */
  setRegionValues(map) {
    if (!this._mesh) return;
    const entries = Object.entries(map ?? {}).map(([id, v]) => [Number(id), Number(v)]);
    const lut = new Map(entries);
    const scale = entries.reduce((max, [, v]) => Math.max(max, Math.abs(v)), 0) || 1;

    const colorAttr = this._mesh.geometry.getAttribute("color");
    const colors = colorAttr.array;
    const regionIds = this._vertexRegionIds;
    const base = this._baseColors;

    for (let i = 0; i < regionIds.length; i++) {
      const value = lut.get(regionIds[i]);
      const o = i * 3;
      if (value === undefined) {
        colors[o] = base[o];
        colors[o + 1] = base[o + 1];
        colors[o + 2] = base[o + 2];
        continue;
      }
      divergingColor(value, scale, tmpColor);
      colors[o] = tmpColor.r;
      colors[o + 1] = tmpColor.g;
      colors[o + 2] = tmpColor.b;
    }
    colorAttr.needsUpdate = true;
  }

  /** t in [0,1] drives rotation. No-op under prefers-reduced-motion. */
  setScrollProgress(t) {
    this._scrollT = Math.min(1, Math.max(0, t));
    if (this.reducedMotion || !this._mesh) return;
    this._mesh.rotation.y = THREE.MathUtils.degToRad(-180 + this._scrollT * 360);
  }

  dispose() {
    this._disposed = true;
    cancelAnimationFrame(this._raf);
    this._resizeObserver?.disconnect();
    this.renderer.domElement.removeEventListener("pointermove", this._onPointerMove);
    this.renderer.domElement.removeEventListener("pointerleave", this._onPointerLeave);
    this._mesh?.geometry.dispose();
    this._mesh?.material.dispose();
    this.renderer.dispose();
  }

  // -- setup -----------------------------------------------------------

  _initScene() {
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(BACKGROUND_COLOR);

    const { clientWidth: w, clientHeight: h } = this.container;
    this.camera = new THREE.PerspectiveCamera(35, w / (h || 1), 0.1, 1000);
    this.camera.position.set(0, 0, 300);

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(w, h || 1);
    this.container.appendChild(this.renderer.domElement);

    this.scene.add(new THREE.AmbientLight(0xffffff, 0.65));
    const key = new THREE.DirectionalLight(0xffffff, 0.9);
    key.position.set(1, 1, 1);
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.3);
    fill.position.set(-1, -0.5, -1);
    this.scene.add(fill);
  }

  _load() {
    const draco = new DRACOLoader();
    draco.setDecoderPath(DRACO_DECODER_PATH);

    const loader = new GLTFLoader();
    loader.setDRACOLoader(draco);
    loader.load(
      this.glbUrl,
      (gltf) => this._onLoaded(gltf),
      undefined,
      (err) => this.dispatchEvent(new CustomEvent("error", { detail: err })),
    );
  }

  _onLoaded(gltf) {
    if (this._disposed) return;
    const mesh = gltf.scene.getObjectByProperty("type", "Mesh");
    const geometry = mesh.geometry;

    const curvature = geometry.getAttribute("_curvature");
    const regionId = geometry.getAttribute("_region_id");
    const vertexCount = geometry.getAttribute("position").count;

    this._vertexRegionIds = new Uint16Array(vertexCount);
    for (let i = 0; i < vertexCount; i++) this._vertexRegionIds[i] = regionId.getX(i);

    const colors = new Float32Array(vertexCount * 3);
    for (let i = 0; i < vertexCount; i++) {
      curvatureColor(curvature.getX(i), tmpColor);
      colors[i * 3] = tmpColor.r;
      colors[i * 3 + 1] = tmpColor.g;
      colors[i * 3 + 2] = tmpColor.b;
    }
    this._baseColors = colors;
    geometry.setAttribute("color", new THREE.BufferAttribute(colors.slice(), 3));

    geometry.computeVertexNormals();
    geometry.computeBoundingSphere();

    mesh.material = new THREE.MeshStandardMaterial({
      vertexColors: true,
      roughness: 1,
      metalness: 0,
      flatShading: false,
    });

    this.scene.add(mesh);
    this._mesh = mesh;
    this._frameCamera(geometry.boundingSphere);
    this.setScrollProgress(this._scrollT);
    this.dispatchEvent(new CustomEvent("ready"));
  }

  _frameCamera(sphere) {
    const fovRad = THREE.MathUtils.degToRad(this.camera.fov);
    const distance = (sphere.radius / Math.sin(fovRad / 2)) * 1.15;
    this.camera.position.set(0, 0, distance);
    this.camera.lookAt(sphere.center);
    this.camera.near = distance / 100;
    this.camera.far = distance * 100;
    this.camera.updateProjectionMatrix();
  }

  // -- interaction -------------------------------------------------------

  _initInteraction() {
    this._raycaster = new THREE.Raycaster();
    this._pointer = new THREE.Vector2();
    this._onPointerMove = this._handlePointerMove.bind(this);
    this._onPointerLeave = () => this._setHoveredRegion(null);
    this.renderer.domElement.addEventListener("pointermove", this._onPointerMove);
    this.renderer.domElement.addEventListener("pointerleave", this._onPointerLeave);
  }

  _handlePointerMove(event) {
    if (!this._mesh) return;
    const rect = this.renderer.domElement.getBoundingClientRect();
    this._pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this._pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

    this._raycaster.setFromCamera(this._pointer, this.camera);
    const [hit] = this._raycaster.intersectObject(this._mesh, false);
    if (!hit || hit.face === undefined) {
      this._setHoveredRegion(null);
      return;
    }
    const regionId = this._vertexRegionIds[hit.face.a];
    this._setHoveredRegion(regionId);
  }

  _setHoveredRegion(regionId) {
    if (regionId === this._hoveredRegionId) return;
    this._hoveredRegionId = regionId;
    this.dispatchEvent(new CustomEvent("regionhover", { detail: { regionId } }));
  }

  // -- lifecycle -----------------------------------------------------------

  _observeResize() {
    this._resizeObserver = new ResizeObserver(() => {
      const { clientWidth: w, clientHeight: h } = this.container;
      if (!w || !h) return;
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
      this.renderer.setSize(w, h);
    });
    this._resizeObserver.observe(this.container);
  }

  _animate() {
    if (this._disposed) return;
    this._raf = requestAnimationFrame(this._animate);
    this.renderer.render(this.scene, this.camera);
  }
}

function curvatureColor(curvature, target) {
  return target.copy(SULCUS_COLOR).lerp(GYRUS_COLOR, THREE.MathUtils.clamp(curvature, 0, 1));
}

function divergingColor(value, scale, target) {
  const t = THREE.MathUtils.clamp(value / scale, -1, 1);
  return t < 0
    ? target.copy(DIVERGE_CENTER).lerp(DIVERGE_NEGATIVE, -t)
    : target.copy(DIVERGE_CENTER).lerp(DIVERGE_POSITIVE, t);
}
