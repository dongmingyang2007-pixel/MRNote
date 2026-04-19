"use client";

import { useEffect, useRef } from "react";
import {
  Scene, PerspectiveCamera, WebGLRenderer, AmbientLight, DirectionalLight,
  Group, Vector3, Color, Fog, Raycaster, Vector2, BufferGeometry,
  Line, LineBasicMaterial, Sprite,
} from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { GraphEdge, GraphNode } from "../types";
import { makeNodeCard, cardCacheKey } from "./cardSprite";
import { placeNodes } from "./layout3d";
import { buildGround } from "./ground";
import { buildEdgeGeometry } from "./edges3d";
import { EDGE_STYLE } from "../constants";
import {
  CAMERA_DEFAULT_POS, CAMERA_DEFAULT_FOV, ORBIT_MIN_DIST, ORBIT_MAX_DIST,
  ORBIT_POLAR_MIN, ORBIT_POLAR_MAX, FOG_NEAR, FOG_FAR, FOG_FALLBACK_COLOR,
  CAMERA_ANIM_DUR, GROUND_Y,
} from "./constants3d";
import type { SceneHandle, CameraAnim } from "./types3d";

interface Options {
  mountRef: React.RefObject<HTMLDivElement | null>;
  nodes: GraphNode[];
  edges: GraphEdge[];
  onHover: (id: string | null) => void;
  onSelect: (id: string | null) => void;
}

interface SceneState {
  renderer?: WebGLRenderer;
  scene?: Scene;
  camera?: PerspectiveCamera;
  controls?: OrbitControls;
  nodeGroup?: Group;
  edgeGroup?: Group;
  dropLineGroup?: Group;
  spriteById?: Map<string, Sprite>;
  nodeById?: Map<string, GraphNode>;
  cameraAnim?: CameraAnim | null;
  rafId?: number | null;
}

function resolveBgColor(mount: HTMLElement | null): Color {
  if (!mount) return new Color(FOG_FALLBACK_COLOR);
  const cs = getComputedStyle(mount);
  const bg = cs.backgroundColor;
  if (bg && bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent") {
    try { return new Color().set(bg); } catch { /* fall through */ }
  }
  return new Color(FOG_FALLBACK_COLOR);
}

function makeHandle(stateRef: React.MutableRefObject<SceneState>): SceneHandle {
  return {
    focusOn: (id) => {
      const s = stateRef.current;
      if (!s.camera || !s.controls) return;
      const fromPos = s.camera.position.clone();
      const fromTarget = s.controls.target.clone();
      if (id && s.spriteById?.has(id)) {
        const sprite = s.spriteById.get(id)!;
        const toTarget = sprite.position.clone();
        const toPos = toTarget.clone().add(new Vector3(0, 60, 180));
        s.cameraAnim = { fromPos, fromTarget, toPos, toTarget, t: 0, dur: CAMERA_ANIM_DUR };
      } else {
        const toTarget = new Vector3(0, 0, 0);
        const toPos = new Vector3(...CAMERA_DEFAULT_POS);
        s.cameraAnim = { fromPos, fromTarget, toPos, toTarget, t: 0, dur: CAMERA_ANIM_DUR };
      }
    },
    rearrange: () => { /* deterministic placement — no-op; fit instead */ },
    zoomIn: () => {
      const s = stateRef.current;
      if (!s.camera || !s.controls) return;
      s.camera.position.multiplyScalar(1 / 1.2);
      s.controls.update();
    },
    zoomOut: () => {
      const s = stateRef.current;
      if (!s.camera || !s.controls) return;
      s.camera.position.multiplyScalar(1.2);
      s.controls.update();
    },
    fit: () => {
      const s = stateRef.current;
      if (!s.camera || !s.controls) return;
      const fromPos = s.camera.position.clone();
      const fromTarget = s.controls.target.clone();
      s.cameraAnim = {
        fromPos, fromTarget,
        toPos: new Vector3(...CAMERA_DEFAULT_POS),
        toTarget: new Vector3(0, 0, 0),
        t: 0, dur: CAMERA_ANIM_DUR,
      };
    },
    toggleAutoRotate: () => {
      if (stateRef.current.controls) {
        stateRef.current.controls.autoRotate = !stateRef.current.controls.autoRotate;
      }
    },
    getProjectedScreenPos: (id) => {
      const s = stateRef.current;
      if (!s.camera || !s.spriteById || !s.renderer) return null;
      const sprite = s.spriteById.get(id);
      if (!sprite) return null;
      const v = sprite.position.clone().project(s.camera);
      const rect = s.renderer.domElement.getBoundingClientRect();
      return {
        x: (v.x * 0.5 + 0.5) * rect.width,
        y: (-v.y * 0.5 + 0.5) * rect.height,
      };
    },
  };
}

