"use client";

import { useTranslations } from "next-intl";
import type { MemoryNode } from "./memory-types";
import {
  isPinnedMemoryNode,
  isSummaryMemoryNode,
  getMemoryRetrievalCount,
  getMemoryCategoryLabel,
} from "@/hooks/useGraphData";

// ---------------------------------------------------------------------------
// Relative time helper
// ---------------------------------------------------------------------------

function getRelativeTime(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diff = now - then;
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d`;
  const months = Math.floor(days / 30);
  return `${months}mo`;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface MemoryCardGridProps {
  nodes: MemoryNode[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MemoryCardGrid({
  nodes,
  selectedId,
  onSelect,
}: MemoryCardGridProps) {
  const t = useTranslations("console");

  if (nodes.length === 0) {
    return (
      <div className="mem-empty-state">
        {t("memory.noResults")}
      </div>
    );
  }

  return (
    <div className="mem-card-grid">
      {nodes.map((node) => {
        const isSelected = node.id === selectedId;
        const categoryLabel = getMemoryCategoryLabel(node) || node.category;
        const pinned = isPinnedMemoryNode(node);
        const summary = isSummaryMemoryNode(node);
        const retrievalCount = getMemoryRetrievalCount(node);

        return (
          <div
            key={node.id}
            className={`mem-card${isSelected ? " is-selected" : ""}`}
            onClick={() => onSelect(node.id)}
          >
            {/* Header */}
            <div className="mem-card-header">
              <span className="mem-card-category">{categoryLabel}</span>
              <span className="mem-card-badges">
                {node.type === "permanent" ? (
                  <span className="mem-badge is-permanent">permanent</span>
                ) : (
                  <span className="mem-badge is-temporary">temporary</span>
                )}
                {pinned && (
                  <span className="mem-badge is-pinned">pinned</span>
                )}
                {summary && (
                  <span className="mem-badge is-summary">summary</span>
                )}
              </span>
            </div>

            {/* Body */}
            <div className="mem-card-body">{node.content}</div>

            {/* Meta */}
            <div className="mem-card-meta">
              <span>
                {t("memory.usedCount", { count: retrievalCount })}
              </span>
              <span>{getRelativeTime(node.updated_at)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
