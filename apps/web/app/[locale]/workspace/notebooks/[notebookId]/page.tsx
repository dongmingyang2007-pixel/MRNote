"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Plus, FileText, ArrowLeft, Pin, Trash2, ChevronRight } from "lucide-react";
import { apiGet, apiPost, apiDelete } from "@/lib/api";

interface NotebookInfo {
  id: string;
  title: string;
}

interface PageItem {
  id: string;
  notebook_id: string;
  title: string;
  page_type: string;
  is_pinned: boolean;
  summary_text?: string;
  updated_at: string;
  created_at: string;
}

export default function NotebookDetailPage() {
  const params = useParams<{ notebookId: string }>();
  const t = useTranslations("console-notebooks");
  const router = useRouter();
  const [notebook, setNotebook] = useState<NotebookInfo | null>(null);
  const [pages, setPages] = useState<PageItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    void apiGet<NotebookInfo>(`/api/v1/notebooks/${params.notebookId}`)
      .then(setNotebook)
      .catch(() => setNotebook(null));
  }, [params.notebookId]);

  const loadPages = useCallback(async () => {
    try {
      const data = await apiGet<{ items: PageItem[]; total: number }>(
        `/api/v1/notebooks/${params.notebookId}/pages`
      );
      setPages(data.items || []);
    } catch {
      setPages([]);
    }
    setLoading(false);
  }, [params.notebookId]);

  useEffect(() => {
    void loadPages();
  }, [loadPages]);

  const handleCreate = useCallback(async () => {
    if (creating) return;
    setCreating(true);
    try {
      const page = await apiPost<PageItem>(
        `/api/v1/notebooks/${params.notebookId}/pages`,
        { title: "", page_type: "document" }
      );
      router.push(`/app/notebooks/${params.notebookId}/pages/${page.id}`);
    } catch {
      // ignore
    }
    setCreating(false);
  }, [creating, params.notebookId, router]);

  const handleDelete = useCallback(async (pageId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await apiDelete(`/api/v1/pages/${pageId}`);
      setPages((prev) => prev.filter((p) => p.id !== pageId));
    } catch {
      // ignore
    }
  }, []);

  const formatDate = (dateStr: string) =>
    new Date(dateStr).toLocaleDateString(undefined, {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });

  return (
    <div className="console-page-shell" style={{ padding: "24px 32px" }}>
      <div style={{ width: "100%" }}>
        {/* Breadcrumb */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 24, fontSize: "0.8125rem", color: "var(--console-text-muted, #6b7280)" }}>
          <button
            onClick={() => router.push("/app/notebooks")}
            style={{ display: "flex", alignItems: "center", gap: 4, background: "none", border: "none", cursor: "pointer", color: "inherit", padding: 0, fontSize: "inherit" }}
          >
            <ArrowLeft size={14} />
            {t("notebooks.title")}
          </button>
          <ChevronRight size={14} />
          <span style={{ color: "var(--console-text-primary, #1a1a2e)", fontWeight: 500 }}>
            {notebook?.title || t("notebooks.untitled")}
          </span>
        </div>

        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 28 }}>
          <div>
            <h1 style={{ fontSize: "1.5rem", fontWeight: 700, color: "var(--console-text-primary)", fontFamily: "var(--font-sora, var(--font-sans))", marginBottom: 4 }}>
              {notebook?.title || t("notebooks.untitled")}
            </h1>
            <p style={{ fontSize: "0.8125rem", color: "var(--console-text-muted)", margin: 0 }}>
              {pages.length > 0 ? `${pages.length} ${t("pages.title").toLowerCase()}` : ""}
            </p>
          </div>
          <button
            onClick={handleCreate}
            disabled={creating}
            style={{
              display: "inline-flex", alignItems: "center", gap: 8,
              padding: "10px 20px", background: "var(--console-accent-gradient, linear-gradient(135deg, #2563EB, #3B82F6))",
              color: "white", border: "none", borderRadius: 12,
              fontSize: "0.875rem", fontWeight: 600, cursor: creating ? "not-allowed" : "pointer",
              opacity: creating ? 0.6 : 1, boxShadow: "0 2px 8px rgba(37, 99, 235, 0.25)",
              transition: "all 200ms ease",
            }}
          >
            <Plus size={16} />
            {t("pages.create")}
          </button>
        </div>

        {/* Loading */}
        {loading && (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {[1, 2, 3, 4].map((i) => (
              <div key={i} style={{
                height: 60, borderRadius: 12,
                background: "rgba(255, 255, 255, 0.5)",
                border: "1px solid rgba(15, 23, 42, 0.04)",
                animation: "pulse 1.5s ease-in-out infinite",
              }} />
            ))}
          </div>
        )}

        {/* Empty state */}
        {!loading && pages.length === 0 && (
          <div style={{
            display: "flex", flexDirection: "column", alignItems: "center",
            justifyContent: "center", minHeight: 350, textAlign: "center",
          }}>
            <div style={{
              width: 72, height: 72, borderRadius: 18,
              background: "rgba(37, 99, 235, 0.06)",
              display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 20,
            }}>
              <FileText size={32} strokeWidth={1.5} color="#2563EB" />
            </div>
            <h3 style={{ fontSize: "1.0625rem", fontWeight: 600, color: "var(--console-text-primary)", marginBottom: 8 }}>
              {t("pages.title")}
            </h3>
            <p style={{ fontSize: "0.875rem", color: "var(--console-text-muted)", maxWidth: 300, marginBottom: 24, lineHeight: 1.6 }}>
              {t("pages.empty")}
            </p>
            <button
              onClick={handleCreate}
              disabled={creating}
              style={{
                display: "inline-flex", alignItems: "center", gap: 8,
                padding: "10px 20px", background: "var(--console-accent-gradient, linear-gradient(135deg, #2563EB, #3B82F6))",
                color: "white", border: "none", borderRadius: 12,
                fontSize: "0.875rem", fontWeight: 600, cursor: "pointer",
                boxShadow: "0 2px 8px rgba(37, 99, 235, 0.25)",
              }}
            >
              <Plus size={16} />
              {t("pages.create")}
            </button>
          </div>
        )}

        {/* Page list */}
        {!loading && pages.length > 0 && (
          <div className="page-list">
            {pages.map((page) => (
              <div
                key={page.id}
                className="page-list-item"
                onClick={() => router.push(`/app/notebooks/${params.notebookId}/pages/${page.id}`)}
              >
                <div className="page-list-item-icon">
                  <FileText size={18} />
                </div>
                <div className="page-list-item-content">
                  <span className="page-list-item-title">
                    {page.title || t("pages.untitled")}
                  </span>
                  <span className="page-list-item-meta">
                    {t(`pages.${page.page_type}` as "pages.document")} · {formatDate(page.updated_at)}
                  </span>
                </div>
                <div className="page-list-item-actions">
                  {page.is_pinned && <Pin size={14} className="page-list-pin" />}
                  <button
                    type="button"
                    className="page-list-delete"
                    onClick={(e) => handleDelete(page.id, e)}
                    title="Delete"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
