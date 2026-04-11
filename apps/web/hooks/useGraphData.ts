"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { apiGet, apiPost, apiPatch, apiDelete } from "@/lib/api";
import { getApiHttpBaseUrl } from "@/lib/env";

export type MemoryKind =
  | "profile"
  | "preference"
  | "goal"
  | "episodic"
  | "fact"
  | "summary";

export type GraphNodeDisplayType = "center" | "memory" | "file";
export type MemoryNodeRole = "fact" | "structure" | "subject" | "concept" | "summary";

export interface MemoryMetadataJson extends Record<string, unknown> {
  memory_kind?: MemoryKind;
  node_kind?: string;
  node_type?: string;
  subject_kind?: string;
  subject_memory_id?: string | null;
  node_status?: string;
  canonical_key?: string;
  lineage_key?: string;
  concept_source?: string;
  parent_binding?: "auto" | "manual" | string;
  manual_parent_id?: string | null;
  pinned?: boolean;
  salience?: number;
  importance?: number;
  last_used_at?: string;
  last_used_source?: string;
  last_retrieval_score?: number;
  retrieval_count?: number;
  conflict_with_memory_id?: string;
  source_count?: number;
  source_memory_ids?: string[];
  summary_group_key?: string;
  visibility?: "public" | "private" | string;
  owner_user_id?: string;
  auto_generated?: boolean;
  promoted_by?: string;
  structural_only?: boolean;
  category_path?: string;
  category_label?: string;
  category_segments?: string[];
  category_prefixes?: string[];
  category_depth?: number;
  synthetic_graph_node?: boolean;
  graph_parent_memory_id?: string | null;
}

export interface MemoryNode {
  id: string;
  workspace_id: string;
  project_id: string;
  content: string;
  category: string;
  type: "permanent" | "temporary";
  confidence?: number | null;
  observed_at?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  last_confirmed_at?: string | null;
  suppression_reason?: string | null;
  reconfirm_after?: string | null;
  last_used_at?: string | null;
  reuse_success_rate?: number | null;
  node_type?: string | null;
  subject_kind?: string | null;
  subject_memory_id?: string | null;
  node_status?: string | null;
  canonical_key?: string | null;
  lineage_key?: string | null;
  source_conversation_id: string | null;
  parent_memory_id: string | null;
  position_x: number | null;
  position_y: number | null;
  metadata_json: MemoryMetadataJson;
  created_at: string;
  updated_at: string;
  // D3 simulation fields (added at runtime)
  x?: number;
  y?: number;
  fx?: number | null;
  fy?: number | null;
}

export function isFileMemoryNode(node: MemoryNode): boolean {
  return (
    node.category === "file" ||
    node.category === "文件" ||
    node.metadata_json?.node_kind === "file"
  );
}

export function isAssistantRootMemoryNode(node: MemoryNode): boolean {
  return node.node_type === "root" || node.metadata_json?.node_kind === "assistant-root";
}

export function getGraphNodeDisplayType(
  node: MemoryNode | MemoryMetadataJson | null | undefined,
): GraphNodeDisplayType {
  const metadata = getMemoryMetadata(node);
  const nodeKind = metadata.node_kind;
  if (
    metadata.node_type === "root" ||
    nodeKind === "assistant-root" ||
    nodeKind === "assistant-center"
  ) {
    return "center";
  }
  if (
    nodeKind === "file" ||
    ("category" in (node || {}) &&
      (node as MemoryNode).category &&
      ((node as MemoryNode).category === "file" || (node as MemoryNode).category === "文件"))
  ) {
    return "file";
  }
  return "memory";
}

export function isConceptMemoryNode(node: MemoryNode | MemoryMetadataJson): boolean {
  const metadata = getMemoryMetadata(node);
  return metadata.node_type === "concept" || metadata.node_kind === "concept";
}

export function isSubjectMemoryNode(node: MemoryNode | MemoryMetadataJson): boolean {
  const metadata = getMemoryMetadata(node);
  return metadata.node_type === "subject" || metadata.node_kind === "subject";
}

