"use client";

import { useState, useMemo } from "react";
import { useTranslations } from "next-intl";
import type { MemoryNode } from "./memory-types";
import {
  isPinnedMemoryNode,
  isSummaryMemoryNode,
  getMemoryRetrievalCount,
  getMemoryCategoryLabel,
} from "@/hooks/useGraphData";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MemoryListTableProps {
  nodes: MemoryNode[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

type SortField = "category" | "content" | "retrieval" | "time";
type SortDir = "asc" | "desc";

// ---------------------------------------------------------------------------
// Helpers
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

function getTypeBadge(
  node: MemoryNode,
): "pinned" | "summary" | "permanent" | "temporary" {
  if (isPinnedMemoryNode(node)) return "pinned";
  if (isSummaryMemoryNode(node)) return "summary";
  return node.type;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MemoryListTable({
  nodes,
  selectedId,
  onSelect,
}: MemoryListTableProps) {
  const t = useTranslations("console");

  const [sortField, setSortField] = useState<SortField>("time");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // -- Sort handler ----------------------------------------------------------

  function handleSort(field: SortField) {
    if (field === sortField) {
      setSortDir((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  }

  // -- Sorted nodes ----------------------------------------------------------

  const sortedNodes = useMemo(() => {
    const copy = [...nodes];
    const dir = sortDir === "asc" ? 1 : -1;

    copy.sort((a, b) => {
      switch (sortField) {
        case "category": {
          const aLabel = getMemoryCategoryLabel(a) || a.category;
          const bLabel = getMemoryCategoryLabel(b) || b.category;
          return dir * aLabel.localeCompare(bLabel);
        }
        case "content":
          return dir * a.content.localeCompare(b.content);
        case "retrieval":
          return dir * (getMemoryRetrievalCount(a) - getMemoryRetrievalCount(b));
        case "time":
          return (
            dir *
            (new Date(a.updated_at).getTime() -
              new Date(b.updated_at).getTime())
          );
        default:
          return 0;
      }
    });

    return copy;
  }, [nodes, sortField, sortDir]);

  // -- Sort indicator --------------------------------------------------------

  function sortIndicator(field: SortField): React.ReactNode {
    if (field !== sortField) return null;
    return (
      <svg
        width={12}
        height={12}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ display: "inline-block", verticalAlign: "middle", marginLeft: 4 }}
        aria-hidden="true"
      >
        {sortDir === "asc"
          ? <path d="M12 19V5m-7 7 7-7 7 7" />
          : <path d="M12 5v14m7-7-7 7-7-7" />}
      </svg>
    );
  }

  // -- Empty state -----------------------------------------------------------

  if (nodes.length === 0) {
    return <div className="mem-empty-state">{t("memory.noResults")}</div>;
  }

  // -- Render ----------------------------------------------------------------

  return (
    <table className="mem-list-table">
      <thead className="mem-list-header">
        <tr>
          <th
            scope="col"
            className={sortField === "category" ? "is-sorted" : ""}
            onClick={() => handleSort("category")}
            style={{ cursor: "pointer" }}
            aria-sort={sortField === "category" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}
          >
            {t("memory.colCategory")}
            {sortIndicator("category")}
          </th>
          <th
            scope="col"
            className={sortField === "content" ? "is-sorted" : ""}
            onClick={() => handleSort("content")}
            style={{ cursor: "pointer" }}
            aria-sort={sortField === "content" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}
          >
            {t("memory.colContent")}
            {sortIndicator("content")}
          </th>
          <th scope="col">{t("memory.colType")}</th>
          <th
            scope="col"
            className={sortField === "retrieval" ? "is-sorted" : ""}
            onClick={() => handleSort("retrieval")}
            style={{ cursor: "pointer" }}
            aria-sort={sortField === "retrieval" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}
          >
            {t("memory.colRetrieval")}
            {sortIndicator("retrieval")}
          </th>
          <th
            scope="col"
            className={sortField === "time" ? "is-sorted" : ""}
            onClick={() => handleSort("time")}
            style={{ cursor: "pointer" }}
            aria-sort={sortField === "time" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}
          >
            {t("memory.colTime")}
            {sortIndicator("time")}
          </th>
        </tr>
      </thead>
      <tbody>
        {sortedNodes.map((node) => {
          const badge = getTypeBadge(node);
          return (
            <tr
              key={node.id}
              className={`mem-list-row${selectedId === node.id ? " is-selected" : ""}`}
              onClick={() => onSelect(node.id)}
            >
              <td>{getMemoryCategoryLabel(node) || node.category}</td>
              <td className="mem-list-content-cell">{node.content}</td>
              <td>
                <span className={`mem-badge is-${badge}`}>{badge}</span>
              </td>
              <td className="mem-list-meta-cell">
                {getMemoryRetrievalCount(node)}
              </td>
              <td className="mem-list-meta-cell">
                {getRelativeTime(node.updated_at)}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
