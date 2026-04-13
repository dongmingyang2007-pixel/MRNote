"use client";

import { useEffect, useState, useMemo } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Brain, Loader2 } from "lucide-react";
import { apiGet } from "@/lib/api";
import { useGraphData, isOrdinaryMemoryNode } from "@/hooks/useGraphData";
import MemoryCardGrid from "@/components/console/memory/MemoryCardGrid";

interface NotebookInfo {
  id: string;
  project_id: string | null;
}

export default function NotebookMemoryPage() {
  const params = useParams<{ notebookId: string }>();
  const t = useTranslations("console-notebooks");
  const [notebook, setNotebook] = useState<NotebookInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void apiGet<NotebookInfo>(`/api/v1/notebooks/${params.notebookId}`)
      .then((data) => {
        if (cancelled) return;
        setNotebook(data);
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [params.notebookId]);

  const { data } = useGraphData(notebook?.project_id ?? "");
  const memoryNodes = useMemo(
    () => data.nodes.filter(isOrdinaryMemoryNode),
    [data.nodes],
  );

  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--console-text-muted)" }}>
        <Loader2 size={20} className="ai-panel-spinner" style={{ marginRight: 8 }} />
        {t("common.loading")}
      </div>
    );
  }

  if (!notebook?.project_id) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 12 }}>
        <Brain size={32} strokeWidth={1.5} color="var(--console-text-muted)" />
        <p style={{ color: "var(--console-text-muted)", fontSize: "0.875rem" }}>
          {t("common.noProject")}
        </p>
      </div>
    );
  }

  return (
    <div style={{ height: "100%", overflow: "auto", padding: "24px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
        <Brain size={22} color="var(--console-accent, #2563EB)" />
        <h2 style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--console-text-primary)", fontFamily: "var(--font-sora, var(--font-sans))" }}>
          {t("memory.title")}
        </h2>
        <span style={{ fontSize: "0.8125rem", color: "var(--console-text-muted)" }}>
          {memoryNodes.length} items
        </span>
      </div>

      {memoryNodes.length === 0 ? (
        <div style={{ textAlign: "center", padding: 40, color: "var(--console-text-muted)", fontSize: "0.875rem" }}>
          {t("memory.empty")}
        </div>
      ) : (
        <MemoryCardGrid
          nodes={memoryNodes}
          selectedId={null}
          onSelect={() => {}}
        />
      )}
    </div>
  );
}
