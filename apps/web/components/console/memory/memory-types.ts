import type { MemoryNode, MemoryKind, MemoryMetadataJson } from "@/hooks/useGraphData";
import {
  isPinnedMemoryNode,
  isSummaryMemoryNode,
  isSubjectMemoryNode,
  getMemoryKind,
  getMemoryCategoryLabel,
  getGraphNodeDisplayType,
  isSyntheticGraphNode,
  isStructureMemoryNode,
  isMemoryStale,
  isConflictMemoryNode,
} from "@/hooks/useGraphData";

// Re-export types for convenience
export type { MemoryNode, MemoryKind, MemoryMetadataJson };

// ---------------------------------------------------------------------------
// 1. View mode
// ---------------------------------------------------------------------------
export type MemoryViewMode =
  | "cards"
  | "list"
  | "graph"
  | "3d"
  | "views"
  | "evidence"
  | "learning"
  | "health";

// ---------------------------------------------------------------------------
// 2. Smart folder definition
// ---------------------------------------------------------------------------
export interface SmartFolder {
  id: string;
  labelKey: string; // translation key
  icon: string; // icon name for MemoryIcon component
  filter: (node: MemoryNode) => boolean;
}

// ---------------------------------------------------------------------------
// 3. Category definition
// ---------------------------------------------------------------------------
export interface CategoryDef {
  kind: MemoryKind;
  labelKey: string;
  icon: string;
}

// ---------------------------------------------------------------------------
// 4. Sidebar selection state
// ---------------------------------------------------------------------------
export interface SidebarSelection {
  type: "folder" | "category" | "subject";
  id: string;
}

// ---------------------------------------------------------------------------
// 5. Filter pill type
// ---------------------------------------------------------------------------
export type FilterPill =
  | "all"
  | "permanent"
  | "temporary"
  | "pinned"
  | "summary"
  | "profile"
  | "episodic"
  | "playbook"
  | "stale"
  | "conflict";

export type MemoryDetailTab =
  | "evidence"
  | "views"
  | "timeline"
  | "history"
  | "learning";

// ---------------------------------------------------------------------------
// 6. Page state
// ---------------------------------------------------------------------------
export interface MemoryPageState {
  view: MemoryViewMode;
  sidebar: SidebarSelection;
  filter: FilterPill;
  search: string;
  selectedId: string | null;
  detailOpen: boolean;
  detailTab: MemoryDetailTab;
}

// ---------------------------------------------------------------------------
// 7. Initial state constant
// ---------------------------------------------------------------------------
export const INITIAL_PAGE_STATE: MemoryPageState = {
  view: "cards",
  sidebar: { type: "folder", id: "all" },
  filter: "all",
  search: "",
  selectedId: null,
  detailOpen: false,
  detailTab: "evidence",
};

// ---------------------------------------------------------------------------
// 8. Smart folders
// ---------------------------------------------------------------------------
export const SMART_FOLDERS: SmartFolder[] = [
  {
    id: "all",
    labelKey: "memory.folderAll",
    icon: "circle",
    filter: () => true,
  },
  {
    id: "core",
    labelKey: "memory.folderCore",
    icon: "star",
    filter: (node) => isPinnedMemoryNode(node),
  },
  {
    id: "temporary",
    labelKey: "memory.folderTemporary",
    icon: "clock",
    filter: (node) => node.type === "temporary",
  },
  {
    id: "recent",
    labelKey: "memory.folderRecent",
    icon: "pencil",
    filter: () => true, // sorted by updated_at in component
  },
];

// ---------------------------------------------------------------------------
// 9. Categories
// ---------------------------------------------------------------------------
export const CATEGORIES: CategoryDef[] = [
  { kind: "profile", labelKey: "memory.catProfile", icon: "person" },
  { kind: "preference", labelKey: "memory.catPreference", icon: "heart" },
  { kind: "goal", labelKey: "memory.catGoal", icon: "target" },
  { kind: "fact", labelKey: "memory.catKnowledge", icon: "book" },
  { kind: "episodic", labelKey: "memory.catEpisodic", icon: "bubble" },
];

// ---------------------------------------------------------------------------
// 10. Filter functions
// ---------------------------------------------------------------------------

/**
 * Returns only displayable memory nodes.
 * Excludes center nodes, file nodes, synthetic graph nodes, and structural-only nodes.
 */
