"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { apiGet } from "@/lib/api";
import { useGraphData } from "@/hooks/useGraphData";
import { MemoryGraphView, adaptGraphData } from "@/components/console/graph/memory-graph";

interface Props {
  notebookId: string;
  initialSelectedId?: string;
  initialMemoryViewId?: string;
}

interface MemoryViewSummary {
  id: string;
  source_subject_id?: string | null;
}

export default function MemoryGraphWindow({
  notebookId,
  initialSelectedId,
  initialMemoryViewId,
}: Props) {
  const t = useTranslations("console-notebooks");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [resolveError, setResolveError] = useState<string | null>(null);
  const [resolvedSelectedId, setResolvedSelectedId] = useState<string | null>(
    initialSelectedId || null,
  );

  useEffect(() => {
    if (!notebookId) return;
    let cancelled = false;
    apiGet<{ project_id: string }>(`/api/v1/notebooks/${notebookId}`)
      .then((nb) => {
        if (!cancelled) setProjectId(nb.project_id ?? null);
      })
      .catch((err: Error) => {
        if (!cancelled) setResolveError(err.message || "resolve failed");
      });
    return () => { cancelled = true; };
  }, [notebookId]);

  useEffect(() => {
    setResolvedSelectedId(initialSelectedId || null);
  }, [initialSelectedId]);

  useEffect(() => {
    if (!projectId || !initialMemoryViewId || initialSelectedId) {
      return;
    }
    let cancelled = false;

    void apiGet<MemoryViewSummary[]>(
      `/api/v1/memory/views?project_id=${encodeURIComponent(projectId)}`,
    )
      .then((views) => {
        if (cancelled) {
          return;
        }
        const matchedView = views.find((view) => view.id === initialMemoryViewId);
        setResolvedSelectedId(matchedView?.source_subject_id || null);
      })
      .catch(() => {
        if (!cancelled) {
          setResolvedSelectedId(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [initialMemoryViewId, initialSelectedId, projectId]);

  const { data, loading } = useGraphData(projectId || "");

  const graph = useMemo(() => adaptGraphData(data), [data]);
  const loadingProject = projectId == null && !resolveError;

  if (loadingProject || (loading && graph.nodes.length === 0)) {
    return (
      <div style={{ padding: 24, fontSize: 14, color: "var(--text-secondary)" }}>
        {t("memoryGraph.loading")}
      </div>
    );
  }

  if (graph.nodes.length === 0) {
    return (
      <div style={{ padding: 32, textAlign: "center" }}>
        <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>
          {t("memoryGraph.empty.title")}
        </div>
        <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>
          {t("memoryGraph.empty.body")}
        </div>
      </div>
    );
  }

  return (
    <MemoryGraphView
      nodes={graph.nodes}
      edges={graph.edges}
      initialSelectedId={resolvedSelectedId || undefined}
    />
  );
}
