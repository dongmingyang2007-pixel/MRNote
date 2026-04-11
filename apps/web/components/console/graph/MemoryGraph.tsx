"use client";

import {
  useRef,
  useEffect,
  useState,
  useCallback,
  useMemo,
} from "react";
import { useTranslations } from "next-intl";
import * as d3 from "d3";
import {
  canPrimaryParentChildren,
  type MemoryNode,
  type MemoryEdge,
  getGraphNodeDisplayType,
  getMemoryCategoryPath,
  getMemoryCategoryLabel,
  getMemoryCategoryPrefixes,
  getMemoryKind,
  getMemoryNodeRole,
  getMemoryRetrievalCount,
  isFactMemoryNode,
  isAssistantRootMemoryNode,
  isFileMemoryNode,
  isStructureMemoryNode,
  isPinnedMemoryNode,
} from "@/hooks/useGraphData";
import { apiPost } from "@/lib/api";
import { useModal } from "@/components/ui/modal-dialog";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import GraphContextMenu from "./GraphContextMenu";
import NodeDetail from "./NodeDetail";
import GraphControls from "./GraphControls";
import GraphFilters, { type GraphFilterState } from "./GraphFilters";
import MemoryGraphOrbitScene, {
  type MemoryGraphOrbitSceneHandle,
} from "./MemoryGraphOrbitScene";

/* ── Types ─────────────────────────────────────── */

interface SimNode extends MemoryNode {
  x: number;
  y: number;
  fx: number | null;
  fy: number | null;
  vx?: number;
  vy?: number;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  id: string;
  edge_type: string;
  strength: number;
}

interface TreeLayoutTarget {
  x: number;
  y: number;
  angle: number;
  depth: number;
}

interface OrbitRotation {
  yaw: number;
  pitch: number;
}

interface OrbitProjectedNode {
  x: number;
  y: number;
  z: number;
  scale: number;
  radius: number;
  opacity: number;
  labelOpacity: number;
}

interface OrbitVector3 {
  x: number;
  y: number;
  z: number;
}

interface OrbitWorldNode extends OrbitVector3 {
  depth: number;
}

interface OrbitSceneLink {
  id: string;
  sourceId: string;
  targetId: string;
  edgeType: string;
  strength: number;
}

interface OrbitSceneRig {
  centerX: number;
  centerY: number;
  centerScale: number;
  floorY: number;
  keyLightX: number;
  keyLightY: number;
  fillLightX: number;
  fillLightY: number;
  rimLightX: number;
  rimLightY: number;
}

type GraphSelectionMode = "parent" | "children" | "related" | null;

interface MemoryGraphProps {
  nodes: MemoryNode[];
  edges: MemoryEdge[];
  assistantName?: string;
  renderMode?: "workbench" | "orbit";
  onNodeSelect: (node: MemoryNode | null) => void;
  onCenterNodeClick?: () => void;
  onCreateMemory: (content: string, category?: string) => Promise<void>;
  onUpdateMemory: (id: string, updates: Partial<MemoryNode>) => Promise<void>;
  onDeleteMemory: (id: string) => Promise<void>;
  onPromoteMemory: (id: string) => Promise<void>;
  onCreateEdge: (sourceId: string, targetId: string) => Promise<void>;
  onDeleteEdge: (id: string) => Promise<void>;
  onAttachFile: (memoryId: string, dataItemId: string) => Promise<void>;
  onDetachFile: (memoryFileId: string) => Promise<void>;
  searchQuery?: string;
  filters?: Partial<GraphFilterState>;
}

/* ── Constants ─────────────────────────────────── */

const CENTER_NODE_RADIUS = 36;
const MEMORY_NODE_RADIUS = 20;
const FILE_NODE_W = 16;
const FILE_NODE_H = 20;
const ASSISTANT_CENTER_ID = "__assistant_center__";
const FILE_ATTACH_DISTANCE = 42;
const FILE_ATTACH_SPREAD = 24;
const FILE_LINK_DISTANCE = 58;
const PARENT_LINK_DISTANCE = 112;
const CENTER_LINK_DISTANCE = 164;
const GRAPH_TOP_LEVEL_TARGET_ID = "__graph_top_level__";
const ORBIT_CAMERA_DISTANCE = 1240;
const ORBIT_INITIAL_ROTATION: OrbitRotation = {
  yaw: -0.96,
  pitch: 0.48,
};
const ORBIT_PITCH_RANGE = {
  min: 0.14,
  max: 0.92,
};
const ORBIT_VIEWPORT_OPTIONS = {
  fill: 0.9,
  maxScale: 2.65,
  minScale: 0.68,
  padding: 42,
  xBias: 0.5,
  yBias: 0.47,
};
const ORBIT_FOCUS_VIEWPORT_OPTIONS = {
  fill: 0.94,
  maxScale: 2.9,
  minScale: 0.86,
  padding: 48,
  xBias: 0.5,
  yBias: 0.46,
};
const COLORS = {
  permanent: "#6f5bff",
  temporary: "#3b82f6",
  core: "#7c5cfc",
  structure: "#9b8ec4",
  subject: "#8b6fff",
  concept: "#a78bfa",
  summary: "#d97706",
  file: "#8b7cc8",
  centerGradStart: "#6f5bff",
  centerGradEnd: "#9770ff",
};

/* ── Helpers ───────────────────────────────────── */

function getNodeSourceKinds(node: MemoryNode): string[] {
  if (isFileMemoryNode(node)) {
    return ["file_upload"];
  }
  const metadata = (node.metadata_json || {}) as Record<string, unknown>;
  if (metadata.promoted_by) {
    return ["promoted"];
  }
  if (node.source_conversation_id) {
    return ["conversation"];
  }
  return ["manual"];
}

function nodeRadius(node: MemoryNode, isCenter: boolean): number {
  if (isCenter) return CENTER_NODE_RADIUS;
  if (isFileMemoryNode(node)) return Math.max(FILE_NODE_W, FILE_NODE_H) / 2 + 4;
  const role = getMemoryNodeRole(node);
  if (role === "summary") return MEMORY_NODE_RADIUS + 4;
  if (role === "subject") return MEMORY_NODE_RADIUS + 4;
  if (role === "concept") return MEMORY_NODE_RADIUS + 2;
  if (role === "structure") return MEMORY_NODE_RADIUS - 1;
  if (isPinnedMemoryNode(node)) return MEMORY_NODE_RADIUS + 2;
  return MEMORY_NODE_RADIUS;
}

function getLabel(node: MemoryNode): string {
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
    return content.length > 12
      ? content.slice(0, 12) + "..."
      : content;
  }
  const categoryLabel = getMemoryCategoryLabel(node);
  if (categoryLabel) {
    return categoryLabel;
  }
  if (node.category) return node.category;
  return node.id.slice(0, 8);
}

function getMemoryNodeColor(node: MemoryNode, maxRetrievalCount: number): string {
  const kind = getMemoryKind(node);
  const role = getMemoryNodeRole(node);
  const baseColor = (() => {
    if (node.type === "temporary") {
      return COLORS.temporary;
    }
    if (role === "summary") {
      return COLORS.summary;
    }
    if (role === "structure") {
      return COLORS.structure;
    }
    if (role === "subject") {
      return COLORS.subject;
    }
    if (role === "concept") {
      return COLORS.concept;
    }
    if (isPinnedMemoryNode(node)) {
      return COLORS.core;
    }
    if (kind === "profile" || kind === "preference" || kind === "goal") {
      return COLORS.core;
    }
    return COLORS.permanent;
  })();

  const retrievalCount = getMemoryRetrievalCount(node);
  if (retrievalCount > 0 && maxRetrievalCount > 0) {
    const normalized = Math.log(retrievalCount + 1) / Math.log(maxRetrievalCount + 1);
    const targetColor =
      node.type === "temporary"
        ? "#215e99"
        : role === "summary"
          ? "#8a6715"
          : role === "structure"
            ? "#b1713d"
            : role === "subject"
              ? "#804650"
            : role === "concept"
              ? "#a94b38"
          : isPinnedMemoryNode(node) || kind === "profile" || kind === "preference" || kind === "goal"
            ? "#b85d39"
            : "#a32020";
    const intensity =
      node.type === "temporary"
        ? 0.22 + normalized * 0.44
        : 0.18 + normalized * 0.68;
    return d3.interpolateRgb(baseColor, targetColor)(Math.min(0.88, intensity));
  }
  return baseColor;
}

function truncateCenterLabel(label: string): string {
  const trimmed = label.trim();
  if (!trimmed) {
    return "AI";
  }
  return trimmed.length > 18 ? `${trimmed.slice(0, 18)}...` : trimmed;
}

function getCenterNodeMonogram(label: string): string {
  const trimmed = label.trim();
  if (!trimmed) {
    return "AI";
  }
  const compact = trimmed.replace(/\s+/g, "");
  if (/[\u4e00-\u9fff]/.test(compact)) {
    return compact.slice(0, 2);
  }
  return compact.slice(0, 2).toUpperCase();
}

function inferDroppedCategory(
  node: SimNode,
  allNodes: SimNode[],
  centerNodeId: string,
): string | null {
  if (node.id === centerNodeId || isFileMemoryNode(node)) {
    return null;
  }

  const nearbyCategories = allNodes
    .filter(
      (candidate) =>
        candidate.id !== node.id &&
        candidate.id !== centerNodeId &&
        !isFileMemoryNode(candidate) &&
        Boolean(candidate.category.trim()),
    )
    .map((candidate) => ({
      category: candidate.category,
      distance: Math.hypot(candidate.x - node.x, candidate.y - node.y),
    }))
    .sort((left, right) => left.distance - right.distance)
    .slice(0, 4);

  if (nearbyCategories.length === 0 || nearbyCategories[0].distance > 220) {
    return null;
  }

  const scores = new Map<string, number>();
  nearbyCategories.forEach((candidate) => {
    const weight = 1 / Math.max(candidate.distance, 24);
    scores.set(candidate.category, (scores.get(candidate.category) || 0) + weight);
  });

  return [...scores.entries()].sort((left, right) => right[1] - left[1])[0]?.[0] || null;
}

function getStableNodeSortKey(node: Pick<MemoryNode, "id" | "created_at" | "category" | "content">): string {
  return `${node.created_at}|${node.category}|${node.content}|${node.id}`;
}

function getFallbackAngle(seed: string): number {
  let hash = 0;
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) % 4096;
  }
  return (hash / 4096) * Math.PI * 2 - Math.PI;
}

function getBranchDirection(
  parentNode: Pick<SimNode, "id" | "x" | "y" | "parent_memory_id">,
  nodeById: Map<string, SimNode>,
  centerNodeId: string,
  seed: string,
): { x: number; y: number } {
  const anchorNode = parentNode.parent_memory_id
    ? nodeById.get(parentNode.parent_memory_id) ?? nodeById.get(centerNodeId)
    : nodeById.get(centerNodeId);
  const dx = parentNode.x - (anchorNode?.x ?? 0);
  const dy = parentNode.y - (anchorNode?.y ?? 0);
  const length = Math.hypot(dx, dy);

  if (length > 1) {
    return {
      x: dx / length,
      y: dy / length,
    };
  }

  const angle = getFallbackAngle(seed);
  return {
    x: Math.cos(angle),
    y: Math.sin(angle),
  };
}

function getAttachedFileTarget(
  fileNode: Pick<MemoryNode, "id" | "parent_memory_id">,
  siblingIndex: number,
  siblingCount: number,
  nodeById: Map<string, SimNode>,
  centerNodeId: string,
): { x: number; y: number } | null {
  const parentId = fileNode.parent_memory_id;
  if (!parentId) {
    return null;
  }

  const parentNode = nodeById.get(parentId);
  if (!parentNode) {
    return null;
  }

  const branchDirection = getBranchDirection(parentNode, nodeById, centerNodeId, fileNode.id);
  const tangent = { x: -branchDirection.y, y: branchDirection.x };
  const tangentOffset =
    siblingCount <= 1 ? 0 : (siblingIndex - (siblingCount - 1) / 2) * FILE_ATTACH_SPREAD;
  const radialDistance = nodeRadius(parentNode, parentNode.id === centerNodeId) + FILE_ATTACH_DISTANCE;

  return {
    x: parentNode.x + branchDirection.x * radialDistance + tangent.x * tangentOffset,
    y: parentNode.y + branchDirection.y * radialDistance + tangent.y * tangentOffset,
  };
}

function createFileAttachmentForce(centerNodeId: string): d3.Force<SimNode, SimLink> {
  let nodeById = new Map<string, SimNode>();
  let fileGroups: Array<{ parentId: string; files: SimNode[] }> = [];

  const rebuildCache = (nodes: SimNode[]) => {
    nodeById = new Map(nodes.map((node) => [node.id, node]));
    const groupedFiles = new Map<string, SimNode[]>();

    [...nodes]
      .filter((node) => isFileMemoryNode(node) && Boolean(node.parent_memory_id))
      .sort((left, right) => getStableNodeSortKey(left).localeCompare(getStableNodeSortKey(right)))
      .forEach((node) => {
        const parentId = node.parent_memory_id;
        if (!parentId) {
          return;
        }
        const siblings = groupedFiles.get(parentId) ?? [];
        siblings.push(node);
        groupedFiles.set(parentId, siblings);
      });

    fileGroups = [...groupedFiles.entries()].map(([parentId, files]) => ({ parentId, files }));
  };

  const force = ((alpha: number) => {
    fileGroups.forEach(({ files }) => {
      files.forEach((fileNode, index) => {
        const target = getAttachedFileTarget(
          fileNode,
          index,
          files.length,
          nodeById,
          centerNodeId,
        );
        if (!target) {
          return;
        }

        fileNode.x += (target.x - fileNode.x) * 0.42 * alpha;
        fileNode.y += (target.y - fileNode.y) * 0.42 * alpha;
        fileNode.vx = (fileNode.vx ?? 0) * 0.52 + (target.x - fileNode.x) * 0.08;
        fileNode.vy = (fileNode.vy ?? 0) * 0.52 + (target.y - fileNode.y) * 0.08;
      });
    });
  }) as d3.Force<SimNode, SimLink>;

  force.initialize = (nodes) => {
    rebuildCache(nodes as SimNode[]);
  };

  return force;
}

function buildEdgeKey(sourceId: string, targetId: string): string {
  return sourceId < targetId ? `${sourceId}::${targetId}` : `${targetId}::${sourceId}`;
}

function getSimLinkEndpointId(endpoint: SimLink["source"] | SimLink["target"]): string {
  if (typeof endpoint === "string") {
    return endpoint;
  }
  if (typeof endpoint === "number") {
    return String(endpoint);
  }
  return endpoint?.id ?? "";
}

function getGraphParentId(
  node: Pick<MemoryNode, "parent_memory_id" | "metadata_json">,
  nodeById?: Map<string, Pick<MemoryNode, "id">>,
): string | null {
  const graphParentId =
    typeof node.metadata_json?.graph_parent_memory_id === "string" &&
    node.metadata_json.graph_parent_memory_id
      ? node.metadata_json.graph_parent_memory_id
      : null;
  if (graphParentId && (!nodeById || nodeById.has(graphParentId))) {
    return graphParentId;
  }
  return node.parent_memory_id ?? null;
}

function isStructuralTreeEdgePair(
  nodeById: Map<string, Pick<MemoryNode, "id" | "parent_memory_id" | "metadata_json">>,
  sourceId: string,
  targetId: string,
  centerNodeId: string,
): boolean {
  if (sourceId === targetId) {
    return false;
  }
  const source = nodeById.get(sourceId);
  const target = nodeById.get(targetId);
  if (!source || !target) {
    return false;
  }
  if (getGraphParentId(target, nodeById) === sourceId) {
    return target.id !== centerNodeId;
  }
  if (getGraphParentId(source, nodeById) === targetId) {
    return source.id !== centerNodeId;
  }
  return false;
}

function isCenterStructuralTreeEdgePair(
  nodeById: Map<string, Pick<MemoryNode, "id" | "parent_memory_id" | "metadata_json">>,
  sourceId: string,
  targetId: string,
  centerNodeId: string,
): boolean {
  return (
    isStructuralTreeEdgePair(nodeById, sourceId, targetId, centerNodeId) &&
    (sourceId === centerNodeId || targetId === centerNodeId)
  );
}

function canGraphRepositionNode(node: Pick<MemoryNode, "id" | "metadata_json" | "category">, centerNodeId: string): boolean {
  return (
    node.id !== centerNodeId &&
    getGraphNodeDisplayType(node as MemoryNode) !== "file" &&
    getMemoryNodeRole(node as MemoryNode) !== "structure"
  );
}

function sortTreeChildren(left: SimNode, right: SimNode): number {
  const roleWeight = (node: SimNode) => {
    const role = getMemoryNodeRole(node);
    if (role === "structure") return 4;
    if (role === "subject") return 5;
    if (role === "concept") return 3;
    if (role === "summary") return 2;
    return 1;
  };
  const roleBias = roleWeight(right) - roleWeight(left);
  if (roleBias !== 0) {
    return roleBias;
  }
  return getStableNodeSortKey(left).localeCompare(getStableNodeSortKey(right));
}