export function isCategoryPathMemoryNode(node: MemoryNode | MemoryMetadataJson): boolean {
  const metadata = getMemoryMetadata(node);
  return metadata.node_kind === "category-path" || metadata.concept_source === "category_path";
}

export function isStructuralOnlyMemoryNode(node: MemoryNode | MemoryMetadataJson): boolean {
  const metadata = getMemoryMetadata(node);
  return metadata.structural_only === true || isCategoryPathMemoryNode(metadata);
}

export function isSyntheticGraphNode(node: MemoryNode | MemoryMetadataJson): boolean {
  return getMemoryMetadata(node).synthetic_graph_node === true;
}

export function getMemoryNodeRole(
  node: MemoryNode | MemoryMetadataJson | null | undefined,
): MemoryNodeRole | null {
  if (getGraphNodeDisplayType(node) !== "memory") {
    return null;
  }
  const metadata = getMemoryMetadata(node);
  if (isCategoryPathMemoryNode(metadata) || metadata.structural_only === true) {
    return "structure";
  }
  if (isSubjectMemoryNode(metadata)) {
    return "subject";
  }
  if (isConceptMemoryNode(metadata)) {
    return "concept";
  }
  if (isSummaryMemoryNode(metadata)) {
    return "summary";
  }
  return "fact";
}

export function isMemoryDisplayNode(
  node: MemoryNode | MemoryMetadataJson | null | undefined,
): boolean {
  return getGraphNodeDisplayType(node) === "memory";
}

export function isStructureMemoryNode(
  node: MemoryNode | MemoryMetadataJson | null | undefined,
): boolean {
  return getMemoryNodeRole(node) === "structure";
}

export function isThemeMemoryNode(
  node: MemoryNode | MemoryMetadataJson | null | undefined,
): boolean {
  const role = getMemoryNodeRole(node);
  return role === "subject" || role === "concept";
}

export function isFactMemoryNode(
  node: MemoryNode | MemoryMetadataJson | null | undefined,
): boolean {
  return getMemoryNodeRole(node) === "fact";
}

export function isOrdinaryMemoryNode(node: MemoryNode): boolean {
  return isFactMemoryNode(node);
}

export function getMemoryMetadata(
  value: MemoryNode | MemoryMetadataJson | null | undefined,
): MemoryMetadataJson {
  if (!value || typeof value !== "object") {
    return {};
  }
  if ("metadata_json" in value && value.metadata_json && typeof value.metadata_json === "object") {
    return value.metadata_json as MemoryMetadataJson;
  }
  return value as MemoryMetadataJson;
}

export function getMemoryKind(node: MemoryNode | MemoryMetadataJson): MemoryKind | null {
  const metadata = getMemoryMetadata(node);
  const kind = metadata.memory_kind;
  return typeof kind === "string" && kind.length > 0 ? kind : null;
}

export function getMemoryParentBinding(node: MemoryNode | MemoryMetadataJson): "auto" | "manual" {
  const value = getMemoryMetadata(node).parent_binding;
  return value === "manual" ? "manual" : "auto";
}

export function getMemoryPrimaryParentId(
  node: MemoryNode | MemoryMetadataJson | null | undefined,
): string | null {
  const metadata = getMemoryMetadata(node);
  if (typeof metadata.graph_parent_memory_id === "string" && metadata.graph_parent_memory_id) {
    return metadata.graph_parent_memory_id;
  }
  if (node && typeof node === "object" && "parent_memory_id" in node) {
    const parentId = node.parent_memory_id;
    return typeof parentId === "string" && parentId ? parentId : null;
  }
  return null;
}

export function hasManualParentBinding(node: MemoryNode | MemoryMetadataJson): boolean {
  return getMemoryParentBinding(node) === "manual";
}

export function isSummaryMemoryNode(node: MemoryNode | MemoryMetadataJson): boolean {
  const metadata = getMemoryMetadata(node);
  return metadata.node_kind === "summary" || metadata.memory_kind === "summary";
}

