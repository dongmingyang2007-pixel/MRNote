"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { useTranslations } from "next-intl";
import { apiGet, apiPost } from "@/lib/api";
import { useWindowManager } from "@/components/notebook/WindowManager";

interface Detail {
  id: string;
  kind: string;
  title: string;
  content_markdown: string;
  content_json: Record<string, unknown>;
  status: string;
  created_at: string;
  period_start: string;
  period_end: string;
}

interface Props {
  digestId: string;
  notebookId: string;
  onBack: () => void;
}

export default function DigestDetail({ digestId, notebookId, onBack }: Props) {
  const t = useTranslations("console-notebooks");
  const [detail, setDetail] = useState<Detail | null>(null);
  const { openWindow } = useWindowManager();

  useEffect(() => {
    void apiGet<Detail>(`/api/v1/digests/${digestId}`)
      .then((d) => {
        setDetail(d);
        if (d.status === "unread") {
          void apiPost(`/api/v1/digests/${d.id}/read`, {});
        }
      })
      .catch(() => setDetail(null));
  }, [digestId]);

  const handleDismiss = useCallback(async () => {
    if (!detail) return;
    await apiPost(`/api/v1/digests/${detail.id}/dismiss`, {});
    onBack();
  }, [detail, onBack]);

  const handleOpenPage = useCallback(
    (pageId: string) => {
      openWindow({
        type: "note",
        title: t("pages.untitled"),
        meta: { notebookId, pageId },
      });
    },
    [notebookId, openWindow, t],
  );

  if (!detail) {
    return <p style={{ padding: 16, fontSize: 12, color: "#888" }}>{t("digest.detail.loading")}</p>;
  }

  const nextActions =
    (detail.content_json?.next_actions as Array<{
      page_id: string; title: string; hint: string;
    }> | undefined) ?? [];
  const reconfirmItems =
    (detail.content_json?.reconfirm_items as Array<{
      memory_id: string; fact: string; age_days: number;
    }> | undefined) ?? [];

  return (
    <div className="digest-detail" data-testid="digest-detail">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <button
          type="button"
          onClick={onBack}
          className="digest-detail__back"
          data-testid="digest-detail-back"
        >
          <ArrowLeft size={14} /> {t("digest.detail.back")}
        </button>
        <button
          type="button"
          onClick={() => void handleDismiss()}
          className="digest-detail__back"
          data-testid="digest-detail-dismiss"
        >
          <X size={14} /> {t("digest.detail.dismiss")}
        </button>
      </div>
      <h2 className="digest-detail__title">{detail.title}</h2>
      <p className="digest-detail__meta">
        {detail.kind} · {detail.created_at.slice(0, 10)}
      </p>
      <div className="digest-detail__body">
        <ReactMarkdown>{detail.content_markdown || t("digest.detail.empty")}</ReactMarkdown>
      </div>

      {nextActions.length > 0 && (
        <>
          <h3 style={{ fontSize: 13, marginTop: 16 }}>{t("digest.detail.nextActions")}</h3>
          <ul style={{ listStyle: "none", padding: 0 }}>
            {nextActions.map((a, i) => (
              <li key={i} style={{ padding: 6, borderBottom: "1px solid #eee" }}>
                <button
                  type="button"
                  onClick={() => handleOpenPage(a.page_id)}
                  data-testid="digest-next-action"
                  style={{
                    background: "none", border: "none",
                    cursor: "pointer", color: "#2563eb",
                    fontSize: 12, padding: 0, textAlign: "left",
                  }}
                >
                  {a.title}
                </button>
                <div style={{ fontSize: 11, color: "#6b7280" }}>{a.hint}</div>
              </li>
            ))}
          </ul>
        </>
      )}

      {reconfirmItems.length > 0 && (
        <>
          <h3 style={{ fontSize: 13, marginTop: 16 }}>{t("digest.detail.memoriesToReconfirm")}</h3>
          <ul style={{ listStyle: "none", padding: 0 }}>
            {reconfirmItems.map((m, i) => (
              <li key={i} style={{ padding: 6, borderBottom: "1px solid #eee", fontSize: 12 }}>
                <strong>{m.fact}</strong>
                <div style={{ color: "#6b7280", fontSize: 11 }}>
                  {m.age_days}d old · {m.memory_id.slice(0, 8)}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
