"use client";

import { type CSSProperties, useDeferredValue, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  type MemoryNode,
  getMemoryCategoryLabel,
  getMemoryCategorySegments,
  getMemoryKind,
  getMemoryLastUsedAt,
  getMemoryLastUsedSource,
  getMemoryNodeRole,
  getMemoryParentBinding,
  getMemoryPrimaryParentId,
  getMemoryRetrievalCount,
  getMemorySalience,
  getSummarySourceCount,
  isAssistantRootMemoryNode,
  isFileMemoryNode,
  isPinnedMemoryNode,
  isStructureMemoryNode,
  isSubjectMemoryNode,
  isSummaryMemoryNode,
} from "@/hooks/useGraphData";
import { formatRelativeTime } from "@/lib/format-time";
import {
  dedupeDisplayLabels,
  formatLocalizedCategorySegmentLabel,
  formatLocalizedMemoryKindLabel,
  formatLocalizedSubjectKindLabel,
} from "@/lib/memory-labels";

interface MemoryListViewProps {
  nodes: MemoryNode[];
  onUpdateMemory: (id: string, updates: Partial<MemoryNode>) => Promise<void>;
  onDeleteMemory: (id: string) => Promise<void>;
}

type FilterKey =
  | "all"
  | "profile"
  | "preference"
  | "goal"
  | "summary"
  | "temporary";

type Selection =
  | { type: "node"; id: string }
  | { type: "branch"; id: string }
  | null;

interface TreeBranchDraft {
  id: string;
  label: string;
  segments: string[];
  depth: number;
  children: Map<string, TreeBranchDraft>;
  leaves: MemoryNode[];
}

interface TreeBranch {
  id: string;
  label: string;
  segments: string[];
  depth: number;
  children: TreeBranch[];
  leaves: MemoryNode[];
  descendantCount: number;
  summaryCount: number;
  temporaryCount: number;
  retrievalCount: number;
  latestActivityAt: number;
  previewNodes: MemoryNode[];
}

type TreeEntry =
  | { type: "branch"; branch: TreeBranch; expanded: boolean }
  | { type: "leaf"; node: MemoryNode; depth: number };

function getTypeClass(node: MemoryNode): string {
  const role = getMemoryNodeRole(node);
  if (role === "summary") return "summary";
  if (role === "structure") return "pinned";
  if (role === "subject") return "subject";
  if (role === "concept") return "concept";
  if (isPinnedMemoryNode(node)) return "pinned";
  if (node.type === "permanent") return "permanent";
  return "temporary";
}

function getMemoryRoleLabel(
  role: ReturnType<typeof getMemoryNodeRole>,
  t: (key: string) => string,
): string {
  const labels: Record<NonNullable<ReturnType<typeof getMemoryNodeRole>>, string> = {
    fact: t("memory.roleFact"),
    structure: t("memory.roleStructure"),
    subject: t("memory.roleSubject"),
    concept: t("memory.roleConcept"),
    summary: t("memory.roleSummary"),
  };
  if (!role) {
    return t("memory.roleFact");
  }
  return labels[role];
}

function getMemoryKindLabel(
  kind: string | null,
  t: (key: string) => string,
): string {
  return formatLocalizedMemoryKindLabel(kind, t, "memory");
}

function getNodeActivityAt(node: MemoryNode): number {
  const timestamp =
    getMemoryLastUsedAt(node) || node.updated_at || node.created_at;
  return new Date(timestamp).getTime();
}

function sortMemoryNodes(left: MemoryNode, right: MemoryNode): number {
  return (
    getNodeActivityAt(right) - getNodeActivityAt(left) ||
    getMemoryRetrievalCount(right) - getMemoryRetrievalCount(left) ||
    new Date(right.updated_at).getTime() -
      new Date(left.updated_at).getTime() ||
    right.content.localeCompare(left.content)
  );
}

function createBranchDraft(
  label: string,
  segments: string[],
  depth: number,
): TreeBranchDraft {
  return {
    id: segments.join("::"),
    label,
    segments,
    depth,
    children: new Map<string, TreeBranchDraft>(),
    leaves: [],
  };
}

