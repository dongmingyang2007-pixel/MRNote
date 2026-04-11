"use client";

import { useState, useCallback, useMemo } from "react";
import { useTranslations } from "next-intl";
import { motion } from "framer-motion";
import { useProjectContext } from "@/lib/ProjectContext";
import { isOrdinaryMemoryNode, useGraphData } from "@/hooks/useGraphData";
import MemoryGraph from "@/components/console/graph/MemoryGraph";
import MemorySidebar from "@/components/console/memory/MemorySidebar";
import MemoryCardGrid from "@/components/console/memory/MemoryCardGrid";
import MemoryListTable from "@/components/console/memory/MemoryListTable";
import MemoryDetailPanel from "@/components/console/memory/MemoryDetailPanel";
import MemoryEvidencePanel from "@/components/console/memory/MemoryEvidencePanel";
import MemoryHealthPanel from "@/components/console/memory/MemoryHealthPanel";
import MemoryLearningPanel from "@/components/console/memory/MemoryLearningPanel";
import MemoryToolbar from "@/components/console/memory/MemoryToolbar";
import MemoryNewDialog from "@/components/console/memory/MemoryNewDialog";
import MemoryViewsPanel from "@/components/console/memory/MemoryViewsPanel";
import {
  type MemoryPageState,
  type MemoryDetailTab,
  INITIAL_PAGE_STATE,
  filterNodes,
} from "@/components/console/memory/memory-types";

