"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { useTranslations } from "next-intl";
import { useProjectContext } from "@/lib/ProjectContext";
import { useGraphData } from "@/hooks/useGraphData";
import MemoryListView from "@/components/console/MemoryListView";

export default function MemoryListPreviewPage() {
  const t = useTranslations("console");
  const { projectId, projects } = useProjectContext();
  const { data, loading, updateMemory, deleteMemory } = useGraphData(projectId, {
    includeTemporary: true,
  });

  const assistantName =
    projects.find((project) => project.id === projectId)?.name || t("memory.title");

  if (!projectId) {
    return (
      <div className="memory-page">
        <div className="memory-loading-state">{t("memory.noProject")}</div>
      </div>
    );
  }

  return (
    <motion.div
      className="memory-page"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.15, ease: [0.16, 1, 0.3, 1] }}
    >
      <div className="memory-workspace-bar">
        <div className="memory-workspace-bar-left">
          <h1 className="memory-workspace-title">{assistantName}</h1>
          <span className="memory-workspace-assistant">{t("memory.viewList")} Preview</span>
        </div>
        <div className="memory-workspace-bar-right">
          <Link href="/app/memory" className="memory-action-btn">
            {t("memory.title")}
          </Link>
        </div>
      </div>

      <div className="memory-content">
        {loading ? (
          <div className="memory-loading-state">Loading...</div>
        ) : (
          <div className="memory-list-preview-stage">
            <MemoryListView
              nodes={data.nodes}
              onUpdateMemory={updateMemory}
              onDeleteMemory={deleteMemory}
            />
          </div>
        )}
      </div>
    </motion.div>
  );
}
