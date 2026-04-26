"use client";

import { useEffect, useState } from "react";
import { BookOpen, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { apiGet } from "@/lib/api";

interface StudyAssetLite {
  id: string;
  title: string;
  asset_type: string;
  status: string;
  total_chunks: number;
}

interface StudyTabProps {
  notebookId: string;
}

export default function StudyTab({ notebookId }: StudyTabProps) {
  const t = useTranslations("console-notebooks");
  const [state, setState] = useState<{
    notebookId: string;
    assets: StudyAssetLite[];
    loading: boolean;
  }>(() => ({ notebookId, assets: [], loading: true }));

  if (state.notebookId !== notebookId) {
    setState({ notebookId, assets: [], loading: true });
  }

  useEffect(() => {
    let cancelled = false;
    apiGet<{ items: StudyAssetLite[] }>(`/api/v1/notebooks/${notebookId}/study`)
      .then((data) => {
        if (!cancelled) {
          setState({ notebookId, assets: data.items || [], loading: false });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setState({ notebookId, assets: [], loading: false });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [notebookId]);

  const { assets, loading } = state;

  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: 32 }}>
        <Loader2 size={20} className="animate-spin" style={{ color: "var(--console-text-muted)" }} />
      </div>
    );
  }

  if (assets.length === 0) {
    return (
      <div style={{
        padding: 24, textAlign: "center",
        fontSize: "0.8125rem", color: "var(--console-text-muted)",
        display: "flex", flexDirection: "column", alignItems: "center", gap: 8,
      }}>
        <BookOpen size={24} strokeWidth={1.2} />
        <span>{t("study.tab.empty")}</span>
        <span style={{ fontSize: "0.75rem" }}>{t("study.tab.emptyHint")}</span>
      </div>
    );
  }

  return (
    <div style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 8 }}>
      {assets.map((a) => (
        <div
          key={a.id}
          style={{
            padding: "10px 12px",
            borderRadius: "var(--console-radius-sm)",
            background: "var(--console-surface)",
            border: "1px solid var(--console-border-subtle)",
          }}
        >
          <div style={{ fontSize: "0.8125rem", fontWeight: 500, color: "var(--console-text-primary)" }}>
            {a.title || t("common.untitled")}
          </div>
          <div style={{ fontSize: "0.6875rem", color: "var(--console-text-muted)", marginTop: 2 }}>
            {a.asset_type} · {a.status} · {t("study.assets.chunks", { count: a.total_chunks })}
          </div>
        </div>
      ))}
    </div>
  );
}
