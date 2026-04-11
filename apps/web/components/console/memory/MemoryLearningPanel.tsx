"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { apiGet } from "@/lib/api";
import type { MemoryDetailTab, MemoryNode } from "./memory-types";

interface MemoryLearningRun {
  id: string;
  trigger: string;
  status: string;
  stages?: string[];
  used_memory_ids?: string[];
  promoted_memory_ids?: string[];
  degraded_memory_ids?: string[];
  outcome_id?: string | null;
  error?: string | null;
  task_id?: string | null;
  message_id?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  metadata_json?: Record<string, unknown>;
}

interface MemoryLearningPanelProps {
  projectId: string;
  allNodes: MemoryNode[];
  visibleNodes: MemoryNode[];
  search: string;
  onSelectMemory: (id: string, detailTab?: MemoryDetailTab) => void;
}

function formatDate(value?: string | null): string {
  if (!value) return "--";
  return new Date(value).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function getLearningStatusLabel(
  t: (key: string) => string,
  status: string,
): string {
  const labels: Record<string, string> = {
    pending: t("memory.learningStatusPending"),
    completed: t("memory.learningStatusCompleted"),
    failed: t("memory.learningStatusFailed"),
  };
  return labels[status] || status;
}

export default function MemoryLearningPanel({
  projectId,
  allNodes,
  visibleNodes,
  search,
  onSelectMemory,
}: MemoryLearningPanelProps) {
  const t = useTranslations("console");
  const [runs, setRuns] = useState<MemoryLearningRun[]>([]);
  const [loadedProjectId, setLoadedProjectId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void apiGet<MemoryLearningRun[]>(
      `/api/v1/memory/learning-runs?project_id=${encodeURIComponent(projectId)}&limit=200`,
    )
      .then((response) => {
        if (!cancelled) {
          setRuns(Array.isArray(response) ? response : []);
          setLoadedProjectId(projectId);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRuns([]);
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

  const filteredRuns = useMemo(() => {
    const query = search.trim().toLowerCase();
    return runs.filter((run) => {
      const usedMemoryIds = Array.isArray(run.used_memory_ids) ? run.used_memory_ids : [];
      const visibleMatches = usedMemoryIds.length === 0 || usedMemoryIds.some((id) => visibleMemoryIds.has(id));
      if (!visibleMatches) {
        return false;
      }
      if (!query) {
        return true;
      }
      const joinedLabels = usedMemoryIds
        .map((id) => nodeById.get(id)?.content ?? "")
        .join(" ")
        .toLowerCase();
      return (
        run.trigger.toLowerCase().includes(query) ||
        run.status.toLowerCase().includes(query) ||
        joinedLabels.includes(query)
      );
    });
  }, [nodeById, runs, search, visibleMemoryIds]);

  const summary = useMemo(() => {
    const touchedMemoryIds = new Set<string>();
    let completed = 0;
    let failed = 0;
    for (const run of filteredRuns) {
      if (run.status === "completed") {
        completed += 1;
      } else if (run.status === "failed") {
        failed += 1;
      }
      for (const memoryId of [
        ...(run.used_memory_ids ?? []),
        ...(run.promoted_memory_ids ?? []),
        ...(run.degraded_memory_ids ?? []),
      ]) {
        if (typeof memoryId === "string" && memoryId.trim()) {
          touchedMemoryIds.add(memoryId);
        }
      }
    }
    return {
      total: filteredRuns.length,
      completed,
      failed,
      touched: touchedMemoryIds.size,
    };
  }, [filteredRuns]);

  const loading = loadedProjectId !== projectId;

  if (loading) {
    return <div className="mem-empty-state">{t("memory.loadingViews")}</div>;
  }

  if (!filteredRuns.length) {
    return <div className="mem-empty-state">{t("memory.noLearningRuns")}</div>;
  }

  return (
    <>
      <div className="mem-layer-summary-grid">
        <div className="mem-card mem-layer-summary-card">
          <div className="mem-layer-summary-label">
            {t("memory.learningSummaryTotal")}
          </div>
          <div className="mem-layer-summary-value">{summary.total}</div>
        </div>
        <div className="mem-card mem-layer-summary-card">
          <div className="mem-layer-summary-label">
            {t("memory.learningSummaryCompleted")}
          </div>
          <div className="mem-layer-summary-value">{summary.completed}</div>
        </div>
        <div className="mem-card mem-layer-summary-card">
          <div className="mem-layer-summary-label">
            {t("memory.learningSummaryFailed")}
          </div>
          <div className="mem-layer-summary-value">{summary.failed}</div>
        </div>
        <div className="mem-card mem-layer-summary-card">
          <div className="mem-layer-summary-label">
            {t("memory.learningSummaryTouched")}
          </div>
          <div className="mem-layer-summary-value">{summary.touched}</div>
        </div>
      </div>

      <div className="mem-layer-grid">
        {filteredRuns.map((run) => {
          const usedMemoryIds = Array.isArray(run.used_memory_ids) ? run.used_memory_ids : [];
          const promotedMemoryIds = Array.isArray(run.promoted_memory_ids)
            ? run.promoted_memory_ids
            : [];
          const degradedMemoryIds = Array.isArray(run.degraded_memory_ids)
            ? run.degraded_memory_ids
            : [];
          return (
            <div key={run.id} className="mem-card mem-layer-card">
              <div className="mem-layer-header">
                <div>
                  <div className="mem-layer-eyebrow">{run.trigger}</div>
                  <div className="mem-layer-title">
                    {getLearningStatusLabel(t, run.status)}
                  </div>
                </div>
                <span className="mem-badge is-summary">{usedMemoryIds.length}</span>
              </div>

              <div className="mem-layer-content">
                {(run.stages ?? []).join(" -> ") || t("memory.noLearningStages")}
              </div>

              {run.error ? (
                <div className="mem-layer-note">
                  {t("memory.learningError")}: {run.error}
                </div>
              ) : null}

              <div className="mem-layer-chiprow">
                <span className="mem-layer-chip is-static">
                  {t("memory.learningUsed")} {usedMemoryIds.length}
                </span>
                <span className="mem-layer-chip is-static">
                  {t("memory.learningPromoted")} {promotedMemoryIds.length}
                </span>
                <span className="mem-layer-chip is-static">
                  {t("memory.learningDegraded")} {degradedMemoryIds.length}
                </span>
              </div>

              {usedMemoryIds.length > 0 && (
                <div className="mem-layer-chiprow">
                  {usedMemoryIds.slice(0, 4).map((memoryId) => {
                    const memory = nodeById.get(memoryId);
                    if (!memory) return null;
                    return (
                      <button
                        key={memoryId}
                        type="button"
                        className="mem-layer-chip"
                        onClick={() => onSelectMemory(memoryId, "learning")}
                      >
                        {memory.content}
                      </button>
                    );
                  })}
                </div>
              )}

              <div className="mem-layer-meta">
                <span>{formatDate(run.completed_at || run.started_at)}</span>
                <span>
                  {run.outcome_id
                    ? t("memory.learningOutcomeLinked")
                    : t("memory.learningOutcomeMissing")}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}