export function getDisplayNodes(nodes: MemoryNode[]): MemoryNode[] {
  return nodes.filter((node) => {
    const displayType = getGraphNodeDisplayType(node);
    if (displayType !== "memory") return false;
    if (isSyntheticGraphNode(node)) return false;
    if (isStructureMemoryNode(node)) return false;
    return true;
  });
}

/**
 * Filters memory nodes by sidebar selection, filter pill, and search query.
 *
 * For the "recent" smart folder the result is sorted by `updated_at` descending
 * and limited to the 50 most-recent nodes.
 */
export function filterNodes(
  nodes: MemoryNode[],
  sidebar: SidebarSelection,
  filter: FilterPill,
  search: string,
): MemoryNode[] {
  let result = getDisplayNodes(nodes);

  // --- sidebar selection ---------------------------------------------------
  if (sidebar.type === "folder") {
    const folder = SMART_FOLDERS.find((f) => f.id === sidebar.id);
    if (folder) {
      result = result.filter(folder.filter);
      if (sidebar.id === "recent") {
        result = [...result]
          .sort(
            (a, b) =>
              new Date(b.updated_at).getTime() -
              new Date(a.updated_at).getTime(),
          )
          .slice(0, 50);
      }
    }
  } else if (sidebar.type === "category") {
    result = result.filter((node) => getMemoryKind(node) === sidebar.id);
  } else if (sidebar.type === "subject") {
    result = result.filter(
      (node) =>
        node.parent_memory_id === sidebar.id ||
        node.metadata_json?.subject_memory_id === sidebar.id,
    );
  }

  // --- filter pill ---------------------------------------------------------
  if (filter === "permanent")
    result = result.filter((n) => n.type === "permanent");
  else if (filter === "temporary")
    result = result.filter((n) => n.type === "temporary");
  else if (filter === "pinned")
    result = result.filter((n) => isPinnedMemoryNode(n));
  else if (filter === "summary")
    result = result.filter((n) => isSummaryMemoryNode(n));
  else if (filter === "profile")
    result = result.filter((n) => getMemoryKind(n) === "profile");
  else if (filter === "episodic")
    result = result.filter((n) => getMemoryKind(n) === "episodic");
  else if (filter === "playbook")
    result = result.filter((n) =>
      /(步骤|流程|方法|先.+再.+|如何|怎么做|解决|排查|复盘|^\d+\.)/.test(
        `${n.category}\n${n.content}`,
      ),
    );
  else if (filter === "stale")
    result = result.filter((n) => isMemoryStale(n));
  else if (filter === "conflict")
    result = result.filter((n) => isConflictMemoryNode(n));

  // --- search --------------------------------------------------------------
  if (search.trim()) {
    const q = search.trim().toLowerCase();
    result = result.filter(
      (n) =>
        n.content.toLowerCase().includes(q) ||
        n.category.toLowerCase().includes(q) ||
        (getMemoryCategoryLabel(n) || "").toLowerCase().includes(q),
    );
  }

  return result;
}

// ---------------------------------------------------------------------------
// 11. Count helpers
// ---------------------------------------------------------------------------

export function countByFolder(nodes: MemoryNode[], folderId: string): number {
  const displayNodes = getDisplayNodes(nodes);
  const folder = SMART_FOLDERS.find((f) => f.id === folderId);
  if (!folder) return 0;
  if (folderId === "recent") return Math.min(displayNodes.length, 50);
  return displayNodes.filter(folder.filter).length;
}

export function countByKind(nodes: MemoryNode[], kind: MemoryKind): number {
  return getDisplayNodes(nodes).filter((n) => getMemoryKind(n) === kind).length;
}

export function countBySubject(
  nodes: MemoryNode[],
  subjectId: string,
): number {
  return getDisplayNodes(nodes).filter(
    (n) =>
      n.parent_memory_id === subjectId ||
      n.metadata_json?.subject_memory_id === subjectId,
  ).length;
}

// ---------------------------------------------------------------------------
// 12. Extract subject nodes
// ---------------------------------------------------------------------------

export function extractSubjects(nodes: MemoryNode[]): MemoryNode[] {
  return nodes.filter(
    (n) => isSubjectMemoryNode(n) && !isSyntheticGraphNode(n),
  );
}
