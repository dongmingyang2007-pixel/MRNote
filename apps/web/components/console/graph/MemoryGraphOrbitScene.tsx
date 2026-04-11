"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
} from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import {
  getMemoryCategoryLabel,
  getMemoryKind,
  getMemoryNodeRole,
  getMemoryRetrievalCount,
  isFileMemoryNode,
  isPinnedMemoryNode,
  type MemoryNode,
} from "@/hooks/useGraphData";

type OrbitWorldNode = {
  x: number;
  y: number;
  z: number;
  depth: number;
};

type OrbitSceneLink = {
  id: string;
  sourceId: string;
  targetId: string;
  edgeType: string;
  strength: number;
};

export interface MemoryGraphOrbitSceneHandle {
  zoomIn: () => void;
  zoomOut: () => void;
  fitView: () => void;
}

interface MemoryGraphOrbitSceneProps {
  nodes: MemoryNode[];
  links: OrbitSceneLink[];
  centerNodeId: string;
  centerNodeLabel: string;
  centerNodeShortLabel: string;
  worldById: Map<string, OrbitWorldNode>;
  visibleNodeIds: Set<string>;
  searchMatchIds: Set<string> | null;
  selectedNodeId: string | null;
  maxRetrievalCount: number;
  onSelectNode: (node: MemoryNode | null) => void;
  onCenterNodeClick?: () => void;
  onRendererUnavailable?: () => void;
}

type CameraTweenState = {
  fromPosition: THREE.Vector3;
  fromTarget: THREE.Vector3;
  toPosition: THREE.Vector3;
  toTarget: THREE.Vector3;
  startTime: number;
  durationMs: number;
};

const ORBIT_CAMERA_DIRECTION = new THREE.Vector3(-1.08, 0.72, 0.94).normalize();
const ORBIT_WORLD_SCALE = 0.92;
const ORBIT_WORLD_Y_SCALE = 1.08;
const ORBIT_WORLD_Z_SCALE = 0.96;
const ORBIT_MIN_CAMERA_DISTANCE = 360;
const ORBIT_MAX_CAMERA_DISTANCE = 1320;
const ORBIT_ZOOM_STEP = 0.84;
const ORBIT_PALETTE = {
  background: "#f5f3ff",
  fog: "#ede8ff",
  ring: "#d4c0ff",
  stage: "#ece6ff",
  stageGlow: "#f3eeff",
  stageEdge: "#d8d0f0",
  shadowPool: "#e0d8f0",
  skyLight: "#ede8ff",
  groundLight: "#e8e0f8",
  keyLight: "#d4c0ff",
  fillLight: "#d8e2ff",
  rimLight: "#e0d0f8",
  edgeWarm: "#9b8ec4",
  edgeGold: "#a78bfa",
  edgeBlue: "#7b8cf2",
  edgeBlueStrong: "#6f5bff",
  edgeRed: "#8b6fff",
  edgeNeutral: "#9b8ec4",
  centerNode: "#6f5bff",
  centerHalo: "#d4c0ff",
};