export default function MemoryPage() {
  const t = useTranslations("console");
  const { projectId, projects } = useProjectContext();
  const {
    data,
    loading,
    createMemory,
    updateMemory,
    deleteMemory,
    promoteMemory,
    createEdge,
    deleteEdge,
    attachFileToMemory,
    detachFileFromMemory,
  } = useGraphData(projectId, { includeTemporary: true });

  // ── Unified page state ────────────────────────────────────────────────────
  const [state, setState] = useState<MemoryPageState>(INITIAL_PAGE_STATE);

  const updateState = useCallback((patch: Partial<MemoryPageState>) => {
    setState((prev) => ({ ...prev, ...patch }));
  }, []);

  // ── Computed values ───────────────────────────────────────────────────────
  const assistantName =
    projects.find((p) => p.id === projectId)?.name || t("memory.title");

  const filteredNodes = useMemo(
    () => filterNodes(data.nodes, state.sidebar, state.filter, state.search),
    [data.nodes, state.sidebar, state.filter, state.search],
  );

  const selectedNode = useMemo(
    () =>
      state.selectedId
        ? (data.nodes.find((n) => n.id === state.selectedId) ?? null)
        : null,
    [data.nodes, state.selectedId],
  );

  // ── Callbacks ─────────────────────────────────────────────────────────────
  const handleSelect = useCallback(
    (id: string, detailTab: MemoryDetailTab = "evidence") => {
      updateState({ selectedId: id, detailOpen: true, detailTab });
    },
    [updateState],
  );

  const handleCloseDetail = useCallback(() => {
    updateState({ detailOpen: false, selectedId: null, detailTab: "evidence" });
  }, [updateState]);

  const [newDialogOpen, setNewDialogOpen] = useState(false);

  const handleExport = useCallback(() => {
    const exportData = {
      memories: data.nodes.filter((n) => isOrdinaryMemoryNode(n)),
      edges: data.edges,
      exported_at: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(exportData, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `memories-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [data.nodes, data.edges]);

  const handleCreateMemory = useCallback(
    async (content: string, category: string) => {
      await createMemory(content, category);
    },
    [createMemory],
  );

  const handleUpdateMemory = useCallback(
    async (id: string, content: string, category?: string) => {
      await updateMemory(id, {
        content,
        ...(category !== undefined ? { category } : {}),
      });
    },
    [updateMemory],
  );

  const handleDeleteMemory = useCallback(
    async (id: string) => {
      await deleteMemory(id);
      updateState({ selectedId: null, detailOpen: false });
    },
    [deleteMemory, updateState],
  );

  const handlePromoteMemory = useCallback(
    async (id: string) => {
      await promoteMemory(id);
    },
    [promoteMemory],
  );

  // ── Render ────────────────────────────────────────────────────────────────
  if (!projectId) {
    return (
      <div className="mem-page">
        <div className="mem-empty-state">{t("memory.noProject")}</div>
      </div>
    );
  }

  return (
    <motion.div
      className="mem-page"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.15 }}
    >
      {/* Left sidebar */}
      <MemorySidebar
        nodes={data.nodes}
        assistantName={assistantName}
        selection={state.sidebar}
        search={state.search}
        onSelect={(selection) =>
          updateState({
            sidebar: selection,
            selectedId: null,
            detailOpen: false,
            detailTab: "evidence",
          })
        }
        onSearchChange={(search) => updateState({ search })}
      />

      {/* Main area */}
      <div className="mem-main">
        <MemoryToolbar
          title={t("memory.title")}
          count={filteredNodes.length}
          view={state.view}
          filter={state.filter}
          onViewChange={(view) => updateState({ view })}
          onFilterChange={(filter) => updateState({ filter })}
          onNewMemory={() => setNewDialogOpen(true)}
          onExport={handleExport}
        />

        <div className="mem-content">
          {loading ? (
            <div className="mem-card-grid" style={{ padding: "0 20px" }}>
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="mem-card animate-pulse" style={{ minHeight: 140 }}>
                  <div style={{ height: 12, width: "40%", borderRadius: 6, background: "rgba(128,102,255,0.1)", marginBottom: 12 }} />
                  <div style={{ height: 10, width: "80%", borderRadius: 6, background: "rgba(128,102,255,0.06)", marginBottom: 8 }} />
                  <div style={{ height: 10, width: "60%", borderRadius: 6, background: "rgba(128,102,255,0.06)" }} />
                </div>
              ))}
            </div>
          ) : state.view === "cards" ? (
            <MemoryCardGrid
              nodes={filteredNodes}
              selectedId={state.selectedId}
              onSelect={handleSelect}
            />
          ) : state.view === "list" ? (
            <MemoryListTable
              nodes={filteredNodes}
              selectedId={state.selectedId}
              onSelect={handleSelect}
            />
          ) : state.view === "views" ? (
            <MemoryViewsPanel
              projectId={projectId}
              allNodes={data.nodes}
              visibleNodes={filteredNodes}
              selectedSubjectId={state.sidebar.type === "subject" ? state.sidebar.id : null}
              search={state.search}
              onSelectMemory={handleSelect}
            />
          ) : state.view === "evidence" ? (
            <MemoryEvidencePanel
              projectId={projectId}
              allNodes={data.nodes}
              visibleNodes={filteredNodes}
              search={state.search}
              onSelectMemory={handleSelect}
            />
          ) : state.view === "learning" ? (
            <MemoryLearningPanel
              projectId={projectId}
              allNodes={data.nodes}
              visibleNodes={filteredNodes}
              search={state.search}
              onSelectMemory={handleSelect}
            />
          ) : state.view === "health" ? (
            <MemoryHealthPanel
              projectId={projectId}
              allNodes={data.nodes}
              search={state.search}
              onSelectMemory={handleSelect}
            />
          ) : (
            <div className="mem-graph-stage">
              <MemoryGraph
                nodes={data.nodes}
                edges={data.edges}
                assistantName={assistantName}
                renderMode={state.view === "3d" ? "orbit" : "workbench"}
                onNodeSelect={(node) => {
                  if (node) handleSelect(node.id);
                }}
                onCreateMemory={async (content, category) => {
                  await createMemory(content, category);
                }}
                onUpdateMemory={updateMemory}
                onDeleteMemory={deleteMemory}
                onPromoteMemory={promoteMemory}
                onCreateEdge={createEdge}
                onDeleteEdge={deleteEdge}
                onAttachFile={async (memoryId, dataItemId) => {
                  await attachFileToMemory(memoryId, dataItemId);
                }}
                onDetachFile={detachFileFromMemory}
                searchQuery={state.search}
              />
            </div>
          )}
        </div>
      </div>

      {/* Right detail panel */}
      {state.detailOpen && selectedNode && (
        <MemoryDetailPanel
          key={selectedNode.id}
          node={selectedNode}
          allNodes={data.nodes}
          edges={data.edges}
          onClose={handleCloseDetail}
          initialTab={state.detailTab}
          onUpdate={handleUpdateMemory}
          onDelete={handleDeleteMemory}
          onPromote={handlePromoteMemory}
          onSelect={handleSelect}
        />
      )}

      {/* New memory dialog */}
      <MemoryNewDialog
        open={newDialogOpen}
        onClose={() => setNewDialogOpen(false)}
        onCreate={handleCreateMemory}
      />
    </motion.div>
  );
}