function getTreeNodeDistance(node: SimNode, depth: number, centerNodeId: string): number {
  if (node.id === centerNodeId) {
    return 0;
  }
  if (depth <= 1) {
    return CENTER_LINK_DISTANCE + 18;
  }
  const role = getMemoryNodeRole(node);
  if (role === "structure") {
    return PARENT_LINK_DISTANCE + 4;
  }
  if (role === "summary") {
    return PARENT_LINK_DISTANCE + 14;
  }
  if (role === "subject") {
    return PARENT_LINK_DISTANCE + 10;
  }
  if (role === "concept") {
    return PARENT_LINK_DISTANCE + 18;
  }
  return PARENT_LINK_DISTANCE + 22;
}

function getChildAngle(
  parentTarget: TreeLayoutTarget,
  index: number,
  siblingCount: number,
): number {
  if (siblingCount <= 1) {
    return parentTarget.angle;
  }
  const spread =
    parentTarget.depth <= 1
      ? Math.min(1.18, 0.52 + siblingCount * 0.16)
      : Math.min(0.82, 0.34 + siblingCount * 0.11);
  const normalizedIndex = siblingCount <= 1
    ? 0
    : (index - (siblingCount - 1) / 2) / ((siblingCount - 1) / 2 || 1);
  return parentTarget.angle + normalizedIndex * (spread / 2);
}

function buildTreeLayoutTargets(nodes: SimNode[], centerNodeId: string): Map<string, TreeLayoutTarget> {
  const targets = new Map<string, TreeLayoutTarget>();
  targets.set(centerNodeId, { x: 0, y: 0, angle: -Math.PI / 2, depth: 0 });

  const treeNodes = nodes.filter((node) => !isFileMemoryNode(node));
  const nodeById = new Map(treeNodes.map((node) => [node.id, node]));
  const childrenByParent = new Map<string, SimNode[]>();

  treeNodes.forEach((node) => {
    if (node.id === centerNodeId) {
      return;
    }
    const graphParentId = getGraphParentId(node, nodeById);
    const parentId = graphParentId && nodeById.has(graphParentId) ? graphParentId : centerNodeId;
    const siblings = childrenByParent.get(parentId) ?? [];
    siblings.push(node);
    childrenByParent.set(parentId, siblings);
  });

  childrenByParent.forEach((siblings) => siblings.sort(sortTreeChildren));

  const rootChildren = childrenByParent.get(centerNodeId) ?? [];
  const rootStep = rootChildren.length > 0 ? (Math.PI * 2) / rootChildren.length : 0;

  const assignNodeTarget = (
    node: SimNode,
    parentTarget: TreeLayoutTarget,
    angle: number,
  ) => {
    const hasStoredPosition =
      typeof node.position_x === "number" && typeof node.position_y === "number";
    const target = hasStoredPosition
      ? {
          x: node.position_x as number,
          y: node.position_y as number,
        }
      : {
          x: parentTarget.x + Math.cos(angle) * getTreeNodeDistance(node, parentTarget.depth + 1, centerNodeId),
          y: parentTarget.y + Math.sin(angle) * getTreeNodeDistance(node, parentTarget.depth + 1, centerNodeId),
        };
    const resolvedAngle = hasStoredPosition
      ? Math.atan2(target.y - parentTarget.y, target.x - parentTarget.x) || angle
      : angle;
    const nextTarget: TreeLayoutTarget = {
      x: target.x,
      y: target.y,
      angle: resolvedAngle,
      depth: parentTarget.depth + 1,
    };
    targets.set(node.id, nextTarget);

    const children = childrenByParent.get(node.id) ?? [];
    children.forEach((child, index) => {
      assignNodeTarget(
        child,
        nextTarget,
        getChildAngle(nextTarget, index, children.length),
      );
    });
  };

  rootChildren.forEach((child, index) => {
    const baseAngle = rootChildren.length <= 1
      ? -Math.PI / 2
      : -Math.PI / 2 + index * rootStep;
    assignNodeTarget(
      child,
      targets.get(centerNodeId)!,
      baseAngle,
    );
  });

  return targets;
}

function createTreeScaffoldForce(centerNodeId: string): d3.Force<SimNode, SimLink> {
  let layoutTargets = new Map<string, TreeLayoutTarget>();
  let simulationNodes: SimNode[] = [];

  const force = ((alpha: number) => {
    simulationNodes.forEach((node) => {
      if (node.id === centerNodeId || isFileMemoryNode(node) || node.fx != null || node.fy != null) {
        return;
      }
      const target = layoutTargets.get(node.id);
      if (!target) {
        return;
      }
      const spring =
        typeof node.position_x === "number" && typeof node.position_y === "number"
          ? 0.05
          : getMemoryNodeRole(node) === "structure"
            ? 0.22
            : getMemoryNodeRole(node) === "subject"
              ? 0.18
            : 0.14;
      node.vx = (node.vx ?? 0) + (target.x - node.x) * spring * alpha;
      node.vy = (node.vy ?? 0) + (target.y - node.y) * spring * alpha;
    });
  }) as d3.Force<SimNode, SimLink>;

  force.initialize = (nodes) => {
    simulationNodes = nodes as SimNode[];
    layoutTargets = buildTreeLayoutTargets(simulationNodes, centerNodeId);
  };

  return force;
}

function clampNumber(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function addOrbitVector(left: OrbitVector3, right: OrbitVector3): OrbitVector3 {
  return {
    x: left.x + right.x,
    y: left.y + right.y,
    z: left.z + right.z,
  };
}

function scaleOrbitVector(vector: OrbitVector3, scalar: number): OrbitVector3 {
  return {
    x: vector.x * scalar,
    y: vector.y * scalar,
    z: vector.z * scalar,
  };
}

function orbitVectorLength(vector: OrbitVector3): number {
  return Math.hypot(vector.x, vector.y, vector.z);
}

function normalizeOrbitVector(
  vector: OrbitVector3,
  fallback: OrbitVector3 = { x: 1, y: 0, z: 0 },
): OrbitVector3 {
  const length = orbitVectorLength(vector);
  if (length < 1e-4) {
    return fallback;
  }
  return scaleOrbitVector(vector, 1 / length);
}

function crossOrbitVector(left: OrbitVector3, right: OrbitVector3): OrbitVector3 {
  return {
    x: left.y * right.z - left.z * right.y,
    y: left.z * right.x - left.x * right.z,
    z: left.x * right.y - left.y * right.x,
  };
}

function getOrbitBasis(forward: OrbitVector3): { right: OrbitVector3; up: OrbitVector3 } {
  const reference =
    Math.abs(forward.y) > 0.88
      ? { x: 0, y: 0, z: 1 }
      : { x: 0, y: 1, z: 0 };
  const right = normalizeOrbitVector(
    crossOrbitVector(reference, forward),
    { x: 1, y: 0, z: 0 },
  );
  const up = normalizeOrbitVector(
    crossOrbitVector(forward, right),
    { x: 0, y: 1, z: 0 },
  );
  return { right, up };
}

function getOrbitRootRadius(node: SimNode): number {
  const role = getMemoryNodeRole(node);
  if (role === "subject") return 342;
  if (role === "concept") return 320;
  if (role === "summary") return 304;
  if (role === "structure") return 286;
  return 312;
}

function getOrbitChildDistance(node: SimNode, depth: number): number {
  if (isFileMemoryNode(node)) {
    return 54;
  }
  const role = getMemoryNodeRole(node);
  const baseDistance =
    depth <= 2
      ? 184
      : depth === 3
        ? 164
        : 144;
  const roleOffset =
    role === "subject"
      ? 16
      : role === "concept"
        ? 10
        : role === "structure"
          ? -10
          : role === "summary"
            ? 2
            : 0;
  const tempOffset = node.type === "temporary" ? -8 : 0;
  return baseDistance + roleOffset + tempOffset;
}

function getOrbitVerticalBias(node: SimNode): number {
  const role = getMemoryNodeRole(node);
  const roleBias =
    role === "subject"
      ? 0.24
      : role === "concept"
        ? 0.16
        : role === "structure"
          ? -0.14
          : role === "summary"
            ? 0.08
            : 0;
  const stateBias =
    (isPinnedMemoryNode(node) ? 0.06 : 0) +
    (node.type === "temporary" ? -0.1 : 0);
  return roleBias + stateBias;
}

function getOrbitRootDirection(
  node: SimNode,
  branchIndex: number,
  branchCount: number,
): OrbitVector3 {
  const baseAngle =
    branchCount <= 1
      ? -Math.PI * 0.12
      : -Math.PI / 2 + (branchIndex / branchCount) * Math.PI * 2;
  const seedAngle = getFallbackAngle(node.id);
  const azimuth = baseAngle + Math.sin(seedAngle) * 0.3;
  const pitch = clampNumber(
    getOrbitVerticalBias(node) + Math.sin(branchIndex * 1.7) * 0.12,
    -0.3,
    0.36,
  );
  return normalizeOrbitVector(
    {
      x: Math.cos(azimuth) * Math.cos(pitch),
      y: Math.sin(pitch),
      z: Math.sin(azimuth) * Math.cos(pitch),
    },
    { x: 1, y: 0, z: 0 },
  );
}

function getOrbitChildDirection(
  node: SimNode,
  parentForward: OrbitVector3,
  depth: number,
  siblingIndex: number,
  siblingCount: number,
): OrbitVector3 {
  const { right, up } = getOrbitBasis(parentForward);
  const normalizedIndex =
    siblingCount <= 1
      ? 0
      : (siblingIndex - (siblingCount - 1) / 2) /
        (((siblingCount - 1) / 2) || 1);
  const lateralSpread =
    depth <= 2
      ? 1.2
      : depth === 3
        ? 0.94
        : 0.72;
  const verticalSpread =
    depth <= 2
      ? 0.42
      : depth === 3
        ? 0.28
        : 0.18;
  const seedAngle = getFallbackAngle(node.id);
  const lateralBias =
    Math.sin(normalizedIndex * (Math.PI / 2)) * lateralSpread +
    Math.cos(seedAngle) * 0.06;
  const verticalBias =
    getOrbitVerticalBias(node) +
    (siblingIndex % 2 === 0 ? 1 : -1) * (0.05 + Math.abs(normalizedIndex) * verticalSpread) +
    Math.sin(seedAngle) * 0.04;

  return normalizeOrbitVector(
    addOrbitVector(
      addOrbitVector(
        scaleOrbitVector(parentForward, 1.08),
        scaleOrbitVector(right, lateralBias),
      ),
      scaleOrbitVector(up, verticalBias),
    ),
    parentForward,
  );
}

function buildViewportTransform(
  width: number,
  height: number,
  nodes: SimNode[],
  centerNodeId: string,
  visibleNodeIds: Set<string>,
  orbitProjectedNodes: Map<string, OrbitProjectedNode> | null,
  options?: {
    fill?: number;
    maxScale?: number;
    minScale?: number;
    padding?: number;
    xBias?: number;
    yBias?: number;
  },
): d3.ZoomTransform | null {
  const fill = options?.fill ?? 0.85;
  const maxScale = options?.maxScale ?? 5;
  const minScale = options?.minScale ?? 0.1;
  const padding = options?.padding ?? 20;
  const xBias = options?.xBias ?? 0.5;
  const yBias = options?.yBias ?? 0.5;

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;

  nodes.forEach((node) => {
    if (!visibleNodeIds.has(node.id)) {
      return;
    }
    const projected = orbitProjectedNodes?.get(node.id) ?? null;
    const radius =
      (projected?.radius ?? nodeRadius(node, node.id === centerNodeId)) + padding;
    const nodeX = projected?.x ?? node.x;
    const nodeY = projected?.y ?? node.y;
    minX = Math.min(minX, nodeX - radius);
    minY = Math.min(minY, nodeY - radius);
    maxX = Math.max(maxX, nodeX + radius);
    maxY = Math.max(maxY, nodeY + radius);
  });

  if (!isFinite(minX) || !isFinite(minY) || !isFinite(maxX) || !isFinite(maxY)) {
    return null;
  }

  const boundsWidth = Math.max(1, maxX - minX);
  const boundsHeight = Math.max(1, maxY - minY);
  const scale = clampNumber(
    Math.min(width / boundsWidth, height / boundsHeight) * fill,
    minScale,
    maxScale,
  );
  const centerX = (minX + maxX) / 2;
  const centerY = (minY + maxY) / 2;

  return d3.zoomIdentity
    .translate(width * xBias - centerX * scale, height * yBias - centerY * scale)
    .scale(scale);
}

function buildOrbitWorldMap(
  nodes: SimNode[],
  centerNodeId: string,
  nodeById: Map<string, SimNode>,
  maxRetrievalCount: number,
): Map<string, OrbitWorldNode> {
  const worldById = new Map<string, OrbitWorldNode>([
    [centerNodeId, { x: 0, y: 0, z: 0, depth: 0 }],
  ]);
  const directionById = new Map<string, OrbitVector3>([
    [centerNodeId, { x: 0, y: 0, z: 1 }],
  ]);

  const treeNodes = nodes.filter((node) => !isFileMemoryNode(node));
  const treeNodeById = new Map(treeNodes.map((node) => [node.id, node] as const));
  const childrenByParent = new Map<string, SimNode[]>();
  const fileNodesByParent = new Map<string, SimNode[]>();

  nodes.forEach((node) => {
    if (node.id === centerNodeId) {
      return;
    }
    if (isFileMemoryNode(node)) {
      const parentId = node.parent_memory_id;
      if (!parentId || !nodeById.has(parentId)) {
        return;
      }
      const siblings = fileNodesByParent.get(parentId) ?? [];
      siblings.push(node);
      fileNodesByParent.set(parentId, siblings);
      return;
    }

    const graphParentId = getGraphParentId(node, treeNodeById);
    const parentId =
      graphParentId && graphParentId !== node.id && treeNodeById.has(graphParentId)
        ? graphParentId
        : centerNodeId;
    const siblings = childrenByParent.get(parentId) ?? [];
    siblings.push(node);
    childrenByParent.set(parentId, siblings);
  });

  childrenByParent.forEach((siblings) => siblings.sort(sortTreeChildren));
  fileNodesByParent.forEach((siblings) =>
    siblings.sort((left, right) =>
      getStableNodeSortKey(left).localeCompare(getStableNodeSortKey(right)),
    ),
  );

  const rootChildren = childrenByParent.get(centerNodeId) ?? [];

  const placeNode = (
    node: SimNode,
    parentId: string,
    parentPosition: OrbitWorldNode,
    parentForward: OrbitVector3,
    depth: number,
    siblingIndex: number,
    siblingCount: number,
  ) => {
    const forward =
      parentId === centerNodeId
        ? getOrbitRootDirection(node, siblingIndex, Math.max(siblingCount, 1))
        : getOrbitChildDirection(node, parentForward, depth, siblingIndex, siblingCount);
    const distance =
      parentId === centerNodeId
        ? getOrbitRootRadius(node)
        : getOrbitChildDistance(node, depth);
    let position = addOrbitVector(
      parentPosition,
      scaleOrbitVector(forward, distance),
    );
    const outwardBias = normalizeOrbitVector(position, forward);
    const retrievalCount = getMemoryRetrievalCount(node);
    const retrievalLift =
      maxRetrievalCount > 0
        ? (Math.log(retrievalCount + 1) / Math.log(maxRetrievalCount + 1)) * 12
        : 0;
    position = addOrbitVector(
      position,
      scaleOrbitVector(outwardBias, 10 + retrievalLift),
    );

    const worldNode: OrbitWorldNode = {
      x: position.x,
      y: position.y,
      z: position.z,
      depth,
    };
    worldById.set(node.id, worldNode);
    directionById.set(node.id, forward);

    const children = childrenByParent.get(node.id) ?? [];
    children.forEach((child, childIndex) => {
      placeNode(
        child,
        node.id,
        worldNode,
        forward,
        depth + 1,
        childIndex,
        children.length,
      );
    });
  };

  rootChildren.forEach((child, index) => {
    placeNode(
      child,
      centerNodeId,
      worldById.get(centerNodeId)!,
      directionById.get(centerNodeId)!,
      1,
      index,
      rootChildren.length,
    );
  });

  fileNodesByParent.forEach((files, parentId) => {
    const parentPosition = worldById.get(parentId);
    if (!parentPosition) {
      return;
    }
    const parentForward =
      directionById.get(parentId) ??
      normalizeOrbitVector(parentPosition, { x: 1, y: 0, z: 0 });
    const { right, up } = getOrbitBasis(parentForward);
    files.forEach((fileNode, index) => {
      const normalizedIndex =
        files.length <= 1
          ? 0
          : (index - (files.length - 1) / 2) / (((files.length - 1) / 2) || 1);
      const tangentOffset = normalizedIndex * 28;
      const stackOffset =
        (index % 2 === 0 ? 1 : -1) * (9 + Math.abs(normalizedIndex) * 8);
      const anchor = addOrbitVector(
        parentPosition,
        scaleOrbitVector(parentForward, 44),
      );
      const position = addOrbitVector(
        addOrbitVector(anchor, scaleOrbitVector(right, tangentOffset)),
        scaleOrbitVector(up, stackOffset),
      );
      worldById.set(fileNode.id, {
        x: position.x,
        y: position.y,
        z: position.z,
        depth: parentPosition.depth + 1,
      });
    });
  });

  return worldById;
}

function rotateOrbitPoint(
  x: number,
  y: number,
  z: number,
  rotation: OrbitRotation,
): { x: number; y: number; z: number } {
  const yawCos = Math.cos(rotation.yaw);
  const yawSin = Math.sin(rotation.yaw);
  const pitchCos = Math.cos(rotation.pitch);
  const pitchSin = Math.sin(rotation.pitch);

  const yawX = x * yawCos - z * yawSin;
  const yawZ = x * yawSin + z * yawCos;

  return {
    x: yawX,
    y: y * pitchCos - yawZ * pitchSin,
    z: y * pitchSin + yawZ * pitchCos,
  };
}

function buildOrbitProjectionMap(
  nodes: SimNode[],
  centerNodeId: string,
  worldById: Map<string, OrbitWorldNode>,
  rotation: OrbitRotation,
): Map<string, OrbitProjectedNode> {
  const projections = new Map<string, OrbitProjectedNode>();

  nodes.forEach((node) => {
    const worldNode = worldById.get(node.id) ?? {
      x: node.x,
      y: node.y,
      z: 0,
      depth: node.id === centerNodeId ? 0 : 1,
    };
    const rotated = rotateOrbitPoint(
      worldNode.x,
      worldNode.y,
      worldNode.z,
      rotation,
    );
    const perspective = clampNumber(
      ORBIT_CAMERA_DISTANCE / (ORBIT_CAMERA_DISTANCE - rotated.z + 320),
      0.76,
      1.42,
    );
    const fade = clampNumber(
      (rotated.z + ORBIT_CAMERA_DISTANCE * 0.62) / (ORBIT_CAMERA_DISTANCE * 1.22),
      0.74,
      1,
    );
    const opacity = clampNumber((0.56 + perspective * 0.34) * fade, 0.72, 1);
    const labelOpacity = clampNumber((0.62 + perspective * 0.28) * fade, 0.74, 1);

    projections.set(node.id, {
      x: rotated.x * perspective,
      y: rotated.y * perspective * 0.92,
      z: rotated.z,
      scale: perspective,
      radius:
        nodeRadius(node, node.id === centerNodeId) *
        clampNumber(perspective, 0.82, 1.24),
      opacity,
      labelOpacity,
    });
  });

  return projections;
}

function getOrbitLabelText(node: SimNode, label: string): string {
  const trimmed = label.trim();
  if (!trimmed) {
    return label;
  }
  const maxLength = isFileMemoryNode(node) ? 13 : 10;
  return trimmed.length > maxLength ? `${trimmed.slice(0, maxLength)}…` : trimmed;
}

function traceRoundedRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
): void {
  const resolvedRadius = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + resolvedRadius, y);
  ctx.lineTo(x + width - resolvedRadius, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + resolvedRadius);
  ctx.lineTo(x + width, y + height - resolvedRadius);
  ctx.quadraticCurveTo(x + width, y + height, x + width - resolvedRadius, y + height);
  ctx.lineTo(x + resolvedRadius, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - resolvedRadius);
  ctx.lineTo(x, y + resolvedRadius);
  ctx.quadraticCurveTo(x, y, x + resolvedRadius, y);
  ctx.closePath();
}