function clampNumber(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function getOrbitNodeRadius(node: MemoryNode, centerNodeId: string): number {
  if (node.id === centerNodeId) return 34;
  if (isFileMemoryNode(node)) return 12;
  const role = getMemoryNodeRole(node);
  if (role === "summary") return 23;
  if (role === "subject") return 24;
  if (role === "concept") return 22;
  if (role === "structure") return 18;
  if (isPinnedMemoryNode(node)) return 22;
  return 20;
}

function getOrbitNodeColor(node: MemoryNode, maxRetrievalCount: number): THREE.Color {
  const kind = getMemoryKind(node);
  const role = getMemoryNodeRole(node);
  const baseHex = (() => {
    if (node.type === "temporary") return "#5b8fca";
    if (role === "summary") return "#b89a48";
    if (role === "structure") return "#c39a69";
    if (role === "subject") return "#9f6268";
    if (role === "concept") return "#bf6c57";
    if (isPinnedMemoryNode(node)) return "#d48760";
    if (kind === "profile" || kind === "preference" || kind === "goal") return "#d48760";
    return "#c96f49";
  })();

  const retrievalCount = getMemoryRetrievalCount(node);
  if (retrievalCount > 0 && maxRetrievalCount > 0) {
    const normalized = Math.log(retrievalCount + 1) / Math.log(maxRetrievalCount + 1);
    return new THREE.Color(baseHex).lerp(new THREE.Color("#f9e7d7"), normalized * 0.08);
  }
  return new THREE.Color(baseHex);
}

function getOrbitLabel(node: MemoryNode, centerNodeId: string, centerNodeLabel: string): string {
  if (node.id === centerNodeId) {
    return centerNodeLabel.length > 12 ? `${centerNodeLabel.slice(0, 12)}...` : centerNodeLabel;
  }
  if (isFileMemoryNode(node)) {
    const filename =
      typeof node.metadata_json?.filename === "string"
        ? node.metadata_json.filename
        : node.content;
    return filename.length > 16 ? `${filename.slice(0, 16)}...` : filename;
  }
  if (getMemoryNodeRole(node) === "structure") {
    return getMemoryCategoryLabel(node) || node.content;
  }
  const content = node.content.trim();
  if (content) {
    return content.length > 13 ? `${content.slice(0, 13)}...` : content;
  }
  return node.category || node.id.slice(0, 8);
}

function getScenePosition(worldNode: OrbitWorldNode | undefined): THREE.Vector3 {
  if (!worldNode) {
    return new THREE.Vector3();
  }
  return new THREE.Vector3(
    worldNode.x * ORBIT_WORLD_SCALE,
    -worldNode.y * ORBIT_WORLD_Y_SCALE,
    worldNode.z * ORBIT_WORLD_Z_SCALE,
  );
}

function disposeHierarchy(root: THREE.Object3D): void {
  root.traverse((object) => {
    const mesh = object as THREE.Mesh;
    if (mesh.geometry) {
      mesh.geometry.dispose();
    }
    const material = (mesh as { material?: THREE.Material | THREE.Material[] }).material;
    if (Array.isArray(material)) {
      material.forEach((entry) => entry.dispose());
    } else if (material) {
      material.dispose();
    }
  });
}

function buildEllipseLine(radiusX: number, radiusZ: number, color: string, opacity: number): THREE.Line {
  const points: THREE.Vector3[] = [];
  const segments = 96;
  for (let index = 0; index <= segments; index += 1) {
    const angle = (index / segments) * Math.PI * 2;
    points.push(new THREE.Vector3(Math.cos(angle) * radiusX, 0, Math.sin(angle) * radiusZ));
  }
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const material = new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity,
    depthWrite: false,
  });
  return new THREE.LineLoop(geometry, material);
}

function createLabelElement(
  node: MemoryNode,
  centerNodeId: string,
  centerNodeShortLabel: string,
  centerNodeLabel: string,
  isSelected: boolean,
  isDimmed: boolean,
): HTMLDivElement {
  const root = document.createElement("div");
  root.className = [
    "graph-orbit-label",
    node.id === centerNodeId ? "is-center" : "",
    isSelected ? "is-selected" : "",
    isDimmed ? "is-muted" : "",
  ]
    .filter(Boolean)
    .join(" ");

  if (node.id === centerNodeId) {
    const chip = document.createElement("strong");
    chip.textContent = centerNodeShortLabel;
    root.appendChild(chip);
  }

  const text = document.createElement("span");
  text.textContent = getOrbitLabel(node, centerNodeId, centerNodeLabel);
  root.appendChild(text);
  return root;
}