function finalizeBranch(draft: TreeBranchDraft): TreeBranch {
  const leaves = [...draft.leaves].sort(sortMemoryNodes);
  const children = [...draft.children.values()].map(finalizeBranch);

  let descendantCount = leaves.length;
  let summaryCount = leaves.filter((node) => isSummaryMemoryNode(node)).length;
  let temporaryCount = leaves.filter(
    (node) => node.type === "temporary",
  ).length;
  let retrievalCount = leaves.reduce(
    (sum, node) => sum + getMemoryRetrievalCount(node),
    0,
  );
  let latestActivityAt = leaves[0] ? getNodeActivityAt(leaves[0]) : 0;
  const previewNodes = [...leaves];

  children.forEach((child) => {
    descendantCount += child.descendantCount;
    summaryCount += child.summaryCount;
    temporaryCount += child.temporaryCount;
    retrievalCount += child.retrievalCount;
    latestActivityAt = Math.max(latestActivityAt, child.latestActivityAt);
    previewNodes.push(...child.previewNodes);
  });

  children.sort(
    (left, right) =>
      right.latestActivityAt - left.latestActivityAt ||
      right.descendantCount - left.descendantCount ||
      left.label.localeCompare(right.label),
  );

  return {
    id: draft.id,
    label: draft.label,
    segments: draft.segments,
    depth: draft.depth,
    children,
    leaves,
    descendantCount,
    summaryCount,
    temporaryCount,
    retrievalCount,
    latestActivityAt,
    previewNodes: [
      ...new Map(
        previewNodes.sort(sortMemoryNodes).map((node) => [node.id, node]),
      ).values(),
    ].slice(0, 6),
  };
}

function buildTree(
  nodes: MemoryNode[],
  nodeMap: Map<string, MemoryNode>,
  uncategorizedLabel: string,
  formatSegmentLabel: (segment: string) => string,
): TreeBranch[] {
  const root = createBranchDraft("root", [], -1);

  nodes.forEach((node) => {
    const segments = getHierarchySegments(node, nodeMap, uncategorizedLabel);
    const normalizedSegments =
      segments.length > 0 ? segments : [uncategorizedLabel];
    let current = root;

    normalizedSegments.forEach((segment, index) => {
      const nextSegments = normalizedSegments.slice(0, index + 1);
      const id = nextSegments.join("::");
      let branch = current.children.get(id);
      if (!branch) {
        branch = createBranchDraft(formatSegmentLabel(segment), nextSegments, index);
        current.children.set(id, branch);
      }
      current = branch;
    });

    current.leaves.push(node);
  });

  return [...root.children.values()]
    .map(finalizeBranch)
    .sort(
      (left, right) =>
        right.latestActivityAt - left.latestActivityAt ||
        right.descendantCount - left.descendantCount ||
        left.label.localeCompare(right.label),
    );
}

function flattenTree(
  branches: TreeBranch[],
  collapsedBranches: Set<string>,
  forceExpanded: boolean,
): TreeEntry[] {
  const entries: TreeEntry[] = [];

  const visit = (branch: TreeBranch) => {
    const expanded = forceExpanded || !collapsedBranches.has(branch.id);
    entries.push({ type: "branch", branch, expanded });
    if (!expanded) return;

    branch.children.forEach(visit);
    branch.leaves.forEach((node) => {
      entries.push({
        type: "leaf",
        node,
        depth: branch.depth + 1,
      });
    });
  };

  branches.forEach(visit);
  return entries;
}

function getBranchPathLabel(
  branch: TreeBranch,
  formatSegmentLabel: (segment: string) => string,
): string {
  return branch.segments.map((segment) => formatSegmentLabel(segment)).join(" / ");
}

function getBranchIdFromNode(
  node: MemoryNode,
  nodeMap: Map<string, MemoryNode>,
  uncategorizedLabel: string,
): string {
  const segments = getHierarchySegments(node, nodeMap, uncategorizedLabel);
  return (segments.length > 0 ? segments : [uncategorizedLabel]).join("::");
}

function compactPathLabel(
  node: MemoryNode,
  nodeMap: Map<string, MemoryNode>,
  uncategorizedLabel: string,
  formatSegmentLabel: (segment: string) => string,
): string {
  const segments = getHierarchySegments(node, nodeMap, uncategorizedLabel);
  if (segments.length === 0) {
    return uncategorizedLabel;
  }
  return segments.map((segment) => formatSegmentLabel(segment)).join(" / ");
}

function getHierarchySegments(
  node: MemoryNode,
  nodeMap: Map<string, MemoryNode>,
  uncategorizedLabel: string,
): string[] {
  const segments: string[] = [];
  let parentId = getMemoryPrimaryParentId(node);
  const seen = new Set<string>();

  while (parentId && !seen.has(parentId)) {
    seen.add(parentId);
    const parent = nodeMap.get(parentId);
    if (!parent || isAssistantRootMemoryNode(parent) || isFileMemoryNode(parent)) {
      break;
    }
    if (isStructureMemoryNode(parent)) {
      const label = parent.content.trim() || getMemoryCategoryLabel(parent) || parent.id.slice(0, 8);
      if (label) {
        segments.unshift(label);
      }
    }
    parentId = getMemoryPrimaryParentId(parent);
  }

  if (segments.length > 0) {
    return segments;
  }

  const categorySegments = getMemoryCategorySegments(node);
  return categorySegments.length > 0 ? categorySegments : [uncategorizedLabel];
}

