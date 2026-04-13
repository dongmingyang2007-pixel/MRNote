"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { MessageSquare, Loader2 } from "lucide-react";
import { apiGet } from "@/lib/api";
import { ChatInterface } from "@/components/console/ChatInterface";

interface NotebookInfo {
  id: string;
  title: string;
  project_id: string | null;
}

export default function NotebookChatPage() {
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
        <MessageSquare size={32} strokeWidth={1.5} color="var(--console-text-muted)" />
        <p style={{ color: "var(--console-text-muted)", fontSize: "0.875rem" }}>
          {t("common.noProject")}
        </p>
      </div>
    );
  }

  return (
    <div style={{ height: "100%", overflow: "hidden" }}>
      <ChatInterface projectId={notebook.project_id} />
    </div>
  );
}