export function canPrimaryParentChildren(node: MemoryNode | MemoryMetadataJson): boolean {
  const displayType = getGraphNodeDisplayType(node);
  if (displayType === "center") {
    return true;
  }
  if (displayType !== "memory") {
    return false;
  }
  const role = getMemoryNodeRole(node);
  return role === "structure" || role === "subject" || role === "concept" || role === "summary";
}

export function isPinnedMemoryNode(node: MemoryNode | MemoryMetadataJson): boolean {
  return getMemoryMetadata(node).pinned === true;
}

export function getMemorySalience(node: MemoryNode | MemoryMetadataJson): number | null {
  const salience = getMemoryMetadata(node).salience;
  return typeof salience === "number" && Number.isFinite(salience) ? salience : null;
}

export function getMemoryRetrievalCount(node: MemoryNode | MemoryMetadataJson): number {
  const count = getMemoryMetadata(node).retrieval_count;
  return typeof count === "number" && Number.isFinite(count) ? count : 0;
}

export function isMemoryStale(node: MemoryNode | MemoryMetadataJson): boolean {
  if (
    node &&
    typeof node === "object" &&
    "valid_to" in node &&
    typeof node.valid_to === "string" &&
    node.valid_to
  ) {
    return new Date(node.valid_to).getTime() < Date.now();
  }
  return false;
}

export function isConflictMemoryNode(node: MemoryNode | MemoryMetadataJson): boolean {
  const metadata = getMemoryMetadata(node);
  return (
    typeof metadata.conflict_with_memory_id === "string" &&
    metadata.conflict_with_memory_id.length > 0
  );
}

export function getMemoryCategorySegments(node: MemoryNode | MemoryMetadataJson): string[] {
  const metadata = getMemoryMetadata(node);
  const segments = metadata.category_segments;
  if (Array.isArray(segments)) {
    return segments.filter((value): value is string => typeof value === "string" && value.length > 0);
  }
  if ("category" in node && typeof node.category === "string") {
    return node.category.split(".").map((segment) => segment.trim()).filter(Boolean);
  }
  return [];
}

export function getMemoryCategoryPrefixes(node: MemoryNode | MemoryMetadataJson): string[] {
  const metadata = getMemoryMetadata(node);
  const prefixes = metadata.category_prefixes;
  if (Array.isArray(prefixes)) {
    return prefixes.filter((value): value is string => typeof value === "string" && value.length > 0);
  }
  const segments = getMemoryCategorySegments(node);
  const values: string[] = [];
  const parts: string[] = [];
  segments.forEach((segment) => {
    parts.push(segment);
    values.push(parts.join("."));
  });
  return values;
}

export function getMemoryCategoryLabel(node: MemoryNode | MemoryMetadataJson): string {
  const metadata = getMemoryMetadata(node);
  if (typeof metadata.category_label === "string" && metadata.category_label.trim()) {
    return metadata.category_label.trim();
  }
  const segments = getMemoryCategorySegments(node);
  return segments[segments.length - 1] || "";
}

export function getMemoryCategoryPath(node: MemoryNode | MemoryMetadataJson): string {
  const metadata = getMemoryMetadata(node);
  if (typeof metadata.category_path === "string" && metadata.category_path.trim()) {
    return metadata.category_path.trim();
  }
  const prefixes = getMemoryCategoryPrefixes(node);
  return prefixes[prefixes.length - 1] || "";
}

export function getMemoryLastUsedAt(node: MemoryNode | MemoryMetadataJson): string | null {
  const value = getMemoryMetadata(node).last_used_at;
  return typeof value === "string" && value ? value : null;
}

export function getMemoryLastUsedSource(node: MemoryNode | MemoryMetadataJson): string | null {
  const value = getMemoryMetadata(node).last_used_source;
  return typeof value === "string" && value ? value : null;
}