export default function MemoryListView({
  nodes,
  onUpdateMemory,
  onDeleteMemory,
}: MemoryListViewProps) {
  const t = useTranslations("console");
  const uncategorizedLabel = t("memory.uncategorized");
  const formatCategorySegmentLabel = useMemo(
    () => (segment: string) => formatLocalizedCategorySegmentLabel(segment, t, "memory"),
    [t],
  );
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [activeFilter, setActiveFilter] = useState<FilterKey>("all");
  const [selection, setSelection] = useState<Selection>(null);
  const [editingContent, setEditingContent] = useState<string | null>(null);
  const [collapsedBranches, setCollapsedBranches] = useState<Set<string>>(
    new Set(),
  );

  const navigableNodes = useMemo(
    () =>
      nodes.filter(
        (node) => !isFileMemoryNode(node) && !isAssistantRootMemoryNode(node),
      ),
    [nodes],
  );

  const memoryNodes = useMemo(
    () => navigableNodes.filter((node) => !isStructureMemoryNode(node)),
    [navigableNodes],
  );

  const nodeMap = useMemo(
    () => new Map(navigableNodes.map((node) => [node.id, node])),
    [navigableNodes],
  );

  const filteredNodes = useMemo(() => {
    let result = memoryNodes;

    if (activeFilter !== "all") {
      result = result.filter((node) => {
        if (activeFilter === "temporary") {
          return node.type === "temporary";
        }
        if (activeFilter === "summary") {
          return isSummaryMemoryNode(node);
        }
        return getMemoryKind(node) === activeFilter;
      });
    }

    if (deferredSearch.trim()) {
      const query = deferredSearch.trim().toLowerCase();
      result = result.filter(
        (node) =>
          node.content.toLowerCase().includes(query) ||
          node.category.toLowerCase().includes(query),
      );
    }

    return [...result].sort(sortMemoryNodes);
  }, [memoryNodes, activeFilter, deferredSearch]);

  const tree = useMemo(
    () => buildTree(filteredNodes, nodeMap, uncategorizedLabel, formatCategorySegmentLabel),
    [filteredNodes, formatCategorySegmentLabel, nodeMap, uncategorizedLabel],
  );

  const branchMap = useMemo(() => {
    const map = new Map<string, TreeBranch>();
    const walk = (items: TreeBranch[]) => {
      items.forEach((branch) => {
        map.set(branch.id, branch);
        walk(branch.children);
      });
    };
    walk(tree);
    return map;
  }, [tree]);

  const visibleEntries = useMemo(
    () =>
      flattenTree(tree, collapsedBranches, deferredSearch.trim().length > 0),
    [tree, collapsedBranches, deferredSearch],
  );

  const visibleBranchCount = branchMap.size;
  const summaryCount = filteredNodes.filter((node) =>
    isSummaryMemoryNode(node),
  ).length;
  const temporaryCount = filteredNodes.filter(
    (node) => node.type === "temporary",
  ).length;
  const activeCount = filteredNodes.filter(
    (node) => getMemoryRetrievalCount(node) > 0,
  ).length;

  const selectedNode =
    selection?.type === "node"
      ? filteredNodes.find((node) => node.id === selection.id) || null
      : null;
  const explicitlySelectedBranch =
    selection?.type === "branch" ? branchMap.get(selection.id) || null : null;
  const fallbackBranch =
    !selectedNode && selection === null
      ? visibleEntries.find(
          (entry): entry is Extract<TreeEntry, { type: "branch" }> =>
            entry.type === "branch",
        )?.branch || null
      : null;
  const selectedBranch = selectedNode
    ? null
    : explicitlySelectedBranch || fallbackBranch;

  const selectedNodeBranch = selectedNode
    ? branchMap.get(getBranchIdFromNode(selectedNode, nodeMap, uncategorizedLabel)) ||
      null
    : null;
  const selectedNodeParent = selectedNode
    ? (getMemoryPrimaryParentId(selectedNode)
        ? nodeMap.get(getMemoryPrimaryParentId(selectedNode) as string) || null
        : null)
    : null;
  const selectedSubjectNode = selectedNode
    ? isSubjectMemoryNode(selectedNode)
      ? selectedNode
      : (selectedNode.subject_memory_id
          ? nodeMap.get(selectedNode.subject_memory_id) || null
          : null)
    : null;
  const selectedNodeChildren = selectedNode
    ? memoryNodes
        .filter((node) => getMemoryPrimaryParentId(node) === selectedNode.id)
        .sort(sortMemoryNodes)
    : [];
  const branchContextNodes = selectedNodeBranch
    ? selectedNodeBranch.previewNodes
        .filter((node) => node.id !== selectedNode?.id)
        .slice(0, 5)
    : [];

  const selectedKind = selectedNode ? getMemoryKind(selectedNode) : null;
  const selectedRole = selectedNode ? getMemoryNodeRole(selectedNode) : null;
  const selectedRetrievalCount = selectedNode
    ? getMemoryRetrievalCount(selectedNode)
    : 0;
  const selectedLastUsedAt = selectedNode
    ? getMemoryLastUsedAt(selectedNode)
    : null;
  const selectedLastUsedSource = selectedNode
    ? getMemoryLastUsedSource(selectedNode)
    : null;
  const selectedSalience = selectedNode
    ? getMemorySalience(selectedNode)
    : null;
  const selectedSummaryCount = selectedNode
    ? getSummarySourceCount(selectedNode)
    : 0;
  const selectedSubjectKindLabel = selectedNode
    ? formatLocalizedSubjectKindLabel(selectedNode.subject_kind, t, "memory")
    : "";
  const selectedNodeBadges = !selectedNode
    ? []
    : dedupeDisplayLabels([
        {
          label:
            selectedNode.type === "permanent"
              ? t("memory.permanentLabel")
              : t("memory.temporaryLabel"),
          className: "memory-detail-type-badge",
        },
        {
          label: getMemoryRoleLabel(selectedRole, t),
          className: "memory-detail-type-badge",
        },
        ...(selectedSubjectKindLabel
          ? [{ label: selectedSubjectKindLabel, className: "memory-detail-type-badge" }]
          : []),
        ...(selectedRole !== "summary"
          ? [{ label: getMemoryKindLabel(selectedKind, t), className: "memory-detail-type-badge" }]
          : []),
        ...(isSummaryMemoryNode(selectedNode)
          ? [{ label: t("memory.summaryBadge"), className: "memory-detail-type-badge is-summary" }]
          : []),
        ...(isPinnedMemoryNode(selectedNode)
          ? [{ label: t("memory.pinnedBadge"), className: "memory-detail-type-badge is-pinned" }]
          : []),
      ]);

  const filters: { key: FilterKey; labelKey: string }[] = [
    { key: "all", labelKey: "memory.filterAll" },
    { key: "profile", labelKey: "memory.filterProfile" },
    { key: "preference", labelKey: "memory.filterPreference" },
    { key: "goal", labelKey: "memory.filterGoal" },
    { key: "summary", labelKey: "memory.filterSummary" },
    { key: "temporary", labelKey: "memory.filterTemporary" },
  ];

  const handleSave = async () => {
    if (!selectedNode || editingContent === null) return;
    await onUpdateMemory(selectedNode.id, { content: editingContent });
    setEditingContent(null);
  };

  const handleDelete = async () => {
    if (!selectedNode) return;
    await onDeleteMemory(selectedNode.id);
    setSelection(null);
    setEditingContent(null);
  };

  const handleToggleBranch = (branchId: string) => {
    setCollapsedBranches((current) => {
      const next = new Set(current);
      if (next.has(branchId)) {
        next.delete(branchId);
      } else {
        next.add(branchId);
      }
      return next;
    });
  };

  const handleSelectNode = (node: MemoryNode) => {
    setSelection({ type: "node", id: node.id });
    setEditingContent(null);
  };

  const handleSelectBranch = (branch: TreeBranch) => {
    setSelection({ type: "branch", id: branch.id });
    setEditingContent(null);
  };

  const handleSelectStructuralTarget = (node: MemoryNode | null) => {
    if (!node) {
      return;
    }
    if (isStructureMemoryNode(node)) {
      const branchId = getBranchIdFromNode(node, nodeMap, uncategorizedLabel);
      const branch = branchMap.get(branchId);
      if (branch) {
        handleSelectBranch(branch);
      }
      return;
    }
    handleSelectNode(node);
  };

  return (
    <div className="memory-list-layout">
      <section className="memory-list-pane memory-list-pane--browser">
        <div className="memory-list-browser-toolbar">
          <div className="memory-list-search">
            <input
              type="text"
              aria-label={t("memory.searchPlaceholder")}
              placeholder={t("memory.searchPlaceholder")}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
          <div
            className="memory-list-browser-summary"
            aria-label={t("memory.listTreeTitle")}
          >
            <span className="memory-list-browser-pill">
              {filteredNodes.length}
              {t("memory.countUnit")}
            </span>
            <span className="memory-list-browser-pill">
              {t("memory.metricBranches")} {visibleBranchCount}
            </span>
          </div>
        </div>

        <div className="memory-list-filters">
          {filters.map((filter) => (
            <button
              key={filter.key}
              type="button"
              className={`memory-list-filter${activeFilter === filter.key ? " active" : ""}`}
              onClick={() => setActiveFilter(filter.key)}
            >
              {t(filter.labelKey)}
            </button>
          ))}
        </div>

        <div className="memory-list-browser-overview">
          <div className="memory-list-overview-header">
            <span className="memory-list-overline">
              {t("memory.listTreeTitle")}
            </span>
            <span className="memory-list-overview-value">
              {filteredNodes.length}
              {t("memory.countUnit")}
            </span>
          </div>
          <div className="memory-list-overview-strip">
            <span>
              {t("memory.metricSummary")} {summaryCount}
            </span>
            <span>
              {t("memory.filterTemporary")} {temporaryCount}
            </span>
            <span>
              {t("memory.metricActive")} {activeCount}
            </span>
          </div>
        </div>

        <div
          className="memory-list-items"
          role="tree"
          aria-label={t("memory.listTreeTitle")}
        >
          {visibleEntries.length === 0 ? (
            <div className="memory-list-empty">{t("memory.noResults")}</div>
          ) : (
            visibleEntries.map((entry) => {
              if (entry.type === "branch") {
                const isActive = selectedBranch?.id === entry.branch.id;
                const branchStyle = {
                  "--tree-depth": entry.branch.depth,
                } as CSSProperties;
                return (
                  <div
                    key={entry.branch.id}
                    className={`memory-tree-branch${isActive ? " is-active" : ""}`}
                    style={branchStyle}
                  >
                    <button
                      type="button"
                      className={`memory-tree-chevron${entry.expanded ? " is-open" : ""}`}
                      onClick={() => handleToggleBranch(entry.branch.id)}
                      aria-label={
                        entry.expanded ? "Collapse branch" : "Expand branch"
                      }
                    >
                      <svg
                        viewBox="0 0 20 20"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.7"
                      >
                        <path d="m7 4 6 6-6 6" />
                      </svg>
                    </button>
                    <button
                      type="button"
                      className={`memory-tree-row memory-tree-row--branch${isActive ? " active" : ""}`}
                      onClick={() => handleSelectBranch(entry.branch)}
                    >
                      <span className="memory-tree-branch-label">
                        {entry.branch.label}
                      </span>
                      <span className="memory-tree-branch-meta">
                        {entry.branch.latestActivityAt > 0
                          ? formatRelativeTime(
                              new Date(
                                entry.branch.latestActivityAt,
                              ).toISOString(),
                              t,
                            )
                          : ""}
                      </span>
                      <span className="memory-tree-branch-count">
                        {entry.branch.descendantCount}
                      </span>
                    </button>
                  </div>
                );
              }

              const node = entry.node;
              const kind = getMemoryKind(node);
              const nodeStyle = {
                "--tree-depth": entry.depth,
              } as CSSProperties;
              const isActive = selectedNode?.id === node.id;
              const lastActiveAt = getMemoryLastUsedAt(node) || node.updated_at;

              return (
                <button
                  key={node.id}
                  type="button"
                  className={`memory-list-item memory-tree-row memory-tree-row--leaf${isActive ? " active" : ""}`}
                  style={nodeStyle}
                  onClick={() => handleSelectNode(node)}
                >
                  <div className="memory-tree-leaf-line">
                    <span className={`memory-type-dot ${getTypeClass(node)}`} />
                    <span className="memory-tree-leaf-title">
                      {node.content}
                    </span>
                    {isPinnedMemoryNode(node) ? (
                      <span className="memory-list-chip is-pinned">
                        {t("memory.pinnedBadge")}
                      </span>
                    ) : null}
                    {isSummaryMemoryNode(node) ? (
                      <span className="memory-list-chip is-summary">
                        {t("memory.summaryBadge")}
                      </span>
                    ) : null}
                    {getMemoryRetrievalCount(node) > 0 ? (
                      <span className="memory-tree-leaf-count">
                        {getMemoryRetrievalCount(node)}
                      </span>
                    ) : null}
                  </div>
                  <div className="memory-tree-leaf-meta">
                    <span>{getMemoryKindLabel(kind, t)}</span>
                    <span>
                      {node.type === "permanent"
                        ? t("memory.permanentLabel")
                        : t("memory.temporaryLabel")}
                    </span>
                    <span>{formatRelativeTime(lastActiveAt, t)}</span>
                  </div>
                </button>
              );
            })
          )}
        </div>
      </section>

      <section className="memory-list-pane memory-list-pane--focus">
        {!selectedNode && !selectedBranch ? (
          <div className="memory-detail-empty">{t("memory.selectToView")}</div>
        ) : selectedBranch ? (
          <div className="memory-focus-layout">
            <header className="memory-focus-header">
              <span className="memory-list-overline">
                {t("memory.listSelectedBranch")}
              </span>
              <h2 className="memory-focus-title">{selectedBranch.label}</h2>
              <div className="memory-focus-meta">
                <span>{getBranchPathLabel(selectedBranch, formatCategorySegmentLabel)}</span>
                {selectedBranch.latestActivityAt > 0 ? (
                  <span>
                    {t("memory.lastUsed")}{" "}
                    {formatRelativeTime(
                      new Date(selectedBranch.latestActivityAt).toISOString(),
                      t,
                    )}
                  </span>
                ) : null}
              </div>
              <div className="memory-focus-badges">
                {selectedBranch.segments.map((segment) => (
                  <span key={segment} className="memory-detail-type-badge">
                    {formatCategorySegmentLabel(segment)}
                  </span>
                ))}
              </div>
            </header>

            <div className="memory-focus-stat-row">
              <div className="memory-focus-stat">
                <span>{t("memory.metricTotal")}</span>
                <strong>{selectedBranch.descendantCount}</strong>
              </div>
              <div className="memory-focus-stat">
                <span>{t("memory.metricSummary")}</span>
                <strong>{selectedBranch.summaryCount}</strong>
              </div>
              <div className="memory-focus-stat">
                <span>{t("memory.filterTemporary")}</span>
                <strong>{selectedBranch.temporaryCount}</strong>
              </div>
              <div className="memory-focus-stat">
                <span>{t("memory.retrievalCount")}</span>
                <strong>{selectedBranch.retrievalCount}</strong>
              </div>
            </div>

            <div className="memory-focus-section">
              <div className="memory-focus-section-head">
                <h3>{t("memory.hotMemories")}</h3>
                <span>{selectedBranch.previewNodes.length}</span>
              </div>
              <div className="memory-focus-list">
                {selectedBranch.previewNodes.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    className="memory-focus-list-item"
                    onClick={() => handleSelectNode(node)}
                  >
                    <div className="memory-focus-list-copy">
                      <strong>{node.content}</strong>
                      <span>{getMemoryKindLabel(getMemoryKind(node), t)}</span>
                    </div>
                    <div className="memory-focus-list-meta">
                      <span>
                        {formatRelativeTime(
                          getMemoryLastUsedAt(node) || node.updated_at,
                          t,
                        )}
                      </span>
                      <span>{getMemoryRetrievalCount(node)}</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div className="memory-focus-section">
              <div className="memory-focus-section-head">
                <h3>{t("memory.listSubbranches")}</h3>
                <span>{selectedBranch.children.length}</span>
              </div>
              {selectedBranch.children.length > 0 ? (
                <div className="memory-focus-list">
                  {selectedBranch.children.map((branch) => (
                    <button
                      key={branch.id}
                      type="button"
                      className="memory-focus-list-item"
                      onClick={() => handleSelectBranch(branch)}
                    >
                      <div className="memory-focus-list-copy">
                        <strong>{branch.label}</strong>
                        <span>{getBranchPathLabel(branch, formatCategorySegmentLabel)}</span>
                      </div>
                      <div className="memory-focus-list-meta">
                        <span>{branch.descendantCount}</span>
                      </div>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="memory-focus-empty">
                  {t("memory.noResults")}
                </div>
              )}
            </div>
          </div>
        ) : selectedNode ? (
          <div className="memory-focus-layout">
            <header className="memory-focus-header">
              <span className="memory-list-overline">
                {t("memory.listSelectedMemory")}
              </span>
              <div className="memory-focus-badges">
                {selectedNodeBadges.map((badge) => (
                  <span key={`${badge.className}:${badge.label}`} className={badge.className}>
                    {badge.label}
                  </span>
                ))}
              </div>
              <div className="memory-focus-meta">
                <span>
                  {compactPathLabel(
                    selectedNode,
                    nodeMap,
                    uncategorizedLabel,
                    formatCategorySegmentLabel,
                  )}
                </span>
                {selectedSubjectNode && !isSubjectMemoryNode(selectedNode) ? (
                  <span>
                    {t("memory.listSubject")} {selectedSubjectNode.content}
                  </span>
                ) : null}
                <span>
                  {t("memory.created")}{" "}
                  {formatRelativeTime(selectedNode.created_at, t)}
                </span>
                <span>
                  {t("memory.updated")}{" "}
                  {formatRelativeTime(selectedNode.updated_at, t)}
                </span>
              </div>
            </header>

            <div className="memory-focus-article">
              {editingContent !== null ? (
                <textarea
                  className="memory-detail-edit-textarea"
                  value={editingContent}
                  onChange={(event) => setEditingContent(event.target.value)}
                  rows={10}
                />
              ) : (
                <div className="memory-detail-text">{selectedNode.content}</div>
              )}
            </div>

            {selectedLastUsedSource ? (
              <div className="memory-detail-note">
                {t("memory.lastUsedSourceLabel")}: {selectedLastUsedSource}
              </div>
            ) : null}

            {isSummaryMemoryNode(selectedNode) ? (
              <div className="memory-detail-note is-summary">
                {t("memory.summarySourceCount", {
                  count: selectedSummaryCount,
                })}
              </div>
            ) : null}

            <div className="memory-focus-section">
              <div className="memory-focus-section-head">
                <h3>{t("memory.listBranchContext")}</h3>
                <span>{branchContextNodes.length}</span>
              </div>
              {branchContextNodes.length > 0 ? (
                <div className="memory-focus-list">
                  {branchContextNodes.map((node) => (
                    <button
                      key={node.id}
                      type="button"
                      className="memory-focus-list-item"
                      onClick={() => handleSelectNode(node)}
                    >
                      <div className="memory-focus-list-copy">
                        <strong>{node.content}</strong>
                        <span>
                          {getMemoryKindLabel(getMemoryKind(node), t)}
                        </span>
                      </div>
                      <div className="memory-focus-list-meta">
                        <span>
                          {formatRelativeTime(
                            getMemoryLastUsedAt(node) || node.updated_at,
                            t,
                          )}
                        </span>
                        <span>{getMemoryRetrievalCount(node)}</span>
                      </div>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="memory-focus-empty">
                  {t("memory.noResults")}
                </div>
              )}
            </div>

            <div className="memory-focus-section">
              <div className="memory-focus-section-head">
                <h3>{t("memory.listChildNodes")}</h3>
                <span>{selectedNodeChildren.length}</span>
              </div>
              {selectedNodeChildren.length > 0 ? (
                <div className="memory-focus-list">
                  {selectedNodeChildren.slice(0, 6).map((node) => (
                    <button
                      key={node.id}
                      type="button"
                      className="memory-focus-list-item"
                      onClick={() => handleSelectNode(node)}
                    >
                      <div className="memory-focus-list-copy">
                        <strong>{node.content}</strong>
                        <span>
                          {compactPathLabel(
                            node,
                            nodeMap,
                            uncategorizedLabel,
                            formatCategorySegmentLabel,
                          )}
                        </span>
                      </div>
                      <div className="memory-focus-list-meta">
                        <span>
                          {formatRelativeTime(
                            getMemoryLastUsedAt(node) || node.updated_at,
                            t,
                          )}
                        </span>
                      </div>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="memory-focus-empty">
                  {t("memory.listNoChildNodes")}
                </div>
              )}
            </div>
          </div>
        ) : null}
      </section>

      <aside className="memory-list-pane memory-list-pane--inspector">
        {!selectedNode && !selectedBranch ? (
          <div className="memory-detail-empty">{t("memory.selectToView")}</div>
        ) : selectedBranch ? (
          <div className="memory-inspector">
            <div className="memory-inspector-group">
              <span className="memory-list-overline">
                {t("memory.listSelectedBranch")}
              </span>
              <h3 className="memory-inspector-title">{selectedBranch.label}</h3>
            </div>

            <div className="memory-inspector-group">
              <div className="memory-inspector-row">
                <span>{t("memory.listBranchPath")}</span>
                <strong>{getBranchPathLabel(selectedBranch, formatCategorySegmentLabel)}</strong>
              </div>
              <div className="memory-inspector-row">
                <span>{t("memory.listStructureDepth")}</span>
                <strong>{selectedBranch.depth + 1}</strong>
              </div>
              <div className="memory-inspector-row">
                <span>{t("memory.metricBranches")}</span>
                <strong>{selectedBranch.children.length}</strong>
              </div>
              <div className="memory-inspector-row">
                <span>{t("memory.metricTotal")}</span>
                <strong>{selectedBranch.descendantCount}</strong>
              </div>
            </div>
          </div>
        ) : selectedNode ? (
          <div className="memory-inspector">
            <div className="memory-inspector-group">
              <span className="memory-list-overline">
                {t("memory.listSelectedMemory")}
              </span>
              <h3 className="memory-inspector-title">
                {getMemoryCategoryLabel(selectedNode) ||
                  getMemoryRoleLabel(selectedRole, t)}
              </h3>
            </div>

            <div className="memory-inspector-group">
              <div className="memory-inspector-row">
                <span>{t("memory.listNodeType")}</span>
                <strong>{getMemoryRoleLabel(selectedRole, t)}</strong>
              </div>
              <div className="memory-inspector-row">
                <span>{t("memory.listBranchPath")}</span>
                <strong>
                  {compactPathLabel(
                    selectedNode,
                    nodeMap,
                    uncategorizedLabel,
                    formatCategorySegmentLabel,
                  )}
                </strong>
              </div>
              <div className="memory-inspector-row">
                <span>{t("memory.listSubject")}</span>
                <button
                  type="button"
                  className="memory-inspector-link"
                  onClick={() =>
                    handleSelectStructuralTarget(selectedSubjectNode)
                  }
                  disabled={!selectedSubjectNode}
                >
                  {selectedSubjectNode
                    ? selectedSubjectNode.content
                    : isSubjectMemoryNode(selectedNode)
                      ? selectedNode.content
                      : t("memory.listNoSubject")}
                </button>
              </div>
              <div className="memory-inspector-row">
                <span>{t("memory.listParentNode")}</span>
                <button
                  type="button"
                  className="memory-inspector-link"
                  onClick={() =>
                    handleSelectStructuralTarget(selectedNodeParent)
                  }
                  disabled={!selectedNodeParent}
                >
                  {selectedNodeParent
                    ? getMemoryCategoryLabel(selectedNodeParent) ||
                      selectedNodeParent.content
                    : t("memory.listNoParent")}
                </button>
              </div>
              <div className="memory-inspector-row">
                <span>{t("memory.listBinding")}</span>
                <strong>
                  {getMemoryParentBinding(selectedNode) === "manual"
                    ? t("memory.listBindingManual")
                    : t("memory.listBindingAuto")}
                </strong>
              </div>
              {selectedNode.subject_kind ? (
                <div className="memory-inspector-row">
                  <span>{t("memory.listSubjectKind")}</span>
                  <strong>{selectedSubjectKindLabel}</strong>
                </div>
              ) : null}
              <div className="memory-inspector-row">
                <span>{t("memory.salience")}</span>
                <strong>
                  {selectedSalience !== null
                    ? `${Math.round(selectedSalience * 100)}%`
                    : "—"}
                </strong>
              </div>
              <div className="memory-inspector-row">
                <span>{t("memory.retrievalCount")}</span>
                <strong>{selectedRetrievalCount}</strong>
              </div>
              <div className="memory-inspector-row">
                <span>{t("memory.lastUsed")}</span>
                <strong>
                  {selectedLastUsedAt
                    ? formatRelativeTime(selectedLastUsedAt, t)
                    : "—"}
                </strong>
              </div>
              <div className="memory-inspector-row">
                <span>{t("memory.visibility")}</span>
                <strong>
                  {selectedNode.metadata_json?.visibility === "private"
                    ? t("memory.visibilityPrivate")
                    : t("memory.visibilityPublic")}
                </strong>
              </div>
              <div className="memory-inspector-row">
                <span>{t("memory.listChildNodes")}</span>
                <strong>{selectedNodeChildren.length}</strong>
              </div>
            </div>

            {selectedNode.source_conversation_id ? (
              <div className="memory-detail-source">
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
                {t("memory.fromConversation")}
              </div>
            ) : null}

            <div className="memory-detail-actions memory-detail-actions--column">
              {editingContent !== null ? (
                <>
                  <button
                    type="button"
                    className="memory-action-btn"
                    onClick={() => setEditingContent(null)}
                  >
                    {t("memory.cancel")}
                  </button>
                  <button
                    type="button"
                    className="memory-action-btn primary"
                    onClick={() => void handleSave()}
                  >
                    {t("memory.save")}
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    className="memory-action-btn"
                    onClick={() => setEditingContent(selectedNode.content)}
                  >
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                    </svg>
                    {t("memory.edit")}
                  </button>
                  <button
                    type="button"
                    className="memory-action-btn"
                    style={{ color: "#dc2626" }}
                    onClick={() => void handleDelete()}
                  >
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                    {t("memory.delete")}
                  </button>
                </>
              )}
            </div>
          </div>
        ) : null}
      </aside>
    </div>
  );
}
