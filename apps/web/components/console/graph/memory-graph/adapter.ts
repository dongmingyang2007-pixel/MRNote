import type { MemoryNode as BackendNode, MemoryEdge as BackendEdge } from "@/hooks/useGraphData";
import {
  getGraphNodeDisplayType,
  getMemoryNodeRole,
  isPinnedMemoryNode,
  getMemoryRetrievalCount,
  getMemoryLastUsedAt,
} from "@/hooks/useGraphData";
import { LABEL_MAX_CHARS } from "./constants";
import { humanizeRelativeTime } from "./humanize";
import type { GraphEdge, GraphNode, Role } from "./types";

function truncateLabel(content: string): string {
  const trimmed = (content ?? "").trim();
  if (trimmed.length <= LABEL_MAX_CHARS) return trimmed;
  return trimmed.slice(0, LABEL_MAX_CHARS) + "…";
}

function resolveRole(node: BackendNode): Role | null {
  const role = getMemoryNodeRole(node);
  return role;
}

function adaptNode(node: BackendNode): GraphNode | null {
  const displayType = getGraphNodeDisplayType(node);
  if (displayType !== "memory") return null;

  const role = resolveRole(node);
  if (!role) return null;

  // Use metadata.category_label when present; fall back to raw node.category verbatim.
  // We avoid getMemoryCategoryLabel's built-in fallback (last path segment) because the
  // test requires the full node.category string when no category_label metadata exists.
  const explicitLabel = node.metadata_json?.category_label;
  const source =
    (typeof explicitLabel === "string" && explicitLabel.trim() ? explicitLabel.trim() : null) ??
    (typeof node.category === "string" && node.category ? node.category : null);

  return {
    id: node.id,
    role,
    label: truncateLabel(node.content || ""),
    conf: typeof node.confidence === "number" && Number.isFinite(node.confidence) ? node.confidence : 0.5,
    reuse: getMemoryRetrievalCount(node),
    lastUsed: humanizeRelativeTime(getMemoryLastUsedAt(node)),
    pinned: isPinnedMemoryNode(node),
    source: source || null,
    raw: node,
  };
}

function adaptEdge(edge: BackendEdge, nodeIds: Set<string>): GraphEdge | null {
  if (!nodeIds.has(edge.source_memory_id) || !nodeIds.has(edge.target_memory_id)) {
    return null;
  }
  return {
    a: edge.source_memory_id,
    b: edge.target_memory_id,
    rel: edge.edge_type,
    w: typeof edge.strength === "number" && Number.isFinite(edge.strength) ? edge.strength : 0.5,
  };
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export function adaptGraphData(raw: { nodes: BackendNode[]; edges: BackendEdge[] }): GraphData {
  const nodes: GraphNode[] = [];
  for (const bn of raw.nodes) {
    const gn = adaptNode(bn);
    if (gn) nodes.push(gn);
  }
  const ids = new Set(nodes.map((n) => n.id));
  const edges: GraphEdge[] = [];
  for (const be of raw.edges) {
    const ge = adaptEdge(be, ids);
    if (ge) edges.push(ge);
  }
  return { nodes, edges };
}
