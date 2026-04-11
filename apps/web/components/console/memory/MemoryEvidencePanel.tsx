"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { apiGet } from "@/lib/api";
import type { MemoryNode } from "./memory-types";
import { getMemoryCategoryLabel } from "@/hooks/useGraphData";

interface MemoryEvidenceItem {
  id: string;
  memory_id: string;
  source_type: string;
  message_role?: string | null;
  quote_text: string;
  confidence?: number | null;
  created_at: string;
}

interface MemoryEvidencePanelProps {
  projectId: string;
  allNodes: MemoryNode[];
  visibleNodes: MemoryNode[];
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

function getEvidenceLabel(t: (key: string) => string, sourceType: string): string {
  switch (sourceType) {
    case "message":
      return t("memory.evidenceSourceMessage");
    case "conversation":
      return t("memory.evidenceSourceConversation");
    case "file":
      return t("memory.evidenceSourceFile");
    case "manual":
      return t("memory.evidenceSourceManual");
    default:
      return sourceType;
  }
}

export default function MemoryEvidencePanel({
  projectId,
  allNodes,
  visibleNodes,
  search,
  onSelectMemory,
}: MemoryEvidencePanelProps) {
  const t = useTranslations("console");
  const [evidences, setEvidences] = useState<MemoryEvidenceItem[]>([]);
  const [loadedProjectId, setLoadedProjectId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void apiGet<MemoryEvidenceItem[]>(
      `/api/v1/memory/evidences?project_id=${encodeURIComponent(projectId)}&limit=200`,
    )
      .then((response) => {
        if (!cancelled) {
          setEvidences(Array.isArray(response) ? response : []);
          setLoadedProjectId(projectId);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setEvidences([]);
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

  const filteredEvidences = useMemo(() => {
    const query = search.trim().toLowerCase();
    return evidences.filter((evidence) => {
      if (!visibleMemoryIds.has(evidence.memory_id)) {
        return false;
      }
      if (!query) {
        return true;
      }
      const memory = nodeById.get(evidence.memory_id);
      return (
        evidence.quote_text.toLowerCase().includes(query) ||
        evidence.source_type.toLowerCase().includes(query) ||
        (memory?.content.toLowerCase().includes(query) ?? false) ||
        (memory?.category.toLowerCase().includes(query) ?? false)
      );
    });
  }, [evidences, nodeById, search, visibleMemoryIds]);

  const loading = loadedProjectId !== projectId;

  if (loading) {
    return <div className="mem-empty-state">{t("memory.loadingEvidence")}</div>;
  }

  if (filteredEvidences.length === 0) {
    return <div className="mem-empty-state">{t("memory.noEvidenceLayer")}</div>;
  }

  return (
    <div className="mem-layer-grid">
      {filteredEvidences.map((evidence) => {
        const memory = nodeById.get(evidence.memory_id) ?? null;
        return (
          <div
            key={evidence.id}
            className={`mem-card mem-layer-card${memory ? " is-clickable" : ""}`}
            onClick={() => {
              if (memory) {
                onSelectMemory(memory.id);
              }
            }}
          >
            <div className="mem-layer-header">
              <div>
                <div className="mem-layer-eyebrow">
                  {getEvidenceLabel(t, evidence.source_type)}
                </div>
                <div className="mem-layer-title">
                  {memory ? getMemoryCategoryLabel(memory) || memory.category : t("memory.uncategorized")}
                </div>
              </div>
              <span className="mem-badge is-permanent">
                {typeof evidence.confidence === "number" ? evidence.confidence.toFixed(2) : "--"}
              </span>
            </div>

            <div className="mem-layer-content">{evidence.quote_text}</div>

            {memory && (
              <button
                type="button"
                className="mem-layer-chip"
                onClick={(event) => {
                  event.stopPropagation();
                  onSelectMemory(memory.id);
                }}
              >
                {memory.content}
              </button>
            )}

            <div className="mem-layer-meta">
              <span>{formatDate(evidence.created_at)}</span>
              <span>
                {evidence.message_role ? `${evidence.message_role} · ` : ""}
                {getEvidenceLabel(t, evidence.source_type)}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