/* ── Component ─────────────────────────────────── */

export default function MemoryGraph(props: MemoryGraphProps) {
  const t = useTranslations("console-assistants");
  const {
    nodes,
    edges,
    assistantName,
    renderMode = "workbench",
    onNodeSelect,
    onCenterNodeClick,
    onCreateMemory,
    onUpdateMemory,
    onDeleteMemory,
    onPromoteMemory,
    onCreateEdge,
    onDeleteEdge,
    onAttachFile,
    onDetachFile,
    searchQuery: externalSearchQuery,
    filters: externalFilters,
  } = props;
  const isOrbitMode = renderMode === "orbit";
  /* refs */
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const orbitSceneRef = useRef<MemoryGraphOrbitSceneHandle | null>(null);
  const simRef = useRef<d3.Simulation<SimNode, SimLink> | null>(null);
  const transformRef = useRef(d3.zoomIdentity);
  const zoomBehaviorRef = useRef<d3.ZoomBehavior<HTMLCanvasElement, unknown> | null>(null);
  const animFrameRef = useRef<number>(0);
  const drawRef = useRef<() => void>(() => {});
  const orbitRotationRef = useRef<OrbitRotation>(ORBIT_INITIAL_ROTATION);
  const orbitAutoFrameKeyRef = useRef<string | null>(null);
  const projectedNodeCacheRef = useRef<Map<string, OrbitProjectedNode>>(new Map());
  const connectStartRef = useRef<SimNode | null>(null);
  const connectModeRef = useRef<"parent" | "manual" | null>(null);
  const connectPointerRef = useRef<{ x: number; y: number } | null>(null);
  const suppressClickRef = useRef(false);
  const editModeRef = useRef<GraphSelectionMode>(null);
  const selectedNodeRef = useRef<MemoryNode | null>(null);
  const selectableNodeIdsRef = useRef<Set<string>>(new Set());
  const visibleNodeIdsRef = useRef<Set<string>>(new Set());

  /* state */
  const [selectedNode, setSelectedNode] = useState<MemoryNode | null>(null);
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    node: MemoryNode | null;
    visible: boolean;
  }>({ x: 0, y: 0, node: null, visible: false });
  const [localSearch, setLocalSearch] = useState("");
  const [filterState, setFilterState] = useState<GraphFilterState>({
    types: [],
    categories: [],
    sources: [],
    timeRange: "all",
  });
  const [filtersCollapsed, setFiltersCollapsed] = useState(false);
  const [semanticMatchIds, setSemanticMatchIds] = useState<Set<string> | null>(null);
  const [createMemoryOpen, setCreateMemoryOpen] = useState(false);
  const [createMemoryContent, setCreateMemoryContent] = useState("");
  const [createMemoryCategory, setCreateMemoryCategory] = useState("");
  const [creatingMemory, setCreatingMemory] = useState(false);
  const [editMode, setEditMode] = useState<GraphSelectionMode>(null);
  const [editSelectionIds, setEditSelectionIds] = useState<string[]>([]);
  const [editPending, setEditPending] = useState(false);
  const [orbitWebglUnavailable, setOrbitWebglUnavailable] = useState(false);

  const modal = useModal();

  const searchQuery = externalSearchQuery ?? localSearch;
  const addMemoryTitle = t("graph.addMemory");
  const centerNodeLabel = assistantName?.trim() || t("graph.centerNodeLabel");
  const centerNodeShortLabel = getCenterNodeMonogram(
    assistantName?.trim() || t("graph.centerNodeShort"),
  );
  const addMemoryPrompt = t("graph.addMemoryPrompt");
  const confirmDeleteMessage = t("graph.confirmDelete");

  useEffect(() => {
    setFiltersCollapsed(renderMode === "orbit");
  }, [renderMode]);

  const openCreateMemoryDialog = useCallback(() => {
    setCreateMemoryContent("");
    setCreateMemoryCategory("");
    setCreateMemoryOpen(true);
  }, []);

  const closeCreateMemoryDialog = useCallback(() => {
    if (creatingMemory) {
      return;
    }
    setCreateMemoryOpen(false);
    setCreateMemoryContent("");
    setCreateMemoryCategory("");
  }, [creatingMemory]);

  const handleCreateMemorySubmit = useCallback(async () => {
    const content = createMemoryContent.trim();
    if (!content || creatingMemory) {
      return;
    }
    setCreatingMemory(true);
    try {
      await onCreateMemory(content, createMemoryCategory.trim() || undefined);
      setCreateMemoryOpen(false);
      setCreateMemoryContent("");
      setCreateMemoryCategory("");
    } finally {
      setCreatingMemory(false);
    }
  }, [createMemoryCategory, createMemoryContent, creatingMemory, onCreateMemory]);

  useEffect(() => {
    const trimmedQuery = searchQuery.trim();
    const projectId = nodes.find((node) => !isFileMemoryNode(node))?.project_id;

    if (!trimmedQuery || !projectId) {
      setSemanticMatchIds(null);
      return;
    }

    let cancelled = false;
    const timer = window.setTimeout(() => {
      void apiPost<Array<{ memory: { id: string } }>>("/api/v1/memory/search", {
        project_id: projectId,
        query: trimmedQuery,
        top_k: 10,
      })
        .then((results) => {
          if (cancelled) return;
          const ids = new Set<string>();
          (Array.isArray(results) ? results : []).forEach((result) => {
            const memoryId = result?.memory?.id;
            if (!memoryId) return;
            ids.add(memoryId);
            nodes.forEach((candidate) => {
              if (candidate.parent_memory_id === memoryId && isFileMemoryNode(candidate)) {
                ids.add(candidate.id);
              }
            });
          });
          setSemanticMatchIds(ids);
        })
        .catch(() => {
          if (!cancelled) {
            setSemanticMatchIds(null);
          }
        });
    }, 180);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [nodes, searchQuery]);

  useEffect(() => {
    if (!selectedNode) {
      return;
    }
    const refreshed = nodes.find((candidate) => candidate.id === selectedNode.id);
    if (!refreshed) {
      setSelectedNode(null);
      onNodeSelect(null);
      return;
    }
    if (refreshed !== selectedNode) {
      setSelectedNode(refreshed);
    }
  }, [nodes, onNodeSelect, selectedNode]);

  useEffect(() => {
    if (!selectedNode && editMode) {
      setEditMode(null);
      setEditSelectionIds([]);
    }
  }, [editMode, selectedNode]);

  useEffect(() => {
    if (editMode !== "children" || !selectedNode) {
      return;
    }
    if (!canPrimaryParentChildren(selectedNode)) {
      setEditMode(null);
      setEditSelectionIds([]);
    }
  }, [editMode, selectedNode]);

  useEffect(() => {
    editModeRef.current = editMode;
  }, [editMode]);

  useEffect(() => {
    selectedNodeRef.current = selectedNode;
  }, [selectedNode]);

  /* ── Derive sim data ────────────────────────── */

  const { simNodes, simLinks, centerNodeId } = useMemo(() => {
    const rootNode = nodes.find((node) => isAssistantRootMemoryNode(node)) ?? null;
    const seedNode =
      nodes.find((node) => isFactMemoryNode(node)) ?? rootNode ?? nodes[0] ?? null;
    const now = new Date().toISOString();
    const cId = rootNode?.id ?? ASSISTANT_CENTER_ID;
    const assistantNode: SimNode | null = rootNode
      ? null
      : {
          id: cId,
          workspace_id: seedNode?.workspace_id ?? "",
          project_id: seedNode?.project_id ?? "",
          content: centerNodeLabel,
          category: "assistant",
          type: "permanent",
          source_conversation_id: null,
          parent_memory_id: null,
          position_x: 0,
          position_y: 0,
          metadata_json: { node_kind: "assistant-center" },
          created_at: seedNode?.created_at ?? now,
          updated_at: seedNode?.updated_at ?? now,
          x: 0,
          y: 0,
          fx: 0,
          fy: 0,
        };

    const provisionalNonFileNodes: SimNode[] = nodes
      .filter((node) => !isFileMemoryNode(node))
      .map((node) => {
        const isRoot = isAssistantRootMemoryNode(node);
        return {
          ...node,
          x: isRoot ? 0 : (node.position_x ?? 0),
          y: isRoot ? 0 : (node.position_y ?? 0),
          fx: isRoot ? 0 : null,
          fy: isRoot ? 0 : null,
        };
      });
    const treeTargets = buildTreeLayoutTargets(
      assistantNode ? [assistantNode, ...provisionalNonFileNodes] : provisionalNonFileNodes,
      cId,
    );
    const nonFileNodes: SimNode[] = provisionalNonFileNodes.map((node) => {
      const isRoot = isAssistantRootMemoryNode(node);
      const target = treeTargets.get(node.id);
      return {
        ...node,
        x: isRoot ? 0 : (node.position_x ?? target?.x ?? (Math.random() - 0.5) * 320),
        y: isRoot ? 0 : (node.position_y ?? target?.y ?? (Math.random() - 0.5) * 320),
      };
    });

    const seededNodeById = new Map<string, SimNode>(
      (assistantNode ? [assistantNode, ...nonFileNodes] : nonFileNodes).map((node) => [node.id, node]),
    );

    const fileSiblingOrder = new Map<string, { index: number; count: number }>();
    const fileNodesByParent = new Map<string, MemoryNode[]>();
    nodes
      .filter((node) => isFileMemoryNode(node) && Boolean(node.parent_memory_id))
      .sort((left, right) => getStableNodeSortKey(left).localeCompare(getStableNodeSortKey(right)))
      .forEach((node) => {
        const parentId = node.parent_memory_id;
        if (!parentId) {
          return;
        }
        const siblings = fileNodesByParent.get(parentId) ?? [];
        siblings.push(node);
        fileNodesByParent.set(parentId, siblings);
      });

    fileNodesByParent.forEach((siblings) => {
      siblings.forEach((node, index) => {
        fileSiblingOrder.set(node.id, { index, count: siblings.length });
      });
    });

    const fileNodes: SimNode[] = nodes
      .filter((node) => isFileMemoryNode(node))
      .map((node) => {
        const siblingPlacement = fileSiblingOrder.get(node.id);
        const attachedTarget = siblingPlacement
          ? getAttachedFileTarget(
              node,
              siblingPlacement.index,
              siblingPlacement.count,
              seededNodeById,
              cId,
            )
          : null;
        return {
          ...node,
          x: node.position_x ?? attachedTarget?.x ?? (Math.random() - 0.5) * 400,
          y: node.position_y ?? attachedTarget?.y ?? (Math.random() - 0.5) * 400,
          fx: null,
          fy: null,
        };
      });

    const memoryNodes: SimNode[] = [...nonFileNodes, ...fileNodes];

    const sn: SimNode[] = assistantNode ? [assistantNode, ...memoryNodes] : memoryNodes;

    const nodeIdSet = new Set(sn.map((n) => n.id));
    const simNodeById = new Map(sn.map((node) => [node.id, node] as const));
    const sl: SimLink[] = edges
      .filter(
        (e) => nodeIdSet.has(e.source_memory_id) && nodeIdSet.has(e.target_memory_id)
      )
      .map((e) => ({
        source: e.source_memory_id,
        target: e.target_memory_id,
        id: e.id,
        edge_type: e.edge_type,
        strength: e.strength,
      }));

    const structuralEdgeKeys = new Set(
      sl
        .filter((link) =>
          isStructuralTreeEdgePair(
            simNodeById,
            String(link.source),
            String(link.target),
            cId,
          ),
        )
        .map((link) => buildEdgeKey(String(link.source), String(link.target))),
    );

    nodes
      .filter(
        (node) =>
          !isFileMemoryNode(node) &&
          !isAssistantRootMemoryNode(node) &&
          Boolean(getGraphParentId(node, simNodeById)) &&
          getGraphParentId(node, simNodeById) !== cId &&
          nodeIdSet.has(getGraphParentId(node, simNodeById) || ""),
      )
      .forEach((node) => {
        const parentId = getGraphParentId(node, simNodeById);
        if (!parentId) {
          return;
        }
        const edgeKey = buildEdgeKey(parentId, node.id);
        if (structuralEdgeKeys.has(edgeKey)) {
          return;
        }
        sl.unshift({
          source: parentId,
          target: node.id,
          id: `parent:${parentId}:${node.id}`,
          edge_type: "parent",
          strength: 0.46,
        });
        structuralEdgeKeys.add(edgeKey);
      });

    nodes
      .filter(
        (node) =>
          !isFileMemoryNode(node) &&
          !isAssistantRootMemoryNode(node) &&
          (getGraphParentId(node, simNodeById) === cId ||
            (rootNode === null && !getGraphParentId(node, simNodeById))),
      )
      .forEach((node) => {
        const edgeKey = buildEdgeKey(cId, node.id);
        if (structuralEdgeKeys.has(edgeKey)) {
          return;
        }
        sl.unshift({
          source: cId,
          target: node.id,
          id: `center:${node.id}`,
          edge_type: "center",
          strength: 0.35,
        });
      });

    return { simNodes: sn, simLinks: sl, centerNodeId: cId };
  }, [centerNodeLabel, nodes, edges]);

  const currentChildIds = useMemo(() => {
    if (!selectedNode) {
      return [];
    }
    return nodes
      .filter(
        (candidate) =>
          !isFileMemoryNode(candidate) &&
          !isAssistantRootMemoryNode(candidate) &&
          candidate.parent_memory_id === selectedNode.id,
      )
      .map((candidate) => candidate.id);
  }, [nodes, selectedNode]);

  const currentManualEdges = useMemo(() => {
    if (!selectedNode) {
      return [];
    }
    return edges.filter(
      (edge) =>
        edge.edge_type === "manual" &&
        (edge.source_memory_id === selectedNode.id || edge.target_memory_id === selectedNode.id),
    );
  }, [edges, selectedNode]);

  const currentManualRelatedIds = useMemo(
    () =>
      currentManualEdges.map((edge) =>
        edge.source_memory_id === selectedNode?.id ? edge.target_memory_id : edge.source_memory_id,
      ),
    [currentManualEdges, selectedNode?.id],
  );

  const currentAncestorIds = useMemo(() => {
    if (!selectedNode) {
      return new Set<string>();
    }
    const ids = new Set<string>();
    const nodeById = new Map(nodes.map((candidate) => [candidate.id, candidate]));
    let current = selectedNode;
    while (current.parent_memory_id && nodeById.has(current.parent_memory_id)) {
      ids.add(current.parent_memory_id);
      current = nodeById.get(current.parent_memory_id)!;
    }
    return ids;
  }, [nodes, selectedNode]);

  const selectableNodeIds = useMemo(() => {
    const ids = new Set<string>();
    if (!selectedNode || !editMode) {
      return ids;
    }
    if (editMode === "parent") {
      ids.add(centerNodeId);
      const blockedIds = new Set<string>([selectedNode.id]);
      const queue = [selectedNode.id];
      while (queue.length > 0) {
        const currentId = queue.shift();
        if (!currentId) {
          continue;
        }
        nodes.forEach((candidate) => {
          if (candidate.parent_memory_id !== currentId || blockedIds.has(candidate.id)) {
            return;
          }
          blockedIds.add(candidate.id);
          queue.push(candidate.id);
        });
      }
      nodes.forEach((candidate) => {
        if (
          isFileMemoryNode(candidate) ||
          isAssistantRootMemoryNode(candidate) ||
          candidate.id === selectedNode.id ||
          blockedIds.has(candidate.id) ||
          !canPrimaryParentChildren(candidate)
        ) {
          return;
        }
        ids.add(candidate.id);
      });
      return ids;
    }

    nodes.forEach((candidate) => {
      if (isFileMemoryNode(candidate) || isAssistantRootMemoryNode(candidate) || candidate.id === selectedNode.id) {
        return;
      }
      if (editMode === "children" && currentAncestorIds.has(candidate.id)) {
        return;
      }
      ids.add(candidate.id);
    });
    return ids;
  }, [centerNodeId, currentAncestorIds, editMode, nodes, selectedNode]);

  const editSelectionSet = useMemo(() => new Set(editSelectionIds), [editSelectionIds]);

  useEffect(() => {
    selectableNodeIdsRef.current = selectableNodeIds;
  }, [selectableNodeIds]);

  const expandStructuralSelectionIds = useCallback(
    (selectionIds: string[], mode: Extract<GraphSelectionMode, "children" | "related">) => {
      const expandedIds = new Set<string>();
      const nodeById = new Map(nodes.map((candidate) => [candidate.id, candidate] as const));

      selectionIds.forEach((selectionId) => {
        const targetNode = nodeById.get(selectionId);
        if (!targetNode) {
          return;
        }
        if (!isStructureMemoryNode(targetNode)) {
          expandedIds.add(selectionId);
          return;
        }
        const categoryPath = getMemoryCategoryPath(targetNode);
        if (!categoryPath) {
          return;
        }
        nodes.forEach((candidate) => {
          if (
            candidate.id === selectedNode?.id ||
            isFileMemoryNode(candidate) ||
            isAssistantRootMemoryNode(candidate) ||
            isStructureMemoryNode(candidate)
          ) {
            return;
          }
          if (!getMemoryCategoryPrefixes(candidate).includes(categoryPath)) {
            return;
          }
          if (mode === "children" && currentAncestorIds.has(candidate.id)) {
            return;
          }
          expandedIds.add(candidate.id);
        });
      });

      return [...expandedIds];
    },
    [currentAncestorIds, nodes, selectedNode?.id],
  );

  const beginEditMode = useCallback(
    (mode: Exclude<GraphSelectionMode, null>) => {
      if (!selectedNode) {
        return;
      }
      setEditMode(mode);
      if (mode === "parent") {
        const currentGraphParentId = getGraphParentId(
          selectedNode,
          new Map(nodes.map((node) => [node.id, node] as const)),
        );
        setEditSelectionIds([
          currentGraphParentId && currentGraphParentId !== centerNodeId
            ? currentGraphParentId
            : GRAPH_TOP_LEVEL_TARGET_ID,
        ]);
        return;
      }
      if (mode === "children") {
        if (!canPrimaryParentChildren(selectedNode)) {
          return;
        }
        setEditSelectionIds(currentChildIds);
        return;
      }
      setEditSelectionIds(currentManualRelatedIds);
    },
    [centerNodeId, currentChildIds, currentManualRelatedIds, nodes, selectedNode],
  );

  const cancelEditMode = useCallback(() => {
    setEditMode(null);
    setEditSelectionIds([]);
  }, []);

  const clearEditSelection = useCallback(() => {
    if (editMode === "parent") {
      setEditSelectionIds([GRAPH_TOP_LEVEL_TARGET_ID]);
      return;
    }
    setEditSelectionIds([]);
  }, [editMode]);

  const applyEditMode = useCallback(async () => {
    if (!selectedNode || !editMode || editPending) {
      return;
    }
    setEditPending(true);
    try {
      if (editMode === "parent") {
        const nextParentId = editSelectionIds[0];
        if (!nextParentId || nextParentId === GRAPH_TOP_LEVEL_TARGET_ID) {
          await onUpdateMemory(selectedNode.id, { parent_memory_id: null });
        } else {
          const nextParentNode = nodes.find((candidate) => candidate.id === nextParentId) ?? null;
          if (nextParentNode && isStructureMemoryNode(nextParentNode)) {
            await onUpdateMemory(selectedNode.id, {
              category: getMemoryCategoryPath(nextParentNode),
              parent_memory_id: null,
            });
          } else {
            await onUpdateMemory(selectedNode.id, { parent_memory_id: nextParentId });
          }
        }
      } else if (editMode === "children") {
        if (!canPrimaryParentChildren(selectedNode)) {
          await modal.alert(t("graph.leafNodeChildrenUnsupported"));
          return;
        }
        const nextChildIds = new Set(expandStructuralSelectionIds(editSelectionIds, "children"));
        const currentChildIdSet = new Set(currentChildIds);
        for (const currentChildId of currentChildIds) {
          if (nextChildIds.has(currentChildId)) {
            continue;
          }
          await onUpdateMemory(currentChildId, { parent_memory_id: null });
        }
        for (const childId of nextChildIds) {
          if (currentChildIdSet.has(childId)) {
            continue;
          }
          await onUpdateMemory(childId, { parent_memory_id: selectedNode.id });
        }
      } else if (editMode === "related") {
        const nextRelatedIds = new Set(expandStructuralSelectionIds(editSelectionIds, "related"));
        const currentEdgeByRelatedId = new Map(
          currentManualEdges.map((edge) => [
            edge.source_memory_id === selectedNode.id ? edge.target_memory_id : edge.source_memory_id,
            edge.id,
          ]),
        );
        for (const edge of currentManualEdges) {
          const otherId =
            edge.source_memory_id === selectedNode.id ? edge.target_memory_id : edge.source_memory_id;
          if (nextRelatedIds.has(otherId)) {
            continue;
          }
          await onDeleteEdge(edge.id);
        }
        for (const relatedId of nextRelatedIds) {
          if (currentEdgeByRelatedId.has(relatedId)) {
            continue;
          }
          await onCreateEdge(selectedNode.id, relatedId);
        }
      }
      setEditMode(null);
      setEditSelectionIds([]);
    } catch (error) {
      const message =
        error instanceof Error && error.message ? error.message : t("graph.applySelectionFailed");
      await modal.alert(message);
    } finally {
      setEditPending(false);
    }
  }, [
    currentChildIds,
    currentManualEdges,
    editMode,
    editPending,
    editSelectionIds,
    expandStructuralSelectionIds,
    modal,
    onCreateEdge,
    onDeleteEdge,
    onUpdateMemory,
    nodes,
    selectedNode,
    t,
  ]);

  /* ── Filtering ──────────────────────────────── */

  const activeTypes = externalFilters?.types ?? filterState.types;
  const activeCategories = externalFilters?.categories ?? filterState.categories;
  const activeSources = externalFilters?.sources ?? filterState.sources;
  const activeTimeRange = externalFilters?.timeRange ?? filterState.timeRange;

  const visibleNodeIds = useMemo(() => {
    const ids = new Set<string>();
    const nodeById = new Map(simNodes.map((node) => [node.id, node]));
    const categoryNodeIdByPath = new Map<string, string>();
    simNodes.forEach((node) => {
      if (!isStructureMemoryNode(node)) {
        return;
      }
      const prefixes = getMemoryCategoryPrefixes(node);
      const categoryPath = prefixes[prefixes.length - 1];
      if (categoryPath) {
        categoryNodeIdByPath.set(categoryPath, node.id);
      }
    });
    simNodes.forEach((n) => {
      if (n.id === centerNodeId) {
        ids.add(n.id);
        return;
      }
      // Type filter
      if (activeTypes.length > 0) {
        const nodeType = isFileMemoryNode(n) ? "file" : n.type;
        if (!activeTypes.includes(nodeType)) return;
      }
      // Category filter
      if (
        activeCategories.length > 0 &&
        !activeCategories.some((categoryPath) => getMemoryCategoryPrefixes(n).includes(categoryPath))
      ) {
        return;
      }
      // Source filter
      if (activeSources.length > 0) {
        const nodeSources = getNodeSourceKinds(n);
        if (!nodeSources.some((source) => activeSources.includes(source))) {
          return;
        }
      }
      // Time range filter
      if (activeTimeRange !== "all") {
        const created = new Date(n.created_at).getTime();
        const now = Date.now();
        const msMap = { "24h": 86400000, "7d": 604800000, "30d": 2592000000 };
        if (now - created > msMap[activeTimeRange]) return;
      }
      ids.add(n.id);
    });
    const matchedIds = Array.from(ids);
    matchedIds.forEach((nodeId) => {
      let current = nodeById.get(nodeId);
      while (current) {
        const graphParentId = getGraphParentId(current, nodeById);
        if (!graphParentId || !nodeById.has(graphParentId)) {
          break;
        }
        ids.add(graphParentId);
        current = nodeById.get(graphParentId);
      }
      const node = nodeById.get(nodeId);
      if (!node || isStructureMemoryNode(node)) {
        return;
      }
      getMemoryCategoryPrefixes(node).forEach((prefix) => {
        const categoryNodeId = categoryNodeIdByPath.get(prefix);
        if (categoryNodeId) {
          ids.add(categoryNodeId);
        }
      });
    });
    return ids;
  }, [activeCategories, activeSources, activeTimeRange, activeTypes, centerNodeId, simNodes]);

  useEffect(() => {
    visibleNodeIdsRef.current = visibleNodeIds;
  }, [visibleNodeIds]);

  const localSearchMatchIds = useMemo(() => {
    if (!searchQuery) return null;
    const q = searchQuery.toLowerCase();
    const ids = new Set<string>();
    simNodes.forEach((n) => {
      if (n.id === centerNodeId) return;
      if (
        n.content.toLowerCase().includes(q) ||
        n.category.toLowerCase().includes(q) ||
        getMemoryCategoryPrefixes(n).some((value) => value.toLowerCase().includes(q))
      ) {
        ids.add(n.id);
      }
    });
    return ids;
  }, [centerNodeId, searchQuery, simNodes]);

  const searchMatchIds = semanticMatchIds ?? localSearchMatchIds;
  const simNodeById = useMemo(
    () => new Map(simNodes.map((node) => [node.id, node] as const)),
    [simNodes],
  );
  const maxRetrievalCount = useMemo(
    () =>
      Math.max(
        0,
        ...simNodes
          .filter((node) => isFactMemoryNode(node))
          .map((node) => getMemoryRetrievalCount(node)),
        ),
    [simNodes],
  );
  const orbitSceneLinks = useMemo<OrbitSceneLink[]>(
    () =>
      simLinks.map((link) => ({
        id: link.id,
        sourceId: getSimLinkEndpointId(link.source),
        targetId: getSimLinkEndpointId(link.target),
        edgeType: link.edge_type,
        strength: link.strength,
      })),
    [simLinks],
  );
  const orbitWorldById = useMemo(
    () => buildOrbitWorldMap(simNodes, centerNodeId, simNodeById, maxRetrievalCount),
    [centerNodeId, maxRetrievalCount, simNodeById, simNodes],
  );
  const getOrbitProjectedNodes = useCallback(() => {
    const projections = buildOrbitProjectionMap(
      simNodes,
      centerNodeId,
      orbitWorldById,
      orbitRotationRef.current,
    );
    projectedNodeCacheRef.current = projections;
    return projections;
  }, [centerNodeId, orbitWorldById, simNodes]);

  /* ── Canvas draw ────────────────────────────── */

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;

    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr;
      canvas.height = h * dpr;
    }

    ctx.save();
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.scale(dpr, dpr);

    const transform = transformRef.current;
    ctx.translate(transform.x, transform.y);
    ctx.scale(transform.k, transform.k);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    const hasSearch = searchMatchIds !== null;
    const isEditActive = Boolean(editMode && selectedNode);
    const activeNodeId = selectedNode?.id || null;
    const centerNode = simNodeById.get(centerNodeId) ?? null;
    const orbitProjectedNodes = isOrbitMode ? getOrbitProjectedNodes() : null;
    const getProjectedNode = (nodeId: string) =>
      orbitProjectedNodes?.get(nodeId) ?? null;
    const getRenderedX = (node: SimNode) => getProjectedNode(node.id)?.x ?? node.x;
    const getRenderedY = (node: SimNode) => getProjectedNode(node.id)?.y ?? node.y;
    const getRenderedScale = (node: SimNode) => getProjectedNode(node.id)?.scale ?? 1;
    const getRenderedOpacity = (node: SimNode) => getProjectedNode(node.id)?.opacity ?? 1;
    const getRenderedLabelOpacity = (node: SimNode) =>
      getProjectedNode(node.id)?.labelOpacity ?? 1;
    const getRenderedRadius = (node: SimNode) =>
      getProjectedNode(node.id)?.radius ?? nodeRadius(node, node.id === centerNodeId);
    const visibleSimNodes = simNodes.filter((node) => visibleNodeIds.has(node.id));
    const orderedNodes = isOrbitMode
      ? [...visibleSimNodes].sort(
          (left, right) =>
            (getProjectedNode(left.id)?.z ?? 0) - (getProjectedNode(right.id)?.z ?? 0),
        )
      : visibleSimNodes;
    const orderedLinks = isOrbitMode
      ? [...simLinks].sort((left, right) => {
          const leftSource = getProjectedNode(
            typeof left.source === "object" ? left.source.id : String(left.source),
          );
          const leftTarget = getProjectedNode(
            typeof left.target === "object" ? left.target.id : String(left.target),
          );
          const rightSource = getProjectedNode(
            typeof right.source === "object" ? right.source.id : String(right.source),
          );
          const rightTarget = getProjectedNode(
            typeof right.target === "object" ? right.target.id : String(right.target),
          );
          return (
            ((leftSource?.z ?? 0) + (leftTarget?.z ?? 0)) / 2 -
            ((rightSource?.z ?? 0) + (rightTarget?.z ?? 0)) / 2
          );
        })
      : simLinks;
    let orbitScene: OrbitSceneRig | null = null;
    const orbitLabelCandidates: Array<{
      text: string;
      x: number;
      y: number;
      fontSize: number;
      opacity: number;
      color: string;
      priority: number;
      z: number;
      backdrop: boolean;
      forceShow: boolean;
    }> = [];

    if (isOrbitMode && centerNode) {
      const projectedCenter = getProjectedNode(centerNode.id);
      const centerX = projectedCenter?.x ?? centerNode.x;
      const centerY = projectedCenter?.y ?? centerNode.y;
      const centerScale = projectedCenter?.scale ?? 1;
      const floorY = centerY + 178 * centerScale;
      const keyLightX = centerX - 392 * centerScale;
      const keyLightY = centerY - 338 * centerScale;
      const fillLightX = centerX + 486 * centerScale;
      const fillLightY = centerY - 58 * centerScale;
      const rimLightX = centerX + 214 * centerScale;
      const rimLightY = centerY - 382 * centerScale;
      orbitScene = {
        centerX,
        centerY,
        centerScale,
        floorY,
        keyLightX,
        keyLightY,
        fillLightX,
        fillLightY,
        rimLightX,
        rimLightY,
      };

      const keySpotlight = ctx.createRadialGradient(
        keyLightX,
        keyLightY,
        0,
        keyLightX,
        keyLightY,
        720 * centerScale,
      );
      keySpotlight.addColorStop(0, "rgba(255, 236, 214, 0.32)");
      keySpotlight.addColorStop(0.32, "rgba(255, 226, 196, 0.14)");
      keySpotlight.addColorStop(1, "rgba(255, 226, 196, 0)");
      ctx.beginPath();
      ctx.arc(keyLightX, keyLightY, 720 * centerScale, 0, Math.PI * 2);
      ctx.fillStyle = keySpotlight;
      ctx.fill();

      const fillSpotlight = ctx.createRadialGradient(
        fillLightX,
        fillLightY,
        0,
        fillLightX,
        fillLightY,
        660 * centerScale,
      );
      fillSpotlight.addColorStop(0, "rgba(188, 206, 255, 0.18)");
      fillSpotlight.addColorStop(0.34, "rgba(188, 206, 255, 0.08)");
      fillSpotlight.addColorStop(1, "rgba(188, 206, 255, 0)");
      ctx.beginPath();
      ctx.arc(fillLightX, fillLightY, 660 * centerScale, 0, Math.PI * 2);
      ctx.fillStyle = fillSpotlight;
      ctx.fill();

      const stageGlow = ctx.createRadialGradient(
        centerX,
        floorY - 34 * centerScale,
        0,
        centerX,
        floorY - 34 * centerScale,
        486 * centerScale,
      );
      stageGlow.addColorStop(0, "rgba(255, 255, 255, 0.28)");
      stageGlow.addColorStop(0.24, "rgba(252, 244, 236, 0.18)");
      stageGlow.addColorStop(0.68, "rgba(228, 219, 236, 0.05)");
      stageGlow.addColorStop(1, "rgba(228, 219, 236, 0)");
      ctx.beginPath();
      ctx.ellipse(
        centerX,
        floorY,
        468 * centerScale,
        124 * centerScale,
        0,
        0,
        Math.PI * 2,
      );
      ctx.fillStyle = stageGlow;
      ctx.fill();

      const stageEdge = ctx.createLinearGradient(
        centerX,
        floorY - 84 * centerScale,
        centerX,
        floorY + 90 * centerScale,
      );
      stageEdge.addColorStop(0, "rgba(255, 255, 255, 0.18)");
      stageEdge.addColorStop(0.48, "rgba(227, 210, 194, 0.12)");
      stageEdge.addColorStop(1, "rgba(142, 110, 84, 0.08)");
      ctx.beginPath();
      ctx.ellipse(
        centerX,
        floorY,
        452 * centerScale,
        108 * centerScale,
        0,
        0,
        Math.PI * 2,
      );
      ctx.strokeStyle = stageEdge;
      ctx.lineWidth = 1.2 * centerScale;
      ctx.stroke();

      const orbitBands = [210, 318];
      orbitBands.forEach((band, index) => {
        ctx.beginPath();
        ctx.ellipse(
          centerX,
          centerY,
          band * centerScale,
          band * (0.14 + index * 0.04) * centerScale,
          0,
          0,
          Math.PI * 2,
        );
        ctx.strokeStyle =
          index === 0
            ? "rgba(219, 168, 127, 0.18)"
            : "rgba(144, 139, 255, 0.12)";
        ctx.lineWidth = 0.9;
        ctx.stroke();
      });

      const groundShadow = ctx.createRadialGradient(
        centerX,
        floorY - 12 * centerScale,
        0,
        centerX,
        floorY - 12 * centerScale,
        426 * centerScale,
      );
      groundShadow.addColorStop(0, "rgba(118, 88, 64, 0.16)");
      groundShadow.addColorStop(0.28, "rgba(118, 88, 64, 0.07)");
      groundShadow.addColorStop(1, "rgba(118, 88, 64, 0)");
      ctx.beginPath();
      ctx.ellipse(
        centerX,
        floorY - 8 * centerScale,
        426 * centerScale,
        96 * centerScale,
        0,
        0,
        Math.PI * 2,
      );
      ctx.fillStyle = groundShadow;
      ctx.fill();

      const centerHalo = ctx.createRadialGradient(
        centerX,
        centerY,
        0,
        centerX,
        centerY,
        260 * centerScale,
      );
      centerHalo.addColorStop(0, "rgba(255, 220, 190, 0.1)");
      centerHalo.addColorStop(0.35, "rgba(255, 220, 190, 0.03)");
      centerHalo.addColorStop(1, "rgba(255, 220, 190, 0)");
      ctx.beginPath();
      ctx.arc(centerX, centerY, 260 * centerScale, 0, Math.PI * 2);
      ctx.fillStyle = centerHalo;
      ctx.fill();

      orderedNodes.forEach((node) => {
        if (
          node.id === centerNodeId ||
          isFileMemoryNode(node)
        ) {
          return;
        }
        const isRootBranch =
          !getGraphParentId(node, simNodeById) || getGraphParentId(node, simNodeById) === centerNodeId;
        if (!isRootBranch) {
          return;
        }
        const projectedNode = getProjectedNode(node.id);
        if (!projectedNode) {
          return;
        }
        const haloRadius = 52 * projectedNode.scale;
        const halo = ctx.createRadialGradient(
          projectedNode.x,
          projectedNode.y,
          0,
          projectedNode.x,
          projectedNode.y,
          haloRadius,
        );
        halo.addColorStop(0, "rgba(235, 173, 132, 0.05)");
        halo.addColorStop(0.45, "rgba(235, 173, 132, 0.015)");
        halo.addColorStop(1, "rgba(235, 173, 132, 0)");
        ctx.beginPath();
        ctx.arc(projectedNode.x, projectedNode.y, haloRadius, 0, Math.PI * 2);
        ctx.fillStyle = halo;
        ctx.fill();
      });
    }

    if (isOrbitMode && orbitScene) {
      orderedNodes.forEach((node) => {
        if (!visibleNodeIds.has(node.id)) {
          return;
        }

        const projectedNode = getProjectedNode(node.id);
        if (!projectedNode) {
          return;
        }

        const nodeX = projectedNode.x;
        const nodeY = projectedNode.y;
        const radius = projectedNode.radius;
        const lightVectorX = nodeX - orbitScene.keyLightX;
        const lightVectorY = nodeY - orbitScene.keyLightY;
        const lightLength = Math.hypot(lightVectorX, lightVectorY) || 1;
        const shadowDirX = lightVectorX / lightLength;
        const shadowDirY = lightVectorY / lightLength;
        const depthLift = clampNumber((projectedNode.z + 360) / 1080, 0.24, 1.12);
        const planeY =
          orbitScene.floorY + (nodeY - orbitScene.centerY) * 0.14 + depthLift * 4;
        const shadowCenterX =
          nodeX + shadowDirX * radius * (1.35 + depthLift * 0.42);
        const shadowCenterY =
          planeY + shadowDirY * radius * (0.42 + depthLift * 0.12);
        const shadowRotation = Math.atan2(shadowDirY, shadowDirX);
        const shadowRadiusX = radius * (1.5 + depthLift * 1.1);
        const shadowRadiusY = Math.max(6, radius * (0.24 + depthLift * 0.08));
        const shadowOpacity =
          isFileMemoryNode(node)
            ? 0.1 * projectedNode.opacity
            : clampNumber(0.1 + depthLift * 0.08, 0.12, 0.22) * projectedNode.opacity;
        const castShadow = ctx.createRadialGradient(
          shadowCenterX,
          shadowCenterY,
          0,
          shadowCenterX,
          shadowCenterY,
          shadowRadiusX,
        );
        castShadow.addColorStop(0, `rgba(71, 46, 31, ${shadowOpacity})`);
        castShadow.addColorStop(0.44, `rgba(71, 46, 31, ${shadowOpacity * 0.44})`);
        castShadow.addColorStop(1, "rgba(71, 46, 31, 0)");

        ctx.save();
        ctx.beginPath();
        ctx.ellipse(
          shadowCenterX,
          shadowCenterY,
          shadowRadiusX,
          shadowRadiusY,
          shadowRotation,
          0,
          Math.PI * 2,
        );
        ctx.fillStyle = castShadow;
        ctx.fill();

        const contactShadow = ctx.createRadialGradient(
          nodeX + shadowDirX * radius * 0.2,
          planeY,
          0,
          nodeX + shadowDirX * radius * 0.2,
          planeY,
          radius * 1.1,
        );
        contactShadow.addColorStop(0, `rgba(56, 36, 24, ${shadowOpacity * 0.9})`);
        contactShadow.addColorStop(0.58, `rgba(56, 36, 24, ${shadowOpacity * 0.36})`);
        contactShadow.addColorStop(1, "rgba(56, 36, 24, 0)");
        ctx.beginPath();
        ctx.ellipse(
          nodeX + shadowDirX * radius * 0.18,
          planeY,
          radius * 1.08,
          Math.max(4, radius * 0.28),
          0,
          0,
          Math.PI * 2,
        );
        ctx.fillStyle = contactShadow;
        ctx.fill();
        ctx.restore();
      });
    }

    /* ── Draw edges ── */
    orderedLinks.forEach((link) => {
      const src = link.source as SimNode;
      const tgt = link.target as SimNode;
      if (!visibleNodeIds.has(src.id) || !visibleNodeIds.has(tgt.id)) return;
      const srcProjection = getProjectedNode(src.id);
      const tgtProjection = getProjectedNode(tgt.id);
      const srcX = srcProjection?.x ?? src.x;
      const srcY = srcProjection?.y ?? src.y;
      const tgtX = tgtProjection?.x ?? tgt.x;
      const tgtY = tgtProjection?.y ?? tgt.y;

      const isFileEdge = link.edge_type === "file";
      const isSummaryEdge = link.edge_type === "summary";
      const isManualRelatedEdge = link.edge_type === "manual";
      const isSystemRelatedEdge = link.edge_type === "related";
      const isPrerequisiteEdge = link.edge_type === "prerequisite";
      const isEvidenceEdge = link.edge_type === "evidence";
      const isVersionEdge = link.edge_type === "supersedes";
      const isConflictEdge = link.edge_type === "conflict";
      const isLateralEdge = isManualRelatedEdge || isSystemRelatedEdge;
      const isStructuralEdge = isStructuralTreeEdgePair(
        simNodeById,
        src.id,
        tgt.id,
        centerNodeId,
      );
      const isCenterEdge =
        link.edge_type === "center" ||
        isCenterStructuralTreeEdgePair(simNodeById, src.id, tgt.id, centerNodeId);
      const isParentEdge =
        link.edge_type === "parent" || (isStructuralEdge && !isCenterEdge);
      const baseLineWidth = isFileEdge
        ? 1
        : isEvidenceEdge
          ? isOrbitMode ? 1.35 : 1.15
        : isCenterEdge
          ? isOrbitMode ? 2.1 : 1.75
          : isParentEdge
            ? isOrbitMode ? 1.55 : 1.3
            : isManualRelatedEdge
              ? isOrbitMode ? 1.95 : 1.7
              : isPrerequisiteEdge
                ? isOrbitMode ? 1.7 : 1.45
              : isConflictEdge
                ? isOrbitMode ? 1.55 : 1.35
              : isVersionEdge
                ? isOrbitMode ? 1.4 : 1.2
              : isSystemRelatedEdge
                ? isOrbitMode ? 1.65 : 1.4
              : isSummaryEdge
                ? isOrbitMode ? 1.45 : 1.2
                : 0.85 + link.strength * 1.2;
      const lineWidth =
        isOrbitMode && srcProjection && tgtProjection
          ? baseLineWidth *
            clampNumber((srcProjection.scale + tgtProjection.scale) / 2, 0.78, 1.52)
          : baseLineWidth;
      const edgeTouchesActiveNode = Boolean(activeNodeId && (src.id === activeNodeId || tgt.id === activeNodeId));
      const edgeTouchesSelection =
        edgeTouchesActiveNode ||
        editSelectionSet.has(src.id) ||
        editSelectionSet.has(tgt.id) ||
        (editSelectionSet.has(GRAPH_TOP_LEVEL_TARGET_ID) &&
          (src.id === centerNodeId || tgt.id === centerNodeId));

      ctx.save();
      if (isOrbitMode) {
        ctx.globalAlpha = clampNumber(
          ((srcProjection?.opacity ?? 1) + (tgtProjection?.opacity ?? 1)) / 2,
          0.44,
          0.92,
        );
      }

      if (isFileEdge) {
        ctx.beginPath();
        ctx.moveTo(srcX, srcY);
        ctx.lineTo(tgtX, tgtY);
        ctx.setLineDash([]);
        ctx.strokeStyle = "rgba(138, 122, 106, 0.45)";
      } else if (isEvidenceEdge) {
        ctx.beginPath();
        ctx.moveTo(srcX, srcY);
        ctx.lineTo(tgtX, tgtY);
        ctx.setLineDash([3, 5]);
        ctx.strokeStyle = isOrbitMode ? "rgba(123, 104, 238, 0.62)" : "rgba(111, 92, 214, 0.46)";
      } else if (isParentEdge) {
        ctx.beginPath();
        ctx.moveTo(srcX, srcY);
        ctx.lineTo(tgtX, tgtY);
        ctx.setLineDash([]);
        ctx.strokeStyle = isOrbitMode ? "rgba(209, 132, 91, 0.5)" : "rgba(200, 115, 74, 0.34)";
      } else if (isSummaryEdge) {
        ctx.beginPath();
        ctx.moveTo(srcX, srcY);
        ctx.lineTo(tgtX, tgtY);
        ctx.setLineDash([]);
        ctx.strokeStyle = isOrbitMode ? "rgba(191, 155, 63, 0.58)" : "rgba(182, 138, 47, 0.45)";
      } else if (isSystemRelatedEdge) {
        ctx.beginPath();
        ctx.moveTo(srcX, srcY);
        ctx.lineTo(tgtX, tgtY);
        ctx.setLineDash([6, 6]);
        ctx.strokeStyle = isOrbitMode ? "rgba(91, 118, 255, 0.66)" : "rgba(89, 102, 241, 0.52)";
      } else if (isPrerequisiteEdge) {
        ctx.beginPath();
        ctx.moveTo(srcX, srcY);
        ctx.lineTo(tgtX, tgtY);
        ctx.setLineDash([8, 5]);
        ctx.strokeStyle = isOrbitMode ? "rgba(37, 99, 235, 0.72)" : "rgba(37, 99, 235, 0.58)";
      } else if (isConflictEdge) {
        ctx.beginPath();
        ctx.moveTo(srcX, srcY);
        ctx.lineTo(tgtX, tgtY);
        ctx.setLineDash([4, 6]);
        ctx.strokeStyle = isOrbitMode ? "rgba(196, 78, 54, 0.82)" : "rgba(184, 65, 41, 0.66)";
      } else if (isVersionEdge) {
        ctx.beginPath();
        ctx.moveTo(srcX, srcY);
        ctx.lineTo(tgtX, tgtY);
        ctx.setLineDash([2, 8]);
        ctx.strokeStyle = isOrbitMode ? "rgba(130, 120, 108, 0.72)" : "rgba(120, 109, 97, 0.56)";
      } else if (isManualRelatedEdge) {
        ctx.beginPath();
        ctx.moveTo(srcX, srcY);
        ctx.lineTo(tgtX, tgtY);
        ctx.setLineDash([10, 6]);
        ctx.strokeStyle = isOrbitMode ? "rgba(89, 111, 255, 0.9)" : "rgba(79, 93, 232, 0.82)";
      } else if (isCenterEdge) {
        const glowGradient = ctx.createLinearGradient(srcX, srcY, tgtX, tgtY);
        glowGradient.addColorStop(0, "rgba(255, 236, 221, 0.4)");
        glowGradient.addColorStop(1, "rgba(200, 115, 74, 0.16)");
        ctx.beginPath();
        ctx.moveTo(srcX, srcY);
        ctx.lineTo(tgtX, tgtY);
        ctx.setLineDash([]);
        ctx.strokeStyle = glowGradient;
        ctx.lineWidth = lineWidth + 2.6;
        if (hasSearch) {
          const srcMatch = searchMatchIds.has(src.id);
          const tgtMatch = searchMatchIds.has(tgt.id);
          if (!srcMatch && !tgtMatch) {
            ctx.globalAlpha = 0.28;
          }
        }
        ctx.stroke();
        ctx.globalAlpha = 1;

        const centerGradient = ctx.createLinearGradient(srcX, srcY, tgtX, tgtY);
        centerGradient.addColorStop(0, "rgba(242, 214, 188, 0.9)");
        centerGradient.addColorStop(0.55, "rgba(210, 142, 95, 0.62)");
        centerGradient.addColorStop(1, "rgba(200, 115, 74, 0.26)");
        ctx.beginPath();
        ctx.moveTo(srcX, srcY);
        ctx.lineTo(tgtX, tgtY);
        ctx.strokeStyle = centerGradient;
      } else {
        ctx.beginPath();
        ctx.moveTo(srcX, srcY);
        ctx.lineTo(tgtX, tgtY);
        ctx.setLineDash([4, 5]);
        ctx.strokeStyle = "rgba(200, 115, 74, 0.22)";
      }
      ctx.lineWidth = lineWidth;

      if (isEditActive) {
        if (!edgeTouchesSelection) {
          ctx.globalAlpha = 0.18;
        } else if (isLateralEdge) {
          ctx.globalAlpha = 0.82;
        } else {
          ctx.globalAlpha = 0.68;
        }
      }

      if (hasSearch) {
        const srcMatch = searchMatchIds.has(src.id);
        const tgtMatch = searchMatchIds.has(tgt.id);
        if (!srcMatch && !tgtMatch) {
          ctx.globalAlpha = 0.32;
        }
      }

      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
    });

    if (!isOrbitMode && connectStartRef.current && connectPointerRef.current) {
      ctx.beginPath();
      ctx.moveTo(connectStartRef.current.x, connectStartRef.current.y);
      ctx.lineTo(connectPointerRef.current.x, connectPointerRef.current.y);
      if (connectModeRef.current === "parent") {
        ctx.setLineDash([]);
        ctx.strokeStyle = "rgba(200, 115, 74, 0.82)";
      } else {
        ctx.setLineDash([6, 4]);
        ctx.strokeStyle = "rgba(74, 138, 200, 0.75)";
      }
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.setLineDash([]);
    }

      /* ── Draw nodes ── */
    orderedNodes.forEach((node) => {
      const nodeX = getRenderedX(node);
      const nodeY = getRenderedY(node);
      const depthScale = getRenderedScale(node);
      const depthOpacity = getRenderedOpacity(node);
      const labelOpacity = getRenderedLabelOpacity(node);

      const isCenter = node.id === centerNodeId;
      const isSearched = hasSearch && searchMatchIds.has(node.id);
      const isEditSelected =
        isEditActive &&
        ((node.id === centerNodeId && editSelectionSet.has(GRAPH_TOP_LEVEL_TARGET_ID)) ||
          editSelectionSet.has(node.id));
      const isEditAnchor = Boolean(isEditActive && activeNodeId === node.id);
      const isEditSelectable = Boolean(isEditActive && selectableNodeIds.has(node.id));
      const isFaded =
        (hasSearch && !isSearched && !isCenter) ||
        (isEditActive && !isEditAnchor && !isEditSelected && !isEditSelectable);
      const renderedRadius = getRenderedRadius(node);
      const keyLightVectorX = orbitScene ? orbitScene.keyLightX - nodeX : -1;
      const keyLightVectorY = orbitScene ? orbitScene.keyLightY - nodeY : -1;
      const keyLightLength =
        orbitScene ? Math.hypot(keyLightVectorX, keyLightVectorY) || 1 : 1;
      const keyLightDirX = keyLightVectorX / keyLightLength;
      const keyLightDirY = keyLightVectorY / keyLightLength;
      const fillLightVectorX = orbitScene ? orbitScene.fillLightX - nodeX : 1;
      const fillLightVectorY = orbitScene ? orbitScene.fillLightY - nodeY : -0.2;
      const fillLightLength =
        orbitScene ? Math.hypot(fillLightVectorX, fillLightVectorY) || 1 : 1;
      const fillLightDirX = fillLightVectorX / fillLightLength;
      const fillLightDirY = fillLightVectorY / fillLightLength;
      const rimLightVectorX = orbitScene ? orbitScene.rimLightX - nodeX : 1;
      const rimLightVectorY = orbitScene ? orbitScene.rimLightY - nodeY : -1;
      const rimLightLength =
        orbitScene ? Math.hypot(rimLightVectorX, rimLightVectorY) || 1 : 1;
      const rimLightDirX = rimLightVectorX / rimLightLength;
      const rimLightDirY = rimLightVectorY / rimLightLength;
      const orbitDepthLift = orbitScene
        ? clampNumber(((getProjectedNode(node.id)?.z ?? 0) + 360) / 1080, 0.24, 1.18)
        : 0.6;

      ctx.save();
      ctx.globalAlpha = clampNumber(depthOpacity * (isFaded ? 0.42 : 1), 0.58, 1);

      if (isSearched || isEditSelected || isEditAnchor) {
        ctx.shadowColor = isEditAnchor
          ? "rgba(255, 146, 90, 0.92)"
          : isEditSelected
            ? "rgba(99, 102, 241, 0.9)"
            : isCenter
              ? COLORS.centerGradStart
              : getMemoryNodeColor(node, maxRetrievalCount);
        ctx.shadowBlur = (isEditAnchor ? 24 : 18) * depthScale;
        ctx.shadowOffsetX = 0;
        ctx.shadowOffsetY = 0;
      } else if (isOrbitMode && !isFileMemoryNode(node)) {
        ctx.shadowColor = "rgba(82, 53, 35, 0.22)";
        ctx.shadowBlur = 14 * depthScale;
        ctx.shadowOffsetX = 0;
        ctx.shadowOffsetY = 7 * depthScale;
      }

      if (isCenter) {
        /* center node gradient */
        const grad = ctx.createRadialGradient(
          nodeX + keyLightDirX * renderedRadius * 0.22,
          nodeY + keyLightDirY * renderedRadius * 0.2,
          Math.max(1, renderedRadius * 0.14),
          nodeX,
          nodeY,
          renderedRadius
        );
        grad.addColorStop(0, "#fff8f0");
        grad.addColorStop(0.24, d3.interpolateRgb(COLORS.centerGradEnd, "#fff4e8")(0.42));
        grad.addColorStop(0.68, COLORS.centerGradEnd);
        grad.addColorStop(1, d3.interpolateRgb(COLORS.centerGradStart, "#5d2f19")(0.28));
        ctx.beginPath();
        ctx.arc(nodeX, nodeY, renderedRadius, 0, Math.PI * 2);
        ctx.fillStyle = grad;
        ctx.fill();
        if (isOrbitMode) {
          const centerShade = ctx.createLinearGradient(
            nodeX + keyLightDirX * renderedRadius,
            nodeY + keyLightDirY * renderedRadius,
            nodeX - keyLightDirX * renderedRadius * 1.12,
            nodeY - keyLightDirY * renderedRadius * 1.12,
          );
          centerShade.addColorStop(0, "rgba(255, 255, 255, 0)");
          centerShade.addColorStop(0.54, "rgba(255, 255, 255, 0.04)");
          centerShade.addColorStop(1, "rgba(95, 48, 23, 0.32)");
          ctx.beginPath();
          ctx.arc(nodeX, nodeY, renderedRadius, 0, Math.PI * 2);
          ctx.fillStyle = centerShade;
          ctx.fill();

          ctx.beginPath();
          ctx.arc(nodeX, nodeY, renderedRadius, 0, Math.PI * 2);
          const centerHighlight = ctx.createRadialGradient(
            nodeX + keyLightDirX * renderedRadius * 0.46,
            nodeY + keyLightDirY * renderedRadius * 0.46,
            Math.max(1, renderedRadius * 0.08),
            nodeX + keyLightDirX * renderedRadius * 0.26,
            nodeY + keyLightDirY * renderedRadius * 0.24,
            renderedRadius * 0.92,
          );
          centerHighlight.addColorStop(0, "rgba(255, 255, 255, 0.86)");
          centerHighlight.addColorStop(0.22, "rgba(255, 255, 255, 0.34)");
          centerHighlight.addColorStop(1, "rgba(255, 255, 255, 0)");
          ctx.fillStyle = centerHighlight;
          ctx.fill();

          const centerRim = ctx.createRadialGradient(
            nodeX + rimLightDirX * renderedRadius * 0.82,
            nodeY + rimLightDirY * renderedRadius * 0.82,
            0,
            nodeX + rimLightDirX * renderedRadius * 0.82,
            nodeY + rimLightDirY * renderedRadius * 0.82,
            renderedRadius * 0.96,
          );
          centerRim.addColorStop(0, "rgba(199, 214, 255, 0.22)");
          centerRim.addColorStop(0.34, "rgba(199, 214, 255, 0.08)");
          centerRim.addColorStop(1, "rgba(199, 214, 255, 0)");
          ctx.beginPath();
          ctx.arc(nodeX, nodeY, renderedRadius, 0, Math.PI * 2);
          ctx.fillStyle = centerRim;
          ctx.fill();

          ctx.shadowColor = "transparent";
          ctx.shadowBlur = 0;
          ctx.shadowOffsetY = 0;
          ctx.strokeStyle = "rgba(137, 78, 42, 0.38)";
          ctx.lineWidth = Math.max(2.2, 2.8 * depthScale);
          ctx.stroke();
          ctx.beginPath();
          ctx.arc(nodeX, nodeY, renderedRadius - 1.4 * depthScale, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(255, 250, 245, 0.92)";
          ctx.lineWidth = Math.max(1, 1.15 * depthScale);
          ctx.stroke();
        } else {
          ctx.strokeStyle = "#fff";
          ctx.lineWidth = Math.max(1.5, 2 * depthScale);
          ctx.stroke();
        }

        if (isOrbitMode) {
          ctx.beginPath();
          ctx.arc(nodeX, nodeY, renderedRadius + 14 * depthScale, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(232, 185, 140, 0.2)";
          ctx.lineWidth = Math.max(1, 1.2 * depthScale);
          ctx.stroke();
        }

        if (isEditSelectable || isEditSelected || isEditAnchor) {
          ctx.beginPath();
          ctx.arc(nodeX, nodeY, renderedRadius + 9 * depthScale, 0, Math.PI * 2);
          ctx.strokeStyle = isEditAnchor
            ? "rgba(255, 255, 255, 0.96)"
            : isEditSelected
              ? "rgba(99, 102, 241, 0.82)"
              : "rgba(99, 102, 241, 0.34)";
          ctx.lineWidth = (isEditAnchor ? 2.4 : 1.8) * depthScale;
          ctx.stroke();
        }

        /* center label (inside) */
        ctx.fillStyle = "#ffffff";
        ctx.font = `bold ${Math.max(11, 13 * depthScale)}px sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(centerNodeShortLabel, nodeX, nodeY);
      } else if (isFileMemoryNode(node)) {
        /* file node: rounded rect */
        const fileWidth = FILE_NODE_W * depthScale;
        const fileHeight = FILE_NODE_H * depthScale;
        const rx = nodeX - fileWidth / 2;
        const ry = nodeY - fileHeight / 2;
        const cornerR = Math.max(2, 3 * depthScale);
        ctx.beginPath();
        ctx.moveTo(rx + cornerR, ry);
        ctx.lineTo(rx + fileWidth - cornerR, ry);
        ctx.quadraticCurveTo(rx + fileWidth, ry, rx + fileWidth, ry + cornerR);
        ctx.lineTo(rx + fileWidth, ry + fileHeight - cornerR);
        ctx.quadraticCurveTo(
          rx + fileWidth,
          ry + fileHeight,
          rx + fileWidth - cornerR,
          ry + fileHeight
        );
        ctx.lineTo(rx + cornerR, ry + fileHeight);
        ctx.quadraticCurveTo(rx, ry + fileHeight, rx, ry + fileHeight - cornerR);
        ctx.lineTo(rx, ry + cornerR);
        ctx.quadraticCurveTo(rx, ry, rx + cornerR, ry);
        ctx.closePath();
        ctx.fillStyle = COLORS.file;
        ctx.fill();
        ctx.strokeStyle = "#b0a090";
        ctx.lineWidth = Math.max(0.9, depthScale);
        ctx.stroke();
      } else {
        /* memory node circle */
        const radius = renderedRadius;
        const color = getMemoryNodeColor(node, maxRetrievalCount);
        if (isOrbitMode) {
          ctx.beginPath();
          ctx.ellipse(
            nodeX,
            nodeY + radius * 0.98,
            Math.max(4, radius * 0.68),
            Math.max(2.5, radius * 0.18),
            0,
            0,
            Math.PI * 2,
          );
          ctx.fillStyle = "rgba(73, 48, 30, 0.14)";
          ctx.fill();
        }
        ctx.beginPath();
        ctx.arc(nodeX, nodeY, radius, 0, Math.PI * 2);
        if (isOrbitMode) {
          const litBase = ctx.createRadialGradient(
            nodeX + keyLightDirX * radius * 0.18,
            nodeY + keyLightDirY * radius * 0.18,
            Math.max(1, radius * 0.1),
            nodeX,
            nodeY,
            radius,
          );
          litBase.addColorStop(0, d3.interpolateRgb(color, "#fff4ec")(0.54));
          litBase.addColorStop(0.3, d3.interpolateRgb(color, "#f8ebe2")(0.2));
          litBase.addColorStop(0.76, color);
          litBase.addColorStop(1, d3.interpolateRgb(color, "#5a3120")(0.26));
          ctx.fillStyle = litBase;
        } else {
          ctx.fillStyle = color;
        }
        ctx.fill();

        if (isOrbitMode) {
          ctx.beginPath();
          ctx.arc(nodeX, nodeY, radius, 0, Math.PI * 2);
          const bodyShade = ctx.createLinearGradient(
            nodeX + keyLightDirX * radius,
            nodeY + keyLightDirY * radius,
            nodeX - keyLightDirX * radius * 1.08,
            nodeY - keyLightDirY * radius * 1.08,
          );
          bodyShade.addColorStop(0, "rgba(255, 255, 255, 0)");
          bodyShade.addColorStop(0.52, "rgba(255, 255, 255, 0.04)");
          bodyShade.addColorStop(1, `rgba(64, 33, 19, ${0.26 + orbitDepthLift * 0.04})`);
          ctx.fillStyle = bodyShade;
          ctx.fill();

          ctx.beginPath();
          ctx.arc(nodeX, nodeY, radius, 0, Math.PI * 2);
          const highlight = ctx.createRadialGradient(
            nodeX + keyLightDirX * radius * 0.48,
            nodeY + keyLightDirY * radius * 0.48,
            Math.max(1, radius * 0.08),
            nodeX + keyLightDirX * radius * 0.26,
            nodeY + keyLightDirY * radius * 0.28,
            radius * 0.78,
          );
          highlight.addColorStop(0, `rgba(255, 255, 255, ${0.72 + orbitDepthLift * 0.08})`);
          highlight.addColorStop(0.22, "rgba(255, 255, 255, 0.28)");
          highlight.addColorStop(1, "rgba(255, 255, 255, 0)");
          ctx.fillStyle = highlight;
          ctx.fill();

          const fillBloom = ctx.createRadialGradient(
            nodeX + fillLightDirX * radius * 0.44,
            nodeY + fillLightDirY * radius * 0.28,
            0,
            nodeX + fillLightDirX * radius * 0.44,
            nodeY + fillLightDirY * radius * 0.28,
            radius * 0.92,
          );
          fillBloom.addColorStop(0, "rgba(210, 223, 255, 0.16)");
          fillBloom.addColorStop(0.34, "rgba(210, 223, 255, 0.06)");
          fillBloom.addColorStop(1, "rgba(210, 223, 255, 0)");
          ctx.beginPath();
          ctx.arc(nodeX, nodeY, radius, 0, Math.PI * 2);
          ctx.fillStyle = fillBloom;
          ctx.fill();

          const rimLight = ctx.createRadialGradient(
            nodeX + rimLightDirX * radius * 0.8,
            nodeY + rimLightDirY * radius * 0.8,
            0,
            nodeX + rimLightDirX * radius * 0.8,
            nodeY + rimLightDirY * radius * 0.8,
            radius * 0.94,
          );
          rimLight.addColorStop(0, "rgba(198, 214, 255, 0.24)");
          rimLight.addColorStop(0.28, "rgba(198, 214, 255, 0.08)");
          rimLight.addColorStop(1, "rgba(198, 214, 255, 0)");
          ctx.beginPath();
          ctx.arc(nodeX, nodeY, radius, 0, Math.PI * 2);
          ctx.fillStyle = rimLight;
          ctx.fill();

          ctx.shadowColor = "transparent";
          ctx.shadowBlur = 0;
          ctx.shadowOffsetY = 0;
          ctx.beginPath();
          ctx.arc(nodeX, nodeY, radius, 0, Math.PI * 2);
          ctx.strokeStyle = d3.interpolateRgb(color, "#5a3120")(0.34);
          ctx.lineWidth = Math.max(1.6, 2 * depthScale);
          ctx.stroke();

          ctx.beginPath();
          ctx.arc(nodeX, nodeY, radius - 1.2 * depthScale, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(255, 250, 244, 0.88)";
          ctx.lineWidth = Math.max(0.8, 0.95 * depthScale);
          ctx.stroke();
        }

        if (node.type === "temporary") {
          ctx.setLineDash([4, 3]);
        }
        if (!isOrbitMode) {
          ctx.strokeStyle = "#fff";
          ctx.lineWidth = (getMemoryNodeRole(node) === "summary" ? 2.5 : 1.75) * depthScale;
          ctx.stroke();
        }
        ctx.setLineDash([]);

        if (isEditSelectable && !isEditSelected && !isEditAnchor) {
          ctx.beginPath();
          ctx.arc(nodeX, nodeY, radius + 7 * depthScale, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(99, 102, 241, 0.34)";
          ctx.lineWidth = 1.4 * depthScale;
          ctx.stroke();
        }

        if (isEditSelected || isEditAnchor) {
          ctx.beginPath();
          ctx.arc(nodeX, nodeY, radius + 8 * depthScale, 0, Math.PI * 2);
          ctx.strokeStyle = isEditAnchor ? "rgba(255, 255, 255, 0.96)" : "rgba(99, 102, 241, 0.82)";
          ctx.lineWidth = (isEditAnchor ? 2.2 : 1.8) * depthScale;
          ctx.stroke();
        }

        if (getMemoryNodeRole(node) === "summary") {
          ctx.beginPath();
          ctx.arc(nodeX, nodeY, Math.max(radius - 6 * depthScale, 6 * depthScale), 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(255, 246, 221, 0.95)";
          ctx.lineWidth = Math.max(0.9, depthScale);
          ctx.stroke();
        }

        if (isPinnedMemoryNode(node)) {
          ctx.beginPath();
          ctx.arc(nodeX + radius - 3 * depthScale, nodeY - radius + 3 * depthScale, 4 * depthScale, 0, Math.PI * 2);
          ctx.fillStyle = "#fff8e6";
          ctx.fill();
        }
      }

      /* label below node */
      const baseLabel = isCenter ? truncateCenterLabel(centerNodeLabel) : getLabel(node);
      const label = isOrbitMode
        ? getOrbitLabelText(node, baseLabel)
        : baseLabel;
      const labelY = isCenter
        ? nodeY + renderedRadius + 14 * depthScale
        : isFileMemoryNode(node)
          ? nodeY + (FILE_NODE_H * depthScale) / 2 + 12 * depthScale
          : nodeY + renderedRadius + 14 * depthScale;
      const labelColor = isFaded
        ? "rgba(42, 32, 24, 0.42)"
        : isOrbitMode
          ? "rgba(36, 22, 16, 0.96)"
          : "#2a2018";

      if (isOrbitMode) {
        const orbitDepth = orbitWorldById.get(node.id)?.depth ?? (isCenter ? 0 : 1);
        const role = getMemoryNodeRole(node);
        const forceShow = Boolean(isCenter || isEditAnchor || isEditSelected || isSearched);
        const priority =
          (forceShow ? 220 : 0) +
          (isCenter ? 160 : 0) +
          (orbitDepth <= 1 ? 90 : orbitDepth === 2 ? 42 : 0) +
          (role === "subject"
            ? 28
            : role === "concept"
              ? 20
              : role === "summary"
                ? 14
                : 0) +
          depthScale * 18 +
          (getProjectedNode(node.id)?.z ?? 0) * 0.02;
        const shouldQueueLabel =
          forceShow ||
          (!isFileMemoryNode(node) && orbitDepth <= 2 && depthScale >= 0.84) ||
          (isFileMemoryNode(node) && depthScale >= 1.04);

        if (shouldQueueLabel) {
          orbitLabelCandidates.push({
            text: label,
            x: nodeX,
            y: labelY,
            fontSize: 11.5 * clampNumber(depthScale, 0.84, 1.18),
            opacity: labelOpacity * (isFaded ? 0.48 : 1),
            color: labelColor,
            priority,
            z: getProjectedNode(node.id)?.z ?? 0,
            backdrop: forceShow || orbitDepth <= 1 || depthScale > 1.04,
            forceShow,
          });
        }
      } else {
        ctx.globalAlpha = labelOpacity * (isFaded ? 0.34 : 1);
        ctx.fillStyle = labelColor;
        ctx.font = "11px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillText(label, nodeX, labelY);
      }

      ctx.restore();
    });

    if (isOrbitMode) {
      const placedLabelBoxes: Array<{
        left: number;
        top: number;
        right: number;
        bottom: number;
      }> = [];

      orbitLabelCandidates
        .sort((left, right) => right.priority - left.priority || right.z - left.z)
        .forEach((candidate) => {
          if (!candidate.forceShow && candidate.opacity < 0.34) {
            return;
          }
          ctx.save();
          ctx.globalAlpha = candidate.opacity;
          ctx.font = `600 ${candidate.fontSize}px sans-serif`;
          ctx.textAlign = "center";
          ctx.textBaseline = "top";

          const textWidth = ctx.measureText(candidate.text).width;
          const paddingX = candidate.backdrop ? 8 : 2;
          const paddingY = candidate.backdrop ? 5 : 0;
          const height = candidate.fontSize + paddingY * 2;
          const box = {
            left: candidate.x - textWidth / 2 - paddingX,
            top: candidate.y - paddingY,
            right: candidate.x + textWidth / 2 + paddingX,
            bottom: candidate.y + candidate.fontSize + paddingY,
          };
          const collides = placedLabelBoxes.some(
            (placed) =>
              box.left < placed.right &&
              box.right > placed.left &&
              box.top < placed.bottom &&
              box.bottom > placed.top,
          );
          if (collides && !candidate.forceShow) {
            ctx.restore();
            return;
          }

          if (candidate.backdrop) {
            traceRoundedRect(
              ctx,
              box.left,
              box.top,
              box.right - box.left,
              height,
              999,
            );
            ctx.fillStyle = "rgba(255, 252, 249, 0.9)";
            ctx.fill();
            ctx.strokeStyle = "rgba(238, 228, 221, 0.96)";
            ctx.lineWidth = 1;
            ctx.stroke();
          }

          ctx.fillStyle = candidate.color;
          ctx.fillText(
            candidate.text,
            candidate.x,
            candidate.backdrop ? candidate.y + 1 : candidate.y,
          );
          placedLabelBoxes.push(box);
          ctx.restore();
        });
    }

    ctx.restore();
  }, [
    centerNodeId,
    centerNodeLabel,
    centerNodeShortLabel,
    editMode,
    editSelectionSet,
    getOrbitProjectedNodes,
    isOrbitMode,
    maxRetrievalCount,
    orbitWorldById,
    searchMatchIds,
    selectableNodeIds,
    selectedNode,
    simNodeById,
    simLinks,
    simNodes,
    visibleNodeIds,
  ]);

  useEffect(() => {
    drawRef.current = draw;
  }, [draw]);

  /* ── Simulation setup ───────────────────────── */

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const sim = d3
      .forceSimulation<SimNode>(simNodes)
      .force("center", d3.forceCenter(0, 0).strength(0.05))
      .force(
        "link",
        d3
          .forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.id)
          .distance((link) => {
            const sourceId = getSimLinkEndpointId(link.source);
            const targetId = getSimLinkEndpointId(link.target);
            const isStructuralCenterEdge =
              link.edge_type === "center" ||
              isCenterStructuralTreeEdgePair(simNodeById, sourceId, targetId, centerNodeId);
            const isStructuralParentEdge =
              link.edge_type === "parent" ||
              (isStructuralTreeEdgePair(simNodeById, sourceId, targetId, centerNodeId) &&
                !isStructuralCenterEdge);
            if (link.edge_type === "file") {
              return FILE_LINK_DISTANCE;
            }
            if (link.edge_type === "evidence") {
              return isOrbitMode ? 126 : 112;
            }
            if (isStructuralParentEdge) {
              return isOrbitMode ? PARENT_LINK_DISTANCE + 10 : PARENT_LINK_DISTANCE;
            }
            if (isStructuralCenterEdge) {
              return isOrbitMode ? CENTER_LINK_DISTANCE + 6 : CENTER_LINK_DISTANCE - 16;
            }
            if (link.edge_type === "prerequisite") {
              return isOrbitMode ? 154 : 138;
            }
            if (link.edge_type === "conflict") {
              return isOrbitMode ? 136 : 124;
            }
            if (link.edge_type === "supersedes") {
              return isOrbitMode ? 128 : 118;
            }
            if (link.edge_type === "related") {
              return isOrbitMode ? 148 : 134;
            }
            if (link.edge_type === "manual") {
              return isOrbitMode ? 140 : 126;
            }
            return 100;
          })
          .strength((link) => {
            const sourceId = getSimLinkEndpointId(link.source);
            const targetId = getSimLinkEndpointId(link.target);
            const isStructuralCenterEdge =
              link.edge_type === "center" ||
              isCenterStructuralTreeEdgePair(simNodeById, sourceId, targetId, centerNodeId);
            const isStructuralParentEdge =
              link.edge_type === "parent" ||
              (isStructuralTreeEdgePair(simNodeById, sourceId, targetId, centerNodeId) &&
                !isStructuralCenterEdge);
            if (link.edge_type === "file") {
              return 0.9;
            }
            if (link.edge_type === "evidence") {
              return Math.max(0.18, link.strength * (isOrbitMode ? 0.22 : 0.26));
            }
            if (isStructuralParentEdge) {
              return isOrbitMode ? 0.42 : 0.48;
            }
            if (isStructuralCenterEdge) {
              return Math.max(isOrbitMode ? 0.12 : 0.14, link.strength * (isOrbitMode ? 0.18 : 0.22));
            }
            if (link.edge_type === "prerequisite") {
              return Math.max(0.12, link.strength * (isOrbitMode ? 0.18 : 0.21));
            }
            if (link.edge_type === "conflict") {
              return Math.max(0.14, link.strength * (isOrbitMode ? 0.2 : 0.24));
            }
            if (link.edge_type === "supersedes") {
              return Math.max(0.16, link.strength * (isOrbitMode ? 0.22 : 0.26));
            }
            if (link.edge_type === "related") {
              return Math.max(isOrbitMode ? 0.1 : 0.12, link.strength * (isOrbitMode ? 0.16 : 0.18));
            }
            if (link.edge_type === "manual") {
              return Math.max(0.16, link.strength * (isOrbitMode ? 0.22 : 0.26));
            }
            return Math.max(0.18, link.strength * 0.3);
          })
      )
      .force(
        "charge",
        d3.forceManyBody<SimNode>().strength((node) => {
          if (node.id === centerNodeId) {
            return isOrbitMode ? -280 : -220;
          }
          if (isFileMemoryNode(node)) {
            return -12;
          }
          return getMemoryNodeRole(node) === "structure"
            ? (isOrbitMode ? -178 : -140)
            : getMemoryNodeRole(node) === "subject"
              ? (isOrbitMode ? -176 : -144)
              : getMemoryNodeRole(node) === "concept"
              ? (isOrbitMode ? -188 : -150)
              : (isOrbitMode ? -196 : -160);
        }),
      )
      .force("collide", d3.forceCollide<SimNode>((d) => nodeRadius(d, d.id === centerNodeId) + 8))
      .force("treeScaffold", createTreeScaffoldForce(centerNodeId))
      .force("fileAttachment", createFileAttachmentForce(centerNodeId))
      .alphaDecay(isOrbitMode ? 0.018 : 0.02)
      .on("tick", () => {
        cancelAnimationFrame(animFrameRef.current);
        animFrameRef.current = requestAnimationFrame(() => drawRef.current());
      });

    simRef.current = sim;

    /* ── Zoom ── */
    const zoomBehavior = d3
      .zoom<HTMLCanvasElement, unknown>()
      .scaleExtent([0.1, 5])
      .filter((event) => {
        if (!isOrbitMode) {
          return !event.button;
        }
        return event.type === "wheel";
      })
      .on("zoom", (event: d3.D3ZoomEvent<HTMLCanvasElement, unknown>) => {
        transformRef.current = event.transform;
        drawRef.current();
      });

    zoomBehaviorRef.current = zoomBehavior;

    const sel = d3.select(canvas);
    sel.call(zoomBehavior);
    // Disable D3's built-in dblclick zoom so our onDblClick handler fires instead
    sel.on("dblclick.zoom", null);

    /* ── Initial transform ── */
    const rect = canvas.getBoundingClientRect();
    const initialTransform =
      isOrbitMode
        ? buildViewportTransform(
            rect.width,
            rect.height,
            simNodes,
            centerNodeId,
            visibleNodeIdsRef.current,
            getOrbitProjectedNodes(),
            ORBIT_VIEWPORT_OPTIONS,
          ) ??
          d3.zoomIdentity.translate(rect.width / 2, rect.height / 2)
        : d3.zoomIdentity.translate(rect.width / 2, rect.height / 2);
    sel.call(zoomBehavior.transform, initialTransform);
    transformRef.current = initialTransform;

    /* ── Drag ── */
    let dragNode: SimNode | null = null;

    const dragStarted = (x: number, y: number) => {
      const node = hitTestDirect(x, y);
      if (!node || !canGraphRepositionNode(node, centerNodeId)) return;
      dragNode = node;
      sim.alphaTarget(0.3).restart();
      node.fx = node.x;
      node.fy = node.y;
    };

    const dragged = (x: number, y: number) => {
      if (!dragNode) return;
      const t = transformRef.current;
      dragNode.fx = (x - t.x) / t.k;
      dragNode.fy = (y - t.y) / t.k;
    };

    const dragEnded = () => {
      if (!dragNode) return;
      sim.alphaTarget(0);
      const node = dragNode;
      // Keep position fixed after drag
      if (node.fx != null && node.fy != null) {
        const inferredCategory = inferDroppedCategory(node, simNodes, centerNodeId);
        onUpdateMemory(node.id, {
          position_x: node.fx,
          position_y: node.fy,
          ...(inferredCategory && inferredCategory !== node.category
            ? { category: inferredCategory }
            : {}),
        }).catch(() => {});
      }
      node.fx = null;
      node.fy = null;
      dragNode = null;
    };

    function hitTestDirect(mx: number, my: number): SimNode | null {
      const t = transformRef.current;
      const x = (mx - t.x) / t.k;
      const y = (my - t.y) / t.k;
      const projectedNodes = projectedNodeCacheRef.current;
      const orderedNodes = isOrbitMode
        ? [...simNodes].sort(
            (left, right) =>
              (projectedNodes.get(right.id)?.z ?? 0) - (projectedNodes.get(left.id)?.z ?? 0),
          )
        : [...simNodes].reverse();
      for (let i = 0; i < orderedNodes.length; i += 1) {
        const n = orderedNodes[i];
        if (!visibleNodeIdsRef.current.has(n.id)) {
          continue;
        }
        const projected = isOrbitMode ? projectedNodes.get(n.id) : null;
        const r = projected?.radius ?? nodeRadius(n, n.id === centerNodeId);
        const dx = x - (projected?.x ?? n.x);
        const dy = y - (projected?.y ?? n.y);
        if (dx * dx + dy * dy <= r * r) return n;
      }
      return null;
    }

    /* ── Mouse events (directly, not through D3 drag to avoid zoom conflict) ── */
    let isDragging = false;
    let isOrbitRotating = false;
    let dragStartPos = { x: 0, y: 0 };
    let orbitDragOrigin = { x: 0, y: 0 };
    let orbitStartRotation = orbitRotationRef.current;

    const onMouseDown = (e: MouseEvent) => {
      if (e.button !== 0) return; // left click only
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const node = hitTestDirect(mx, my);
      if (editModeRef.current && selectedNodeRef.current) {
        if (
          node &&
          (
            selectableNodeIdsRef.current.has(node.id) ||
            (editModeRef.current === "parent" && node.id === centerNodeId)
          )
        ) {
          suppressClickRef.current = true;
        }
        return;
      }
      if (
        !isOrbitMode &&
        (e.shiftKey || e.altKey) &&
        node &&
        canGraphRepositionNode(node, centerNodeId)
      ) {
        const t = transformRef.current;
        connectStartRef.current = node;
        connectModeRef.current = e.altKey ? "manual" : "parent";
        connectPointerRef.current = {
          x: (mx - t.x) / t.k,
          y: (my - t.y) / t.k,
        };
        suppressClickRef.current = true;
        draw();
        e.preventDefault();
        e.stopPropagation();
        return;
      }
      if (isOrbitMode) {
        isOrbitRotating = true;
        dragStartPos = { x: e.clientX, y: e.clientY };
        orbitDragOrigin = { x: e.clientX, y: e.clientY };
        orbitStartRotation = orbitRotationRef.current;
        suppressClickRef.current = true;
        e.preventDefault();
        e.stopPropagation();
        return;
      }
      if (node && canGraphRepositionNode(node, centerNodeId)) {
        isDragging = true;
        dragStartPos = { x: e.clientX, y: e.clientY };
        dragStarted(mx, my);
        // Temporarily disable zoom panning so drag works
        sel.on(".zoom", null);
        e.preventDefault();
        e.stopPropagation();
      }
    };

    const onMouseMove = (e: MouseEvent) => {
      if (editModeRef.current) {
        return;
      }
      if (connectStartRef.current) {
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const t = transformRef.current;
        connectPointerRef.current = {
          x: (mx - t.x) / t.k,
          y: (my - t.y) / t.k,
        };
        drawRef.current();
        return;
      }
      if (isOrbitRotating) {
        orbitRotationRef.current = {
          yaw: orbitStartRotation.yaw + (e.clientX - orbitDragOrigin.x) * 0.0055,
          pitch: clampNumber(
            orbitStartRotation.pitch + (e.clientY - orbitDragOrigin.y) * 0.0045,
            ORBIT_PITCH_RANGE.min,
            ORBIT_PITCH_RANGE.max,
          ),
        };
        drawRef.current();
        return;
      }
      if (!isDragging) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      dragged(mx, my);
    };

    const onMouseUp = (e: MouseEvent) => {
      if (editModeRef.current && selectedNodeRef.current) {
        return;
      }
      if (connectStartRef.current) {
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const sourceNode = connectStartRef.current;
        const connectMode = connectModeRef.current;
        const targetNode = hitTestDirect(mx, my);
        connectStartRef.current = null;
        connectModeRef.current = null;
        connectPointerRef.current = null;
        if (connectMode === "parent") {
          if (targetNode?.id === centerNodeId) {
            onUpdateMemory(sourceNode.id, { parent_memory_id: null }).catch(() => {});
          } else if (
            targetNode &&
            sourceNode.id !== targetNode.id &&
            !isFileMemoryNode(targetNode) &&
            canPrimaryParentChildren(targetNode)
          ) {
            onUpdateMemory(sourceNode.id, { parent_memory_id: targetNode.id }).catch(() => {});
          } else if (targetNode && !isFileMemoryNode(targetNode)) {
            void modal.alert(t("graph.invalidParentTarget"));
          }
        } else if (
          targetNode &&
          sourceNode.id !== targetNode.id &&
          targetNode.id !== centerNodeId &&
          !isFileMemoryNode(targetNode)
        ) {
          onCreateEdge(sourceNode.id, targetNode.id).catch(() => {});
        }
        drawRef.current();
        return;
      }
      if (isOrbitRotating) {
        isOrbitRotating = false;
        const dist = Math.hypot(
          e.clientX - dragStartPos.x,
          e.clientY - dragStartPos.y,
        );
        if (dist < 4) {
          const rect = canvas.getBoundingClientRect();
          const mx = e.clientX - rect.left;
          const my = e.clientY - rect.top;
          const node = hitTestDirect(mx, my);
          if (!node) {
            setSelectedNode(null);
            onNodeSelect(null);
            return;
          }
          if (node.id === centerNodeId) {
            setSelectedNode(null);
            onNodeSelect(null);
            onCenterNodeClick?.();
            return;
          }
          setSelectedNode(node);
          onNodeSelect(node);
        }
        return;
      }
      if (!isDragging) {
        return;
      }
      isDragging = false;
      dragEnded();
      // Re-enable zoom
      sel.call(zoomBehavior);
      // Restore current transform
      sel.call(zoomBehavior.transform, transformRef.current);

      // Check if this was a click (not a drag)
      const dist = Math.hypot(
        e.clientX - dragStartPos.x,
        e.clientY - dragStartPos.y
      );
      if (dist < 4) {
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const node = hitTestDirect(mx, my);
        if (node) {
          if (node.id === centerNodeId) {
            setSelectedNode(null);
            onNodeSelect(null);
            onCenterNodeClick?.();
            return;
          }
          setSelectedNode(node);
          onNodeSelect(node);
        }
      }
    };

    const onClick = (e: MouseEvent) => {
      if (suppressClickRef.current) {
        suppressClickRef.current = false;
        if (!editMode || !selectedNode) {
          return;
        }
      }
      // Only handle clicks on blank canvas (not on nodes which are handled via drag flow)
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const node = hitTestDirect(mx, my);
      if (editModeRef.current && selectedNodeRef.current) {
        if (!node) {
          return;
        }
        if (editModeRef.current === "parent" && node.id === centerNodeId) {
          setEditSelectionIds([GRAPH_TOP_LEVEL_TARGET_ID]);
          return;
        }
        if (!selectableNodeIdsRef.current.has(node.id)) {
          return;
        }
        if (editModeRef.current === "parent") {
          setEditSelectionIds([node.id]);
          return;
        }
        setEditSelectionIds((current) =>
          current.includes(node.id)
            ? current.filter((candidateId) => candidateId !== node.id)
            : [...current, node.id],
        );
        return;
      }
      if (!node) {
        setSelectedNode(null);
        onNodeSelect(null);
      } else if (node.id === centerNodeId) {
        setSelectedNode(null);
        onNodeSelect(null);
        onCenterNodeClick?.();
      } else {
        setSelectedNode(node);
        onNodeSelect(node);
      }
    };

    const onDblClick = (e: MouseEvent) => {
      if (editModeRef.current) {
        return;
      }
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const node = hitTestDirect(mx, my);
      if (!node) {
        openCreateMemoryDialog();
      }
    };

    const onContextMenu = (e: MouseEvent) => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const node = hitTestDirect(mx, my);
      setContextMenu({
        x: e.clientX,
        y: e.clientY,
        node: node?.id === centerNodeId ? null : node,
        visible: true,
      });
    };

    canvas.addEventListener("mousedown", onMouseDown);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    canvas.addEventListener("click", onClick);
    canvas.addEventListener("dblclick", onDblClick);
    canvas.addEventListener("contextmenu", onContextMenu);

    return () => {
      sim.stop();
      cancelAnimationFrame(animFrameRef.current);
      canvas.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      canvas.removeEventListener("click", onClick);
      canvas.removeEventListener("dblclick", onDblClick);
      canvas.removeEventListener("contextmenu", onContextMenu);
      sel.on(".zoom", null);
    };
    // We intentionally exclude draw from deps to avoid re-creating the simulation
    // on every render. The draw function is captured by the tick callback.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    centerNodeId,
    getOrbitProjectedNodes,
    isOrbitMode,
    onCenterNodeClick,
    onCreateEdge,
    onNodeSelect,
    onUpdateMemory,
    openCreateMemoryDialog,
    simLinks,
    simNodeById,
    simNodes,
  ]);

  /* ── Redraw when filters/search change ─────── */

  useEffect(() => {
    draw();
  }, [draw]);

  useEffect(() => {
    if (!isOrbitMode) {
      orbitAutoFrameKeyRef.current = null;
      return;
    }
    const canvas = canvasRef.current;
    const zb = zoomBehaviorRef.current;
    if (!canvas || !zb || simNodes.length === 0) {
      return;
    }

    const visibleSignature = [...visibleNodeIds].sort().join("|");
    const nextKey = `${centerNodeId}:${visibleSignature}`;
    if (orbitAutoFrameKeyRef.current === nextKey) {
      return;
    }

    const rect = canvas.getBoundingClientRect();
    const nextTransform = buildViewportTransform(
      rect.width,
      rect.height,
      simNodes,
      centerNodeId,
      visibleNodeIds,
      getOrbitProjectedNodes(),
      ORBIT_VIEWPORT_OPTIONS,
    );

    if (!nextTransform) {
      return;
    }

    orbitAutoFrameKeyRef.current = nextKey;
    d3.select(canvas).transition().duration(460).call(zb.transform, nextTransform);
  }, [centerNodeId, getOrbitProjectedNodes, isOrbitMode, simNodes, visibleNodeIds]);

  /* ── Zoom controls ──────────────────────────── */

  const handleZoomIn = useCallback(() => {
    if (isOrbitMode && !orbitWebglUnavailable) {
      orbitSceneRef.current?.zoomIn();
      return;
    }
    const canvas = canvasRef.current;
    const zb = zoomBehaviorRef.current;
    if (!canvas || !zb) return;
    const sel = d3.select(canvas);
    sel.transition().duration(300).call(zb.scaleBy, 1.3);
  }, [isOrbitMode, orbitWebglUnavailable]);

  const handleZoomOut = useCallback(() => {
    if (isOrbitMode && !orbitWebglUnavailable) {
      orbitSceneRef.current?.zoomOut();
      return;
    }
    const canvas = canvasRef.current;
    const zb = zoomBehaviorRef.current;
    if (!canvas || !zb) return;
    const sel = d3.select(canvas);
    sel.transition().duration(300).call(zb.scaleBy, 0.7);
  }, [isOrbitMode, orbitWebglUnavailable]);

  const handleFitView = useCallback(() => {
    if (isOrbitMode && !orbitWebglUnavailable) {
      orbitSceneRef.current?.fitView();
      return;
    }
    const canvas = canvasRef.current;
    const zb = zoomBehaviorRef.current;
    if (!canvas || !zb || simNodes.length === 0) return;
    const rect = canvas.getBoundingClientRect();
    const orbitProjectedNodes = isOrbitMode ? getOrbitProjectedNodes() : null;
    const t = buildViewportTransform(
      rect.width,
      rect.height,
      simNodes,
      centerNodeId,
      visibleNodeIds,
      orbitProjectedNodes,
      isOrbitMode
        ? ORBIT_VIEWPORT_OPTIONS
        : {
            fill: 0.85,
            maxScale: 5,
            minScale: 0.1,
            padding: 20,
            xBias: 0.5,
            yBias: 0.5,
          },
    );
    if (!t) return;

    const sel = d3.select(canvas);
    sel.transition().duration(500).call(zb.transform, t);
  }, [
    centerNodeId,
    getOrbitProjectedNodes,
    isOrbitMode,
    orbitWebglUnavailable,
    simNodes,
    visibleNodeIds,
  ]);

  useEffect(() => {
    if (!searchMatchIds || searchMatchIds.size === 0) {
      return;
    }
    const canvas = canvasRef.current;
    const zb = zoomBehaviorRef.current;
    if (!canvas || !zb) return;

    const rect = canvas.getBoundingClientRect();
    const orbitProjectedNodes = isOrbitMode ? getOrbitProjectedNodes() : null;
    const matchedNodes = simNodes.filter(
      (node) => visibleNodeIds.has(node.id) && searchMatchIds.has(node.id),
    );
    if (matchedNodes.length === 0) return;

    const matchedNodeIds = new Set(matchedNodes.map((node) => node.id));
    const t = buildViewportTransform(
      rect.width,
      rect.height,
      matchedNodes,
      centerNodeId,
      matchedNodeIds,
      orbitProjectedNodes,
      isOrbitMode
        ? ORBIT_FOCUS_VIEWPORT_OPTIONS
        : {
            fill: 0.9,
            maxScale: 2.2,
            minScale: 0.1,
            padding: 24,
            xBias: 0.5,
            yBias: 0.5,
          },
    );
    if (!t) return;

    d3.select(canvas).transition().duration(360).call(zb.transform, t);
  }, [centerNodeId, getOrbitProjectedNodes, isOrbitMode, searchMatchIds, simNodes, visibleNodeIds]);

  /* ── Stats ──────────────────────────────────── */

  const fileCount = useMemo(
    () =>
      nodes.filter(
        (node) =>
          visibleNodeIds.has(node.id) &&
          (!searchMatchIds || searchMatchIds.has(node.id)) &&
          isFileMemoryNode(node),
      ).length,
    [nodes, searchMatchIds, visibleNodeIds],
  );
  const memoryCount = useMemo(
    () =>
      nodes.filter(
        (node) =>
          visibleNodeIds.has(node.id) &&
          (!searchMatchIds || searchMatchIds.has(node.id)) &&
          getGraphNodeDisplayType(node) === "memory",
      ).length,
    [nodes, searchMatchIds, visibleNodeIds],
  );
  const branchCount = useMemo(() => {
    const branchIds = new Set<string>();
    nodes.forEach((node) => {
      if (
        !visibleNodeIds.has(node.id) ||
        (searchMatchIds !== null && !searchMatchIds.has(node.id)) ||
        isFileMemoryNode(node) ||
        node.id === centerNodeId
      ) {
        return;
      }
      const parentId = node.parent_memory_id;
      if (!parentId || parentId === centerNodeId) {
        branchIds.add(node.id);
      }
    });
    return branchIds.size;
  }, [centerNodeId, nodes, searchMatchIds, visibleNodeIds]);
  const relatedCount = useMemo(
    () =>
      simLinks.filter((link) => {
        const source = link.source as SimNode;
        const target = link.target as SimNode;
        return (
          visibleNodeIds.has(source.id) &&
          visibleNodeIds.has(target.id) &&
          (!searchMatchIds || (searchMatchIds.has(source.id) || searchMatchIds.has(target.id))) &&
          (link.edge_type === "manual" || link.edge_type === "related")
        );
      }).length,
    [searchMatchIds, simLinks, visibleNodeIds],
  );
  const temporaryCount = useMemo(
    () =>
      nodes.filter(
        (node) =>
          visibleNodeIds.has(node.id) &&
          (!searchMatchIds || searchMatchIds.has(node.id)) &&
          !isFileMemoryNode(node) &&
          node.type === "temporary",
      ).length,
    [nodes, searchMatchIds, visibleNodeIds],
  );

  /* ── Context menu actions ───────────────────── */

  const contextActions = useMemo(
    () => ({
      onViewDetail: (node: MemoryNode) => {
        setSelectedNode(node);
        onNodeSelect(node);
      },
      onEdit: (node: MemoryNode) => {
        setSelectedNode(node);
        onNodeSelect(node);
      },
      onPromote: (id: string) => {
        onPromoteMemory(id);
      },
      onDelete: (id: string) => {
        void modal.confirm(confirmDeleteMessage).then((ok) => {
          if (ok) onDeleteMemory(id);
        });
      },
      onAddMemory: () => {
        openCreateMemoryDialog();
      },
    }),
    [confirmDeleteMessage, modal, onDeleteMemory, onNodeSelect, onPromoteMemory, openCreateMemoryDialog]
  );

  /* ── Render ─────────────────────────────────── */

  return (
    <div className={`graph-container graph-container--${renderMode}`}>
      <GraphFilters
        nodes={nodes}
        activeFilters={filterState}
        onFilterChange={setFilterState}
        collapsed={filtersCollapsed}
        onToggleCollapsed={() => setFiltersCollapsed((value) => !value)}
      />

      <div className={`graph-main graph-main--${renderMode}`}>
        <div className="graph-atmosphere" aria-hidden="true">
          <span className="graph-atmosphere-orb is-primary" />
          <span className="graph-atmosphere-orb is-secondary" />
          <span className="graph-atmosphere-grid" />
        </div>
        <div className={`graph-mode-hud graph-mode-hud--${renderMode}`}>
          <span className="graph-mode-hud-kicker">
            {isOrbitMode ? t("graph.modeOrbit") : t("graph.modeWorkbench")}
          </span>
        </div>

        {isOrbitMode && !orbitWebglUnavailable ? (
          <MemoryGraphOrbitScene
            ref={orbitSceneRef}
            nodes={simNodes}
            links={orbitSceneLinks}
            centerNodeId={centerNodeId}
            centerNodeLabel={centerNodeLabel}
            centerNodeShortLabel={centerNodeShortLabel}
            worldById={orbitWorldById}
            visibleNodeIds={visibleNodeIds}
            searchMatchIds={searchMatchIds}
            selectedNodeId={selectedNode?.id ?? null}
            maxRetrievalCount={maxRetrievalCount}
            onSelectNode={(node) => {
              setSelectedNode(node);
              onNodeSelect(node);
            }}
            onCenterNodeClick={onCenterNodeClick}
            onRendererUnavailable={() => {
              setOrbitWebglUnavailable(true);
            }}
          />
        ) : (
          <canvas
            ref={canvasRef}
            className="graph-canvas"
          />
        )}

        {selectedNode && editMode ? (
          <div className="graph-edit-banner">
            <div className="graph-edit-banner-copy">
              <span className="graph-edit-banner-kicker">
                {editMode === "parent"
                  ? t("graph.selectionParentTitle")
                  : editMode === "children"
                    ? t("graph.selectionChildrenTitle")
                    : t("graph.selectionRelatedTitle")}
              </span>
              <p className="graph-edit-banner-text">
                {editMode === "parent"
                  ? t("graph.selectionParentDescription")
                  : editMode === "children"
                    ? t("graph.selectionChildrenDescription")
                    : t("graph.selectionRelatedDescription")}
              </p>
            </div>
            <div className="graph-edit-banner-actions">
              <button
                type="button"
                className="graph-controls-btn"
                onClick={clearEditSelection}
                disabled={editPending}
              >
                {t("graph.clearSelection")}
              </button>
              <button
                type="button"
                className="graph-controls-btn"
                onClick={cancelEditMode}
                disabled={editPending}
              >
                {t("graph.cancel")}
              </button>
              <button
                type="button"
                className="graph-controls-btn is-add"
                onClick={() => void applyEditMode()}
                disabled={editPending}
              >
                {editPending ? t("graph.applyingSelection") : t("graph.applySelection")}
              </button>
            </div>
          </div>
        ) : null}

        <GraphControls
          nodeCount={memoryCount}
          fileCount={fileCount}
          branchCount={branchCount}
          relatedCount={relatedCount}
          temporaryCount={temporaryCount}
          renderMode={renderMode}
          onAdd={openCreateMemoryDialog}
          searchQuery={searchQuery}
          onSearchChange={setLocalSearch}
          onZoomIn={handleZoomIn}
          onZoomOut={handleZoomOut}
          onFitView={handleFitView}
        />
      </div>

      {selectedNode && (
        <NodeDetail
          key={selectedNode.id}
          node={selectedNode}
          allNodes={nodes}
          onClose={() => {
            cancelEditMode();
            setSelectedNode(null);
            onNodeSelect(null);
          }}
          onFocusNode={(node) => {
            cancelEditMode();
            setSelectedNode(node);
            onNodeSelect(node);
          }}
          onUpdate={onUpdateMemory}
          onDelete={onDeleteMemory}
          onPromote={onPromoteMemory}
          onDeleteEdge={onDeleteEdge}
          onAttachFile={onAttachFile}
          onDetachFile={onDetachFile}
          editMode={editMode}
          editSelectionIds={editSelectionIds}
          editPending={editPending}
          topLevelSelectionId={GRAPH_TOP_LEVEL_TARGET_ID}
          onBeginEditMode={beginEditMode}
          onCancelEditMode={cancelEditMode}
          onClearEditModeSelection={clearEditSelection}
          onApplyEditMode={applyEditMode}
        />
      )}

      <GraphContextMenu
        x={contextMenu.x}
        y={contextMenu.y}
        node={contextMenu.node}
        visible={contextMenu.visible}
        onClose={() => setContextMenu((c) => ({ ...c, visible: false }))}
        actions={contextActions}
      />

      <Dialog
        open={createMemoryOpen}
        onOpenChange={(open) => {
          if (open) {
            setCreateMemoryOpen(true);
            return;
          }
          closeCreateMemoryDialog();
        }}
      >
        <DialogContent className="sm:max-w-[460px]">
          <DialogHeader>
            <DialogTitle>{addMemoryTitle}</DialogTitle>
            <p className="text-sm text-muted-foreground">{addMemoryPrompt}</p>
          </DialogHeader>

          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              void handleCreateMemorySubmit();
            }}
          >
            <div className="space-y-2">
              <label className="graph-detail-label" htmlFor="memory-create-content">
                {t("graph.contentLabel")}
              </label>
              <textarea
                id="memory-create-content"
                className="graph-detail-textarea"
                value={createMemoryContent}
                onChange={(event) => setCreateMemoryContent(event.target.value)}
                rows={5}
                autoFocus
              />
            </div>

            <div className="space-y-2">
              <label className="graph-detail-label" htmlFor="memory-create-category">
                {t("graph.category")}
              </label>
              <input
                id="memory-create-category"
                className="graph-detail-input"
                value={createMemoryCategory}
                onChange={(event) => setCreateMemoryCategory(event.target.value)}
                type="text"
              />
            </div>

            <DialogFooter>
              <button
                type="button"
                className="graph-detail-btn"
                onClick={closeCreateMemoryDialog}
                disabled={creatingMemory}
              >
                {t("graph.cancel")}
              </button>
              <button
                type="submit"
                className="graph-detail-btn is-primary"
                disabled={creatingMemory || createMemoryContent.trim().length === 0}
              >
                {creatingMemory ? "..." : t("graph.save")}
              </button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
