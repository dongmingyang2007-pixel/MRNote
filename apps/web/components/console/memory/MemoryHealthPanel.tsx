"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { apiGet } from "@/lib/api";
import type { MemoryDetailTab, MemoryNode } from "./memory-types";

interface MemoryHealthEntry {
  kind: string;
  reason: string;
  memory?: MemoryNode | null;
  view?: {
    id: string;
    view_type: string;
    content: string;
    source_subject_id?: string | null;
    metadata_json?: Record<string, unknown> | null;
    updated_at?: string | null;
  } | null;
}

interface MemoryHealthPayload {
  counts?: Record<string, number>;
  entries?: MemoryHealthEntry[];
}

interface MemoryHealthPanelProps {
  projectId: string;
  allNodes: MemoryNode[];
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

function getHealthKindLabel(
  t: (key: string) => string,
  kind: string,
): string {
  const labels: Record<string, string> = {
    stale: t("memory.healthKindStale"),
    conflict: t("memory.healthKindConflict"),
    needs_reconfirm: t("memory.healthKindNeedsReconfirm"),
    high_risk_playbook: t("memory.healthKindHighRiskPlaybook"),
  };
  return labels[kind] || kind;
}

function formatPercent(value?: number | null): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "--";
  }
  return `${Math.round(value * 100)}%`;
}