export function useThreeScene(opts: Options): SceneHandle {
  const stateRef = useRef<SceneState>({});
  const handleRef = useRef<SceneHandle | null>(null);

  useEffect(() => {
    const mount = opts.mountRef.current;
    if (!mount) return;

    const w = Math.max(200, mount.clientWidth);
    const h = Math.max(200, mount.clientHeight);

    const scene = new Scene();
    scene.background = null;
    const fogColor = resolveBgColor(mount);
    scene.fog = new Fog(fogColor.getHex(), FOG_NEAR, FOG_FAR);

    const camera = new PerspectiveCamera(CAMERA_DEFAULT_FOV, w / h, 1, 3000);
    camera.position.set(...CAMERA_DEFAULT_POS);

    const renderer = new WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
    renderer.setSize(w, h);
    renderer.setClearColor(0x000000, 0);
    mount.appendChild(renderer.domElement);
    renderer.domElement.style.display = "block";
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";

    scene.add(new AmbientLight(0xffffff, 0.8));
    const sun = new DirectionalLight(0xffffff, 0.7); sun.position.set(160, 280, 180); scene.add(sun);
    const cool = new DirectionalLight(0xcfe7ff, 0.35); cool.position.set(-180, -40, -120); scene.add(cool);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.09;
    controls.rotateSpeed = 0.7;
    controls.minDistance = ORBIT_MIN_DIST;
    controls.maxDistance = ORBIT_MAX_DIST;
    controls.minPolarAngle = ORBIT_POLAR_MIN;
    controls.maxPolarAngle = ORBIT_POLAR_MAX;
    controls.target.set(0, 0, 0);
    controls.autoRotate = false;

    scene.add(buildGround());
    const nodeGroup = new Group();
    const edgeGroup = new Group();
    const dropLineGroup = new Group();
    scene.add(edgeGroup, dropLineGroup, nodeGroup);

    stateRef.current = {
      renderer, scene, camera, controls,
      nodeGroup, edgeGroup, dropLineGroup,
      spriteById: new Map(), nodeById: new Map(),
      cameraAnim: null, rafId: null,
    };

    const raycaster = new Raycaster();
    const mouseNdc = new Vector2();
    let hoverId: string | null = null;
    const onPointerMove = (e: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      mouseNdc.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouseNdc.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouseNdc, camera);
      const hits = raycaster.intersectObjects(nodeGroup.children, false);
      const id = (hits[0]?.object.userData.id as string | undefined) ?? null;
      if (id !== hoverId) { hoverId = id; opts.onHover(id); }
    };
    const onClick = (e: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      mouseNdc.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouseNdc.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouseNdc, camera);
      const hits = raycaster.intersectObjects(nodeGroup.children, false);
      const id = (hits[0]?.object.userData.id as string | undefined) ?? null;
      opts.onSelect(id);
    };
    renderer.domElement.addEventListener("pointermove", onPointerMove);
    renderer.domElement.addEventListener("click", onClick);

    const onResize = () => {
      if (!stateRef.current.renderer) return;
      const nw = Math.max(200, mount.clientWidth);
      const nh = Math.max(200, mount.clientHeight);
      stateRef.current.camera!.aspect = nw / nh;
      stateRef.current.camera!.updateProjectionMatrix();
      stateRef.current.renderer.setSize(nw, nh);
    };
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(onResize) : null;
    ro?.observe(mount);

    let last = performance.now();
    const tick = () => {
      const now = performance.now();
      const dt = (now - last) / 1000;
      last = now;
      const s = stateRef.current;
      if (!s.renderer || !s.scene || !s.camera || !s.controls) return;
      if (s.cameraAnim) {
        const ca = s.cameraAnim;
        ca.t += dt;
        const k = Math.min(1, ca.t / ca.dur);
        const ease = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        s.camera.position.lerpVectors(ca.fromPos, ca.toPos, ease);
        s.controls.target.lerpVectors(ca.fromTarget, ca.toTarget, ease);
        if (k >= 1) s.cameraAnim = null;
      }
      s.controls.update();
      s.renderer.render(s.scene, s.camera);
      s.rafId = requestAnimationFrame(tick);
    };
    stateRef.current.rafId = requestAnimationFrame(tick);

    handleRef.current = makeHandle(stateRef);

    return () => {
      const s = stateRef.current;
      if (s.rafId) cancelAnimationFrame(s.rafId);
      renderer.domElement.removeEventListener("pointermove", onPointerMove);
      renderer.domElement.removeEventListener("click", onClick);
      ro?.disconnect();
      s.nodeGroup?.children.forEach((o) => {
        const sp = o as Sprite;
        const m = sp.material as SpriteMaterial;
        m.map?.dispose();
        m.dispose();
      });
      renderer.dispose();
      if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
      stateRef.current = {};
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const s = stateRef.current;
    if (!s.nodeGroup || !s.edgeGroup || !s.dropLineGroup || !s.spriteById || !s.nodeById) return;

    const placed = placeNodes(opts.nodes);
    const kept = new Set<string>();
    for (const p of placed) {
      kept.add(p.id);
      const existing = s.spriteById.get(p.id);
      const key = cardCacheKey(p.node);
      if (existing && existing.userData.cacheKey === key) {
        existing.position.copy(p.position);
        continue;
      }
      if (existing) {
        s.nodeGroup.remove(existing);
        const m = existing.material as SpriteMaterial;
        m.map?.dispose();
        m.dispose();
      }
      const sprite = makeNodeCard(p.node);
      sprite.position.copy(p.position);
      sprite.userData.id = p.id;
      s.nodeGroup.add(sprite);
      s.spriteById.set(p.id, sprite);
      s.nodeById.set(p.id, p.node);
    }
    for (const [id, sprite] of s.spriteById.entries()) {
      if (!kept.has(id)) {
        s.nodeGroup.remove(sprite);
        const m = sprite.material as SpriteMaterial;
        m.map?.dispose();
        m.dispose();
        s.spriteById.delete(id);
        s.nodeById.delete(id);
      }
    }

    while (s.edgeGroup.children.length > 0) {
      const l = s.edgeGroup.children.pop() as Line;
      l.geometry.dispose();
      (l.material as LineBasicMaterial).dispose();
    }
    const placedById = new Map(placed.map((p) => [p.id, p]));
    for (const e of opts.edges) {
      const a = placedById.get(e.a);
      const b = placedById.get(e.b);
      if (!a || !b) continue;
      const style = EDGE_STYLE[e.rel] ?? EDGE_STYLE.__fallback__;
      const geo = buildEdgeGeometry(a.position, b.position);
      const line = new Line(geo, new LineBasicMaterial({
        color: new Color(style.stroke), transparent: true, opacity: 0.42, depthWrite: false,
      }));
      line.userData = { a: e.a, b: e.b, rel: e.rel };
      s.edgeGroup.add(line);
    }

    while (s.dropLineGroup.children.length > 0) {
      const l = s.dropLineGroup.children.pop() as Line;
      l.geometry.dispose();
      (l.material as LineBasicMaterial).dispose();
    }
    for (const p of placed) {
      const geo = new BufferGeometry().setFromPoints([
        new Vector3(p.position.x, p.position.y, p.position.z),
        new Vector3(p.position.x, GROUND_Y + 1, p.position.z),
      ]);
      const line = new Line(geo, new LineBasicMaterial({
        color: 0x94a3b8, transparent: true, opacity: 0.22, depthWrite: false,
      }));
      s.dropLineGroup.add(line);
    }
  }, [opts.nodes, opts.edges]);

  return handleRef.current ?? makeHandle(stateRef);
}

// Local type alias so the generic SpriteMaterial reference typechecks in strict mode
type SpriteMaterial = NonNullable<Sprite["material"]>;