export function getSummarySourceCount(node: MemoryNode | MemoryMetadataJson): number {
  const value = getMemoryMetadata(node).source_count;
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export interface MemoryEdge {
  id: string;
  source_memory_id: string;
  target_memory_id: string;
  edge_type:
    | "auto"
    | "manual"
    | "related"
    | "summary"
    | "file"
    | "center"
    | "parent"
    | "prerequisite"
    | "evidence"
    | "supersedes"
    | "conflict";
  strength: number;
  confidence?: number | null;
  observed_at?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  metadata_json?: Record<string, unknown>;
  created_at: string;
  // D3 fields
  source?: string | MemoryNode;
  target?: string | MemoryNode;
}

export interface MemoryFileAttachment {
  id: string;
  memory_id: string;
  data_item_id: string;
  filename?: string | null;
  media_type?: string | null;
  created_at: string;
}

interface GraphData {
  nodes: MemoryNode[];
  edges: MemoryEdge[];
}

function augmentGraphDataWithCategoryBranches(raw: GraphData): GraphData {
  return {
    nodes: (Array.isArray(raw.nodes) ? raw.nodes : [])
      .filter(
        (node) =>
          !isSyntheticGraphNode(node) &&
          node.node_status !== "superseded" &&
          node.node_status !== "archived",
      ),
    edges: (Array.isArray(raw.edges) ? raw.edges : []).filter((edge) => !edge.id.startsWith("graph-category:")),
  };
}

interface NormalizeStreamNodeOptions {
  projectId: string;
  previous?: MemoryNode;
}

function normalizeStreamNode(
  node: Partial<MemoryNode>,
  options: NormalizeStreamNodeOptions,
): MemoryNode {
  const { projectId, previous } = options;
  const now = new Date().toISOString();
  return {
    id: node.id || previous?.id || "",
    workspace_id: node.workspace_id || previous?.workspace_id || "",
    project_id: node.project_id || previous?.project_id || projectId,
    content: node.content || previous?.content || "",
    category: node.category || previous?.category || "",
    type: node.type || previous?.type || "temporary",
    confidence:
      node.confidence !== undefined
        ? node.confidence
        : (previous?.confidence ?? null),
    observed_at:
      node.observed_at !== undefined
        ? node.observed_at
        : (previous?.observed_at ?? null),
    valid_from:
      node.valid_from !== undefined
        ? node.valid_from
        : (previous?.valid_from ?? null),
    valid_to:
      node.valid_to !== undefined
        ? node.valid_to
        : (previous?.valid_to ?? null),
    last_confirmed_at:
      node.last_confirmed_at !== undefined
        ? node.last_confirmed_at
        : (previous?.last_confirmed_at ?? null),
    node_type:
      node.node_type !== undefined
        ? node.node_type
        : (previous?.node_type ?? null),
    subject_kind:
      node.subject_kind !== undefined
        ? node.subject_kind
        : (previous?.subject_kind ?? null),
    subject_memory_id:
      node.subject_memory_id !== undefined
        ? node.subject_memory_id
        : (previous?.subject_memory_id ?? null),
    node_status:
      node.node_status !== undefined
        ? node.node_status
        : (previous?.node_status ?? null),
    canonical_key:
      node.canonical_key !== undefined
        ? node.canonical_key
        : (previous?.canonical_key ?? null),
    lineage_key:
      node.lineage_key !== undefined
        ? node.lineage_key
        : (previous?.lineage_key ?? null),
    source_conversation_id:
      node.source_conversation_id !== undefined
        ? node.source_conversation_id
        : (previous?.source_conversation_id ?? null),
    parent_memory_id:
      node.parent_memory_id !== undefined
        ? node.parent_memory_id
        : (previous?.parent_memory_id ?? null),
    position_x:
      node.position_x !== undefined ? node.position_x : (previous?.position_x ?? null),
    position_y:
      node.position_y !== undefined ? node.position_y : (previous?.position_y ?? null),
    metadata_json:
      (node.metadata_json as MemoryMetadataJson | undefined) ||
      previous?.metadata_json ||
      {},
    created_at: node.created_at || previous?.created_at || now,
    updated_at: node.updated_at || previous?.updated_at || node.created_at || now,
  };
}

export function getMemoryLineageKey(
  node: MemoryNode | MemoryMetadataJson | null | undefined,
): string | null {
  const metadata = getMemoryMetadata(node);
  if (node && typeof node === "object" && "lineage_key" in node) {
    const value = node.lineage_key;
    if (typeof value === "string" && value) {
      return value;
    }
  }
  const value = metadata.lineage_key;
  return typeof value === "string" && value ? value : null;
}

interface UseGraphDataOptions {
  conversationId?: string;
  includeTemporary?: boolean;
}

export function useGraphData(projectId: string, options: UseGraphDataOptions = {}) {
  const { conversationId, includeTemporary = false } = options;
  const [data, setData] = useState<GraphData>({ nodes: [], edges: [] });
  const [loading, setLoading] = useState(true);
  const silentRefreshTimerRef = useRef<number | null>(null);
  const fetchRequestSeqRef = useRef(0);
  const activeFetchControllerRef = useRef<AbortController | null>(null);

  const cancelActiveFetch = useCallback(() => {
    activeFetchControllerRef.current?.abort();
    activeFetchControllerRef.current = null;
  }, []);

  const fetchGraph = useCallback(async (options?: { silent?: boolean }) => {
    if (!projectId) {
      cancelActiveFetch();
      setData({ nodes: [], edges: [] });
      setLoading(false);
      return;
    }
    cancelActiveFetch();
    const requestSeq = ++fetchRequestSeqRef.current;
    const controller = new AbortController();
    activeFetchControllerRef.current = controller;
    if (!options?.silent) {
      setLoading(true);
    }
    try {
      const params = new URLSearchParams({ project_id: projectId });
      if (conversationId) params.set("conversation_id", conversationId);
      if (includeTemporary) params.set("include_temporary", "true");
      const result = await apiGet<GraphData>(`/api/v1/memory?${params}`, {
        signal: controller.signal,
      });
      if (controller.signal.aborted || fetchRequestSeqRef.current !== requestSeq) {
        return;
      }
      setData(augmentGraphDataWithCategoryBranches(result));
    } catch (error) {
      if (
        controller.signal.aborted ||
        fetchRequestSeqRef.current !== requestSeq ||
        (error instanceof DOMException && error.name === "AbortError")
      ) {
        return;
      }
      // show empty graph on error
      setData({ nodes: [], edges: [] });
    } finally {
      if (activeFetchControllerRef.current === controller) {
        activeFetchControllerRef.current = null;
      }
      if (!options?.silent && fetchRequestSeqRef.current === requestSeq) {
        setLoading(false);
      }
    }
  }, [cancelActiveFetch, conversationId, includeTemporary, projectId]);

  const scheduleSilentGraphRefresh = useCallback((delayMs = 180) => {
    if (silentRefreshTimerRef.current !== null) {
      window.clearTimeout(silentRefreshTimerRef.current);
    }
    silentRefreshTimerRef.current = window.setTimeout(() => {
      silentRefreshTimerRef.current = null;
      void fetchGraph({ silent: true });
    }, delayMs);
  }, [fetchGraph]);

  useEffect(() => {
    void fetchGraph();
  }, [fetchGraph]);

  useEffect(
    () => () => {
      cancelActiveFetch();
      if (silentRefreshTimerRef.current !== null) {
        window.clearTimeout(silentRefreshTimerRef.current);
        silentRefreshTimerRef.current = null;
      }
    },
    [cancelActiveFetch, fetchGraph],
  );

  // SSE subscription for real-time memory updates
  useEffect(() => {
    if (!projectId || loading) return;

    let eventSource: EventSource | null = null;
    let retryTimeout: ReturnType<typeof setTimeout>;

    function connect() {
      const apiBase = getApiHttpBaseUrl();
      const streamPath = conversationId
        ? `/api/v1/chat/conversations/${conversationId}/memory-stream`
        : `/api/v1/memory/${projectId}/stream`;
      eventSource = new EventSource(`${apiBase}${streamPath}`, { withCredentials: true });

      eventSource.addEventListener("new_memory", (event) => {
        try {
          const newNode = JSON.parse(event.data) as Partial<MemoryNode>;
          if (
            conversationId &&
            newNode.type === "temporary" &&
            newNode.source_conversation_id !== conversationId
          ) {
            return;
          }
          setData((prev) => ({
            ...augmentGraphDataWithCategoryBranches({
              ...prev,
              nodes: prev.nodes.some((node) => node.id === newNode.id)
                ? prev.nodes.map((node) =>
                    node.id === newNode.id
                      ? normalizeStreamNode(newNode, { projectId, previous: node })
                      : node,
                  )
                : [...prev.nodes, normalizeStreamNode(newNode, { projectId })],
            }),
          }));
          scheduleSilentGraphRefresh();
        } catch { /* ignore parse errors */ }
      });

      eventSource.addEventListener("memory_promoted", (event) => {
        try {
          const { id } = JSON.parse(event.data);
          setData((prev) => ({
            ...augmentGraphDataWithCategoryBranches({
              ...prev,
              nodes: prev.nodes.map((n) =>
                n.id === id
                  ? { ...n, type: "permanent" as const, updated_at: new Date().toISOString() }
                  : n
              ),
            }),
          }));
          scheduleSilentGraphRefresh();
        } catch { /* ignore parse errors */ }
      });

      eventSource.addEventListener("graph_changed", () => {
        scheduleSilentGraphRefresh(80);
      });

      eventSource.onerror = () => {
        // Close on error and don't auto-reconnect (avoids 401 spam)
        eventSource?.close();
        eventSource = null;
        // Retry after 30 seconds (in case auth was restored)
        retryTimeout = setTimeout(connect, 30000);
      };
    }

    connect();

    return () => {
      eventSource?.close();
      clearTimeout(retryTimeout);
    };
  }, [conversationId, loading, projectId, scheduleSilentGraphRefresh]);

  const createMemory = async (content: string, category?: string) => {
    const node = await apiPost<MemoryNode>("/api/v1/memory", {
      project_id: projectId, content, category: category || "",
    });
    await fetchGraph();
    return node;
  };

  const updateMemory = async (id: string, updates: Partial<MemoryNode>) => {
    const currentNode = data.nodes.find((node) => node.id === id) || null;
    const contentChanged =
      typeof updates.content === "string" && currentNode && updates.content !== currentNode.content;
    const categoryChanged =
      typeof updates.category === "string" && currentNode && updates.category !== currentNode.category;
    const shouldSupersede =
      currentNode !== null &&
      currentNode.type === "permanent" &&
      currentNode.node_type === "fact" &&
      currentNode.node_status !== "superseded" &&
      (contentChanged || categoryChanged);

    if (shouldSupersede && currentNode) {
      await apiPost<MemoryNode>(`/api/v1/memory/${id}/supersede`, {
        content: typeof updates.content === "string" ? updates.content : currentNode.content,
        category: typeof updates.category === "string" ? updates.category : currentNode.category,
        reason: "manual_edit",
      });
    } else {
      await apiPatch<MemoryNode>(`/api/v1/memory/${id}`, updates);
    }
    await fetchGraph();
  };

  const deleteMemory = async (id: string) => {
    await apiDelete(`/api/v1/memory/${id}`);
    await fetchGraph();
  };

  const promoteMemory = async (id: string) => {
    await apiPost<MemoryNode>(`/api/v1/memory/${id}/promote`);
    await fetchGraph();
  };

  const createEdge = async (sourceId: string, targetId: string) => {
    await apiPost<MemoryEdge>("/api/v1/memory/edges", {
      source_memory_id: sourceId, target_memory_id: targetId,
    });
    await fetchGraph();
  };

  const deleteEdge = async (id: string) => {
    await apiDelete(`/api/v1/memory/edges/${id}`);
    await fetchGraph();
  };

  const attachFileToMemory = async (memoryId: string, dataItemId: string) => {
    const file = await apiPost<MemoryFileAttachment>(`/api/v1/memory/${memoryId}/files`, {
      data_item_id: dataItemId,
    });
    await fetchGraph();
    return file;
  };

  const detachFileFromMemory = async (memoryFileId: string) => {
    await apiDelete(`/api/v1/memory/files/${memoryFileId}`);
    await fetchGraph();
  };

  return {
    data, loading, refetch: fetchGraph,
    createMemory, updateMemory, deleteMemory, promoteMemory,
    createEdge, deleteEdge,
    attachFileToMemory, detachFileFromMemory,
  };
}