export default function MemoryHealthPanel({
  projectId,
  allNodes,
  search,
  onSelectMemory,
}: MemoryHealthPanelProps) {
  const t = useTranslations("console");
  const [payload, setPayload] = useState<MemoryHealthPayload>({});
  const [loadedProjectId, setLoadedProjectId] = useState<string | null>(null);
  const [kindFilter, setKindFilter] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void apiGet<MemoryHealthPayload>(
      `/api/v1/memory/health?project_id=${encodeURIComponent(projectId)}&limit=200`,
    )
      .then((response) => {
        if (!cancelled) {
          setPayload(response && typeof response === "object" ? response : {});
          setLoadedProjectId(projectId);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setPayload({});
          setLoadedProjectId(projectId);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const nodeById = useMemo(
    () => new Map(allNodes.map((node) => [node.id, node])),
    [allNodes],
  );

  const summaryCounts = useMemo(
    () =>
      Object.entries(payload.counts || {}).filter(
        ([, count]) => typeof count === "number" && count > 0,
      ),
    [payload.counts],
  );
  const effectiveKindFilter =
    kindFilter && summaryCounts.some(([kind]) => kind === kindFilter)
      ? kindFilter
      : null;

  const entries = useMemo(() => {
    const query = search.trim().toLowerCase();
    const rawEntries = Array.isArray(payload.entries) ? payload.entries : [];
    return rawEntries.filter((entry) => {
      if (effectiveKindFilter && entry.kind !== effectiveKindFilter) {
        return false;
      }
      if (!query) {
        return true;
      }
      const memoryLabel =
        (entry.memory?.content ||
          (entry.memory?.id ? nodeById.get(entry.memory.id)?.content : "") ||
          entry.view?.content ||
          "") ?? "";
      return (
        entry.kind.toLowerCase().includes(query) ||
        entry.reason.toLowerCase().includes(query) ||
        memoryLabel.toLowerCase().includes(query)
      );
    });
  }, [effectiveKindFilter, nodeById, payload.entries, search]);

  const loading = loadedProjectId !== projectId;

  if (loading) {
    return <div className="mem-empty-state">{t("memory.loadingViews")}</div>;
  }

  if (!entries.length) {
    return <div className="mem-empty-state">{t("memory.noHealthIssues")}</div>;
  }

  return (
    <>
      {summaryCounts.length ? (
        <div className="mem-layer-chiprow" style={{ marginBottom: 16 }}>
          {summaryCounts.map(([kind, count]) => (
            <button
              key={kind}
              type="button"
              className={`mem-layer-chip${effectiveKindFilter === kind ? " is-active" : ""}`}
              onClick={() =>
                setKindFilter((current) => (current === kind ? null : kind))
              }
            >
              {getHealthKindLabel(t, kind)} {count}
            </button>
          ))}
        </div>
      ) : null}

      <div className="mem-layer-grid">
        {entries.map((entry, index) => {
          const targetMemoryId =
            entry.memory?.id || entry.view?.source_subject_id || null;
          const label =
            entry.memory?.content ||
            (entry.view?.source_subject_id
              ? nodeById.get(entry.view.source_subject_id)?.content
              : null) ||
            entry.view?.content ||
            t("memory.viewUnknownSubject");
          const viewMetadata =
            entry.view?.metadata_json && typeof entry.view.metadata_json === "object"
              ? entry.view.metadata_json
              : {};
          const successCount = Number(viewMetadata.success_count || 0);
          const failureCount = Number(viewMetadata.failure_count || 0);
          const failureReasons = Array.isArray(viewMetadata.common_failure_reasons)
            ? viewMetadata.common_failure_reasons.filter(
                (item): item is string =>
                  typeof item === "string" && item.trim().length > 0,
              )
            : [];
          const targetTab: MemoryDetailTab = entry.view
            ? "views"
            : entry.kind === "needs_reconfirm"
              ? "history"
              : entry.kind === "stale" || entry.kind === "conflict"
                ? "timeline"
                : "evidence";
          return (
            <div
              key={`${entry.kind}-${targetMemoryId || index}`}
              className={`mem-card mem-layer-card${targetMemoryId ? " is-clickable" : ""}`}
              onClick={() => {
                if (targetMemoryId) {
                  onSelectMemory(targetMemoryId, targetTab);
                }
              }}
            >
              <div className="mem-layer-header">
                <div>
                  <div className="mem-layer-eyebrow">
                    {getHealthKindLabel(t, entry.kind)}
                  </div>
                  <div className="mem-layer-title">{label}</div>
                </div>
                <span className="mem-badge is-summary">
                  {entry.memory
                    ? entry.memory.type === "permanent"
                      ? t("memory.badgePermanent")
                      : t("memory.badgeTemporary")
                    : entry.view?.view_type || "--"}
                </span>
              </div>
              <div className="mem-layer-content">{entry.reason}</div>

              {entry.memory?.suppression_reason ? (
                <div className="mem-layer-note">
                  {t("memory.healthSignalSuppression")}: {entry.memory.suppression_reason}
                </div>
              ) : null}
              {entry.memory?.reconfirm_after ? (
                <div className="mem-layer-note">
                  {t("memory.healthSignalReconfirm")}: {formatDate(entry.memory.reconfirm_after)}
                </div>
              ) : null}
              {typeof entry.memory?.reuse_success_rate === "number" ? (
                <div className="mem-layer-note">
                  {t("memory.healthSignalReuse")}: {formatPercent(entry.memory.reuse_success_rate)}
                </div>
              ) : null}
              {entry.view ? (
                <div className="mem-layer-note">
                  {t("memory.healthSignalSuccessFailure")}: {successCount}/{failureCount}
                </div>
              ) : null}
              {failureReasons.length ? (
                <div className="mem-layer-note">
                  {t("memory.healthFailureReasons")}: {failureReasons.join(" · ")}
                </div>
              ) : null}

              {targetMemoryId ? (
                <div className="mem-layer-chiprow">
                  <button
                    type="button"
                    className="mem-layer-chip"
                    onClick={(event) => {
                      event.stopPropagation();
                      onSelectMemory(targetMemoryId, targetTab);
                    }}
                  >
                    {label}
                  </button>
                </div>
              ) : null}

              <div className="mem-layer-meta">
                <span>{entry.view?.view_type || entry.memory?.type || "--"}</span>
                <span>
                  {entry.view?.updated_at
                    ? formatDate(entry.view.updated_at)
                    : entry.memory?.updated_at
                      ? formatDate(entry.memory.updated_at)
                      : "--"}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}