function getEdgeBaseColor(edgeType: string): THREE.Color {
  switch (edgeType) {
    case "center":
    case "parent":
      return new THREE.Color(ORBIT_PALETTE.edgeWarm);
    case "summary":
      return new THREE.Color(ORBIT_PALETTE.edgeGold);
    case "manual":
      return new THREE.Color(ORBIT_PALETTE.edgeBlue);
    case "related":
      return new THREE.Color(ORBIT_PALETTE.edgeBlue);
    case "prerequisite":
      return new THREE.Color(ORBIT_PALETTE.edgeBlueStrong);
    case "conflict":
      return new THREE.Color(ORBIT_PALETTE.edgeRed);
    case "supersedes":
      return new THREE.Color(ORBIT_PALETTE.edgeNeutral);
    case "file":
      return new THREE.Color("#99887c");
    default:
      return new THREE.Color(ORBIT_PALETTE.edgeWarm);
  }
}

function buildEdgeCurve(
  start: THREE.Vector3,
  end: THREE.Vector3,
  edgeType: string,
): THREE.Curve<THREE.Vector3> {
  const midpoint = start.clone().add(end).multiplyScalar(0.5);
  const distance = start.distanceTo(end);
  const lift =
    edgeType === "center" || edgeType === "parent"
      ? Math.max(18, distance * 0.16)
      : edgeType === "summary"
        ? Math.max(14, distance * 0.12)
        : Math.max(10, distance * 0.08);
  const offsetAxis = new THREE.Vector3().subVectors(end, start).normalize();
  const sideAxis = new THREE.Vector3(-offsetAxis.z, 0, offsetAxis.x).multiplyScalar(
    edgeType === "manual" || edgeType === "related" ? 14 : 8,
  );
  const control = midpoint.clone().add(new THREE.Vector3(0, lift, 0)).add(sideAxis);
  return new THREE.QuadraticBezierCurve3(start, control, end);
}

function createRendererContext(
  canvas: HTMLCanvasElement,
): WebGL2RenderingContext | WebGLRenderingContext | null {
  try {
    return (
      canvas.getContext("webgl2", {
        alpha: true,
        antialias: true,
        powerPreference: "high-performance",
      }) ??
      canvas.getContext("webgl", {
        alpha: true,
        antialias: true,
        powerPreference: "high-performance",
      })
    );
  } catch {
    return null;
  }
}

const MemoryGraphOrbitScene = forwardRef<
  MemoryGraphOrbitSceneHandle,
  MemoryGraphOrbitSceneProps
