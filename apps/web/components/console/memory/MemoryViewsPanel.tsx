"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { apiGet } from "@/lib/api";
import type { MemoryNode } from "./memory-types";

interface MemoryWorkbenchView {
  id: string;
  source_subject_id?: string | null;
  view_type: string;
  content: string;
  metadata_json?: {
    source_memory_ids?: string[];
    memory_count?: number;
  } | null;
  created_at: string;
  updated_at: string;
}

interface MemoryViewsPanelProps {
  projectId: string;
  allNodes: MemoryNode[];
  visibleNodes: MemoryNode[];
  selectedSubjectId?: string | null;
  search: string;
  onSelectMemory: (id: string) => void;
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function getViewLabel(t: (key: string) => string, viewType: string): string {
  switch (viewType) {
    case "profile":
      return t("memory.viewTypeProfile");
    case "timeline":
      return t("memory.viewTypeTimeline");
    case "playbook":
      return t("memory.viewTypePlaybook");
    case "summary":
      return t("memory.viewTypeSummary");
    default:
      return viewType;
  }
}

export default function MemoryViewsPanel({
  projectId,
  allNodes,
  visibleNodes,
  selectedSubjectId,
  search,
  onSelectMemory,
}: MemoryViewsPanelProps) {
  const t = useTranslations("console");
  const [views, setViews] = useState<MemoryWorkbenchView[]>([]);
  const [loadedProjectId, setLoadedProjectId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void apiGet<MemoryWorkbenchView[]>(
      `/api/v1/memory/views?project_id=${encodeURIComponent(projectId)}`,
    )
      .then((response) => {
        if (!cancelled) {
          setViews(Array.isArray(response) ? response : []);
          setLoadedProjectId(projectId);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setViews([]);
          setLoadedProjectId(projectId);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const visibleMemoryIds = useMemo(
    () => new Set(visibleNodes.map((node) => node.id)),
    [visibleNodes],
  );
  const nodeById = useMemo(
    () => new Map(allNodes.map((node) => [node.id, node])),
    [allNodes],
  );

  const filteredViews = useMemo(() => {
    const query = search.trim().toLowerCase();
    return views.filter((view) => {
      const sourceMemoryIds = Array.isArray(view.metadata_json?.source_memory_ids)
        ? view.metadata_json?.source_memory_ids ?? []
        : [];
      const matchesScope = selectedSubjectId
        ? view.source_subject_id === selectedSubjectId ||
          sourceMemoryIds.some((id) => visibleMemoryIds.has(id))
        : sourceMemoryIds.length === 0 ||
          sourceMemoryIds.some((id) => visibleMemoryIds.has(id)) ||
          (!!view.source_subject_id && visibleMemoryIds.has(view.source_subject_id));
      if (!matchesScope) {
        return false;
      }
      if (!query) {
        return true;
      }
      const subjectLabel = view.source_subject_id
        ? nodeById.get(view.source_subject_id)?.content ?? ""
        : "";
      return (
        view.content.toLowerCase().includes(query) ||
        view.view_type.toLowerCase().includes(query) ||
        subjectLabel.toLowerCase().includes(query)
      );
    });
  }, [nodeById, search, selectedSubjectId, views, visibleMemoryIds]);

  const loading = loadedProjectId !== projectId;

  if (loading) {
    return <div className="mem-empty-state">{t("memory.loadingViews")}</div>;
  }

  if (filteredViews.length === 0) {
    return <div className="mem-empty-state">{t("memory.noDerivedViews")}</div>;
  }

  return (
    <div className="mem-layer-grid">
      {filteredViews.map((view) => {
        const sourceMemoryIds = Array.isArray(view.metadata_json?.source_memory_ids)
          ? view.metadata_json?.source_memory_ids ?? []
          : [];
        const subjectNode = view.source_subject_id
          ? nodeById.get(view.source_subject_id) ?? null
          : null;
        return (
          <div
            key={view.id}
            className={`mem-card mem-layer-card${subjectNode ? " is-clickable" : ""}`}
            onClick={() => {
              if (subjectNode) {
                onSelectMemory(subjectNode.id);
              }
            }}
          >
            <div className="mem-layer-header">
              <div>
                <div className="mem-layer-eyebrow">
                  {getViewLabel(t, view.view_type)}
                </div>
                <div className="mem-layer-title">
                  {subjectNode?.content || t("memory.viewUnknownSubject")}
                </div>
              </div>
              <span className="mem-badge is-summary">
                {view.metadata_json?.memory_count ?? sourceMemoryIds.length}
              </span>
            </div>

            <div className="mem-layer-content">{view.content}</div>

            {sourceMemoryIds.length > 0 && (
              <div className="mem-layer-chiprow">
                {sourceMemoryIds.slice(0, 4).map((memoryId) => {
                  const sourceNode = nodeById.get(memoryId);
                  if (!sourceNode) {
                    return null;
                  }
                  return (
                    <button
                      key={memoryId}
                      type="button"
                      className="mem-layer-chip"
                      onClick={(event) => {
                        event.stopPropagation();
                        onSelectMemory(memoryId);
                      }}
                    >
                      {sourceNode.content}
                    </button>
                  );
                })}
              </div>
            )}

            <div className="mem-layer-meta">
              <span>{t("memory.updated")}</span>
              <span>{formatDate(view.updated_at)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