>(function MemoryGraphOrbitScene(
  {
    nodes,
    links,
    centerNodeId,
    centerNodeLabel,
    centerNodeShortLabel,
    worldById,
    visibleNodeIds,
    searchMatchIds,
    selectedNodeId,
    maxRetrievalCount,
    onSelectNode,
    onCenterNodeClick,
    onRendererUnavailable,
  },
  ref,
) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const labelRendererRef = useRef<CSS2DRenderer | null>(null);
  const composerRef = useRef<EffectComposer | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const graphRootRef = useRef<THREE.Group | null>(null);
  const pmremRef = useRef<THREE.PMREMGenerator | null>(null);
  const keyLightRef = useRef<THREE.DirectionalLight | null>(null);
  const fillLightRef = useRef<THREE.DirectionalLight | null>(null);
  const spotLightRef = useRef<THREE.SpotLight | null>(null);
  const targetObjectRef = useRef<THREE.Object3D | null>(null);
  const sceneGroupRef = useRef<THREE.Group | null>(null);
  const boundsObjectRef = useRef<THREE.Object3D | null>(null);
  const animationFrameRef = useRef<number>(0);
  const cameraTweenRef = useRef<CameraTweenState | null>(null);
  const pointerStateRef = useRef<{ x: number; y: number } | null>(null);
  const raycasterRef = useRef(new THREE.Raycaster());
  const pointerVectorRef = useRef(new THREE.Vector2());
  const pickableObjectsRef = useRef<Array<{ object: THREE.Object3D; node: MemoryNode }>>([]);

  const fitView = useCallback((animated = true) => {
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    const boundsObject = boundsObjectRef.current;
    if (!camera || !controls || !boundsObject) {
      return;
    }

    const box = new THREE.Box3().setFromObject(boundsObject);
    if (box.isEmpty()) {
      return;
    }
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const dominant = Math.max(size.x, size.y * 1.14, size.z);
    const fov = THREE.MathUtils.degToRad(camera.fov);
    const distance = clampNumber(
      (dominant / (2 * Math.tan(fov / 2))) * 1.22,
      ORBIT_MIN_CAMERA_DISTANCE,
      ORBIT_MAX_CAMERA_DISTANCE,
    );
    const target = center.clone().add(new THREE.Vector3(0, -size.y * 0.02, 0));
    const position = target.clone().add(ORBIT_CAMERA_DIRECTION.clone().multiplyScalar(distance));

    if (!animated) {
      controls.target.copy(target);
      camera.position.copy(position);
      camera.lookAt(target);
      controls.update();
      cameraTweenRef.current = null;
      return;
    }

    cameraTweenRef.current = {
      fromPosition: camera.position.clone(),
      fromTarget: controls.target.clone(),
      toPosition: position,
      toTarget: target,
      startTime: performance.now(),
      durationMs: 460,
    };
  }, []);

  const dollyCamera = useCallback((factor: number) => {
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!camera || !controls) {
      return;
    }
    const offset = camera.position.clone().sub(controls.target);
    const nextLength = clampNumber(
      offset.length() * factor,
      ORBIT_MIN_CAMERA_DISTANCE * 0.82,
      ORBIT_MAX_CAMERA_DISTANCE * 1.08,
    );
    camera.position.copy(controls.target.clone().add(offset.setLength(nextLength)));
    controls.update();
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      zoomIn: () => dollyCamera(ORBIT_ZOOM_STEP),
      zoomOut: () => dollyCamera(1 / ORBIT_ZOOM_STEP),
      fitView: () => fitView(true),
    }),
    [dollyCamera, fitView],
  );

  useEffect(() => {
    const host = hostRef.current;
    if (!host) {
      return;
    }

    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(ORBIT_PALETTE.fog, 0.00034);
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(40, 1, 1, 4200);
    camera.position.set(-420, 280, 380);
    cameraRef.current = camera;

    const rendererCanvas = document.createElement("canvas");
    const rendererContext = createRendererContext(rendererCanvas);
    if (!rendererContext) {
      onRendererUnavailable?.();
      return;
    }

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        canvas: rendererCanvas,
        context: rendererContext,
        antialias: true,
        alpha: true,
        powerPreference: "high-performance",
      });
    } catch {
      onRendererUnavailable?.();
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.04;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.setClearColor(ORBIT_PALETTE.background, 0);
    renderer.domElement.className = "graph-orbit-webgl";
    host.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    const labelRenderer = new CSS2DRenderer();
    labelRenderer.domElement.className = "graph-orbit-label-layer";
    host.appendChild(labelRenderer.domElement);
    labelRendererRef.current = labelRenderer;

    const composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.03, 0.28, 1.18);
    composer.addPass(bloom);
    composerRef.current = composer;

    const pmrem = new THREE.PMREMGenerator(renderer);
    pmremRef.current = pmrem;
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.024).texture;

    const hemisphere = new THREE.HemisphereLight(
      ORBIT_PALETTE.skyLight,
      ORBIT_PALETTE.groundLight,
      0.88,
    );
    scene.add(hemisphere);

    const keyLight = new THREE.DirectionalLight(ORBIT_PALETTE.keyLight, 2.18);
    keyLight.position.set(-420, 620, 260);
    keyLight.castShadow = true;
    keyLight.shadow.mapSize.set(2048, 2048);
    keyLight.shadow.radius = 8;
    keyLight.shadow.bias = -0.00016;
    scene.add(keyLight);
    keyLightRef.current = keyLight;

    const fillLight = new THREE.DirectionalLight(ORBIT_PALETTE.fillLight, 1.02);
    fillLight.position.set(460, 280, 520);
    scene.add(fillLight);
    fillLightRef.current = fillLight;

    const spotTarget = new THREE.Object3D();
    spotTarget.position.set(0, 0, 0);
    scene.add(spotTarget);
    targetObjectRef.current = spotTarget;

    const spotLight = new THREE.SpotLight(
      ORBIT_PALETTE.rimLight,
      0.94,
      2100,
      Math.PI / 5.2,
      0.48,
      1.45,
    );
    spotLight.position.set(-280, 720, 90);
    spotLight.target = spotTarget;
    scene.add(spotLight);
    spotLightRef.current = spotLight;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.enablePan = false;
    controls.minDistance = ORBIT_MIN_CAMERA_DISTANCE * 0.82;
    controls.maxDistance = ORBIT_MAX_CAMERA_DISTANCE * 1.1;
    controls.minPolarAngle = 0.46;
    controls.maxPolarAngle = 1.42;
    controls.rotateSpeed = 0.66;
    controls.zoomSpeed = 0.82;
    controls.target.set(0, 0, 0);
    controlsRef.current = controls;

    const rootGroup = new THREE.Group();
    rootGroup.name = "orbit-root";
    scene.add(rootGroup);
    graphRootRef.current = rootGroup;

    const resize = () => {
      const width = host.clientWidth;
      const height = host.clientHeight;
      if (width === 0 || height === 0) {
        return;
      }
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
      composer.setSize(width, height);
      labelRenderer.setSize(width, height);
    };

    const renderFrame = () => {
      animationFrameRef.current = window.requestAnimationFrame(renderFrame);
      controls.update();

      const tween = cameraTweenRef.current;
      if (tween) {
        const progress = clampNumber(
          (performance.now() - tween.startTime) / tween.durationMs,
          0,
          1,
        );
        const eased = 1 - Math.pow(1 - progress, 3);
        camera.position.lerpVectors(tween.fromPosition, tween.toPosition, eased);
        controls.target.lerpVectors(tween.fromTarget, tween.toTarget, eased);
        if (progress >= 1) {
          cameraTweenRef.current = null;
        }
      }

      composer.render();
      labelRenderer.render(scene, camera);
    };

    resize();
    renderFrame();

    const resizeObserver = new ResizeObserver(() => resize());
    resizeObserver.observe(host);

    const onPointerDown = (event: PointerEvent) => {
      pointerStateRef.current = { x: event.clientX, y: event.clientY };
      host.classList.add("is-dragging");
    };

    const onPointerUp = (event: PointerEvent) => {
      host.classList.remove("is-dragging");
      const start = pointerStateRef.current;
      pointerStateRef.current = null;
      if (!start) {
        return;
      }
      const delta = Math.hypot(event.clientX - start.x, event.clientY - start.y);
      if (delta > 4) {
        return;
      }

      const bounds = renderer.domElement.getBoundingClientRect();
      pointerVectorRef.current.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
      pointerVectorRef.current.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1;
      raycasterRef.current.setFromCamera(pointerVectorRef.current, camera);
      const hits = raycasterRef.current.intersectObjects(
        pickableObjectsRef.current.map((entry) => entry.object),
        true,
      );
      if (hits.length === 0) {
        onSelectNode(null);
        return;
      }
      const match = pickableObjectsRef.current.find((entry) =>
        hits.some((hit) => hit.object === entry.object || hit.object.parent === entry.object),
      );
      if (!match) {
        onSelectNode(null);
        return;
      }
      if (match.node.id === centerNodeId) {
        onSelectNode(null);
        onCenterNodeClick?.();
        return;
      }
      onSelectNode(match.node);
    };

    renderer.domElement.addEventListener("pointerdown", onPointerDown);
    renderer.domElement.addEventListener("pointerup", onPointerUp);

    return () => {
      renderer.domElement.removeEventListener("pointerdown", onPointerDown);
      renderer.domElement.removeEventListener("pointerup", onPointerUp);
      resizeObserver.disconnect();
      window.cancelAnimationFrame(animationFrameRef.current);
      controls.dispose();
      composer.dispose();
      pmrem.dispose();
      if (graphRootRef.current && sceneGroupRef.current) {
        disposeHierarchy(sceneGroupRef.current);
        graphRootRef.current.remove(sceneGroupRef.current);
      }
      if (graphRootRef.current) {
        scene.remove(graphRootRef.current);
      }
      host.innerHTML = "";
      renderer.dispose();
      labelRenderer.domElement.remove();
      rendererRef.current = null;
      labelRendererRef.current = null;
      composerRef.current = null;
      controlsRef.current = null;
      sceneRef.current = null;
      cameraRef.current = null;
      graphRootRef.current = null;
      sceneGroupRef.current = null;
      boundsObjectRef.current = null;
      pickableObjectsRef.current = [];
    };
  }, [centerNodeId, onCenterNodeClick, onRendererUnavailable, onSelectNode]);

  useEffect(() => {
    const scene = sceneRef.current;
    const graphRoot = graphRootRef.current;
    const keyLight = keyLightRef.current;
    const targetObject = targetObjectRef.current;
    const fillLight = fillLightRef.current;
    const spotLight = spotLightRef.current;
    if (!scene || !graphRoot || !keyLight || !targetObject || !fillLight || !spotLight) {
      return;
    }

    if (sceneGroupRef.current) {
      disposeHierarchy(sceneGroupRef.current);
      graphRoot.remove(sceneGroupRef.current);
    }
    sceneGroupRef.current = null;
    boundsObjectRef.current = null;
    pickableObjectsRef.current = [];

    const sceneGroup = new THREE.Group();
    sceneGroup.name = "orbit-graph";
    const contentGroup = new THREE.Group();
    contentGroup.name = "orbit-content";
    sceneGroup.add(contentGroup);

    const visibleNodes = nodes.filter((node) => visibleNodeIds.has(node.id));
    const worldPositions = new Map<string, THREE.Vector3>(
      visibleNodes.map((node) => [node.id, getScenePosition(worldById.get(node.id))] as const),
    );
    const boundsSource = visibleNodes.length > 0 ? visibleNodes : nodes;
    const box = new THREE.Box3();
    boundsSource.forEach((node) => {
      const position = worldPositions.get(node.id) ?? getScenePosition(worldById.get(node.id));
      const radius = getOrbitNodeRadius(node, centerNodeId) * 1.24;
      box.expandByPoint(position.clone().addScalar(radius));
      box.expandByPoint(position.clone().addScalar(-radius));
    });
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const floorY = box.min.y - Math.max(24, size.y * 0.12);
    const stageRadius = clampNumber(Math.max(size.x, size.z) * 0.46 + 108, 118, 280);
    const stageDepth = stageRadius * 0.74;

    targetObject.position.set(center.x, center.y - size.y * 0.02, center.z);
    fillLight.position.set(center.x + 280, center.y + 160, center.z + 320);
    keyLight.position.set(center.x - 260, center.y + 340, center.z + 160);
    spotLight.position.set(center.x + 40, center.y + 280, center.z + 180);
    keyLight.target = targetObject;
    spotLight.target = targetObject;
    keyLight.shadow.camera.left = -stageRadius;
    keyLight.shadow.camera.right = stageRadius;
    keyLight.shadow.camera.top = stageRadius * 0.72;
    keyLight.shadow.camera.bottom = -stageRadius * 0.72;
    keyLight.shadow.camera.near = 120;
    keyLight.shadow.camera.far = 2200;
    keyLight.shadow.camera.updateProjectionMatrix();

    const stageShadowGeometry = new THREE.CircleGeometry(stageRadius * 1.04, 96);
    const stageShadowMaterial = new THREE.MeshBasicMaterial({
      color: ORBIT_PALETTE.shadowPool,
      transparent: true,
      opacity: 0.05,
      depthWrite: false,
    });
    const stageShadow = new THREE.Mesh(stageShadowGeometry, stageShadowMaterial);
    stageShadow.rotation.x = -Math.PI / 2;
    stageShadow.position.set(center.x, floorY - 1.2, center.z);
    stageShadow.scale.set(1.08, 0.84, 1);
    sceneGroup.add(stageShadow);

    const stageGeometry = new THREE.CircleGeometry(stageRadius, 96);
    const stageMaterial = new THREE.MeshPhysicalMaterial({
      color: ORBIT_PALETTE.stage,
      roughness: 0.98,
      metalness: 0.04,
      clearcoat: 0.08,
      clearcoatRoughness: 0.66,
      transparent: true,
      opacity: 0.82,
    });
    const stage = new THREE.Mesh(stageGeometry, stageMaterial);
    stage.rotation.x = -Math.PI / 2;
    stage.position.set(center.x, floorY, center.z);
    stage.scale.set(1, 0.82, 1);
    stage.receiveShadow = true;
    sceneGroup.add(stage);

    const stageGlowGeometry = new THREE.CircleGeometry(stageRadius * 0.6, 96);
    const stageGlowMaterial = new THREE.MeshBasicMaterial({
      color: ORBIT_PALETTE.stageGlow,
      transparent: true,
      opacity: 0.07,
      depthWrite: false,
    });
    const stageGlow = new THREE.Mesh(stageGlowGeometry, stageGlowMaterial);
    stageGlow.rotation.x = -Math.PI / 2;
    stageGlow.position.set(center.x, floorY + 0.8, center.z);
    stageGlow.scale.set(1, 0.62, 1);
    sceneGroup.add(stageGlow);

    const stageEdgeGeometry = new THREE.RingGeometry(stageRadius * 0.96, stageRadius, 128);
    const stageEdgeMaterial = new THREE.MeshBasicMaterial({
      color: ORBIT_PALETTE.stageEdge,
      transparent: true,
      opacity: 0.16,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const stageEdge = new THREE.Mesh(stageEdgeGeometry, stageEdgeMaterial);
    stageEdge.rotation.x = -Math.PI / 2;
    stageEdge.position.set(center.x, floorY + 1.2, center.z);
    stageEdge.scale.set(1, 0.82, 1);
    sceneGroup.add(stageEdge);

    const ringLarge = buildEllipseLine(stageRadius * 0.88, stageDepth * 0.58, ORBIT_PALETTE.ring, 0.11);
    ringLarge.position.set(center.x, floorY + 2, center.z);
    ringLarge.rotation.x = -Math.PI / 2;
    sceneGroup.add(ringLarge);

    const ringSmall = buildEllipseLine(stageRadius * 0.52, stageDepth * 0.3, ORBIT_PALETTE.ring, 0.13);
    ringSmall.position.set(center.x, floorY + 2.4, center.z);
    ringSmall.rotation.x = -Math.PI / 2;
    sceneGroup.add(ringSmall);

    const visibleLinkIds = new Set(visibleNodes.map((node) => node.id));
    links.forEach((link) => {
      if (!visibleLinkIds.has(link.sourceId) || !visibleLinkIds.has(link.targetId)) {
        return;
      }
      const source = worldPositions.get(link.sourceId);
      const target = worldPositions.get(link.targetId);
      if (!source || !target) {
        return;
      }
      const isDimmed =
        searchMatchIds !== null &&
        !searchMatchIds.has(link.sourceId) &&
        !searchMatchIds.has(link.targetId);
      const color = getEdgeBaseColor(link.edgeType);
      const opacity = isDimmed ? 0.18 : link.edgeType === "center" || link.edgeType === "parent" ? 0.7 : 0.52;
      const curve = buildEdgeCurve(source, target, link.edgeType);

      if (link.edgeType === "manual" || link.edgeType === "related") {
        const points = curve.getPoints(40);
        const geometry = new THREE.BufferGeometry().setFromPoints(points);
        const material = new THREE.LineDashedMaterial({
          color,
          transparent: true,
          opacity,
          dashSize: 9,
          gapSize: 7,
        });
        const line = new THREE.Line(geometry, material);
        line.computeLineDistances();
        contentGroup.add(line);
        return;
      }

      const tube = new THREE.TubeGeometry(
        curve,
        40,
        link.edgeType === "center" ? 1.8 : link.edgeType === "summary" ? 1.5 : 1.1,
        10,
        false,
      );
      const material = new THREE.MeshStandardMaterial({
        color,
        roughness: 0.54,
        metalness: 0.04,
        transparent: true,
        opacity,
        emissive: color.clone().multiplyScalar(link.edgeType === "center" ? 0.12 : 0.05),
      });
      const mesh = new THREE.Mesh(tube, material);
      mesh.castShadow = false;
      mesh.receiveShadow = true;
      contentGroup.add(mesh);
    });

    visibleNodes.forEach((node) => {
      const isCenter = node.id === centerNodeId;
      const position = worldPositions.get(node.id) ?? new THREE.Vector3();
      const radius = getOrbitNodeRadius(node, centerNodeId);
      const isDimmed = searchMatchIds !== null && !searchMatchIds.has(node.id) && !isCenter;
      const isSelected = selectedNodeId === node.id;
      const color = isCenter
        ? new THREE.Color(ORBIT_PALETTE.centerNode)
        : getOrbitNodeColor(node, maxRetrievalCount);

      const group = new THREE.Group();
      group.position.copy(position);
      group.userData.nodeId = node.id;

      const geometry = isFileMemoryNode(node)
        ? new THREE.BoxGeometry(radius * 1.32, radius * 1.04, radius * 0.72)
        : new THREE.SphereGeometry(radius, 48, 48);

      const material = new THREE.MeshPhysicalMaterial({
        color,
        emissive: color.clone().multiplyScalar(isCenter ? 0.16 : isSelected ? 0.1 : 0.04),
        roughness: isCenter ? 0.26 : 0.4,
        metalness: isCenter ? 0.12 : 0.04,
        clearcoat: isCenter ? 0.78 : 0.48,
        clearcoatRoughness: 0.32,
        reflectivity: 0.36,
        transparent: true,
        opacity: isDimmed ? 0.26 : 1,
        envMapIntensity: isCenter ? 0.62 : 0.36,
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      if (isFileMemoryNode(node)) {
        mesh.rotation.z = -0.08;
      }
      group.add(mesh);

      if (!isFileMemoryNode(node)) {
        const haloMaterial = new THREE.MeshBasicMaterial({
          color: isSelected
            ? ORBIT_PALETTE.centerHalo
            : color.clone().lerp(new THREE.Color(ORBIT_PALETTE.centerHalo), 0.22),
          transparent: true,
          opacity: isSelected ? 0.18 : isCenter ? 0.1 : 0.05,
          depthWrite: false,
        });
        const halo = new THREE.Mesh(
          new THREE.SphereGeometry(radius * (isCenter ? 1.26 : 1.18), 28, 28),
          haloMaterial,
        );
        group.add(halo);
      }

      const labelElement = createLabelElement(
        node,
        centerNodeId,
        centerNodeShortLabel,
        centerNodeLabel,
        isSelected,
        isDimmed,
      );
      const label = new CSS2DObject(labelElement);
      label.position.set(0, -(radius + (isCenter ? 32 : 22)), 0);
      group.add(label);

      contentGroup.add(group);
      pickableObjectsRef.current.push({ object: mesh, node });
    });

    graphRoot.add(sceneGroup);
    sceneGroupRef.current = sceneGroup;
    boundsObjectRef.current = contentGroup;
    fitView(false);

    return () => {
      disposeHierarchy(sceneGroup);
      graphRoot.remove(sceneGroup);
      if (sceneGroupRef.current === sceneGroup) {
        sceneGroupRef.current = null;
      }
      if (boundsObjectRef.current === contentGroup) {
        boundsObjectRef.current = null;
      }
    };
  }, [
    centerNodeId,
    centerNodeLabel,
    centerNodeShortLabel,
    fitView,
    links,
    maxRetrievalCount,
    nodes,
    onSelectNode,
    searchMatchIds,
    selectedNodeId,
    visibleNodeIds,
    worldById,
  ]);

  return <div ref={hostRef} className="graph-orbit-stage" />;
});

export default MemoryGraphOrbitScene;
