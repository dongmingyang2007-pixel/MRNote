"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Plus, FileText, ArrowLeft, Pin, Trash2, ChevronRight, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { apiGet, apiPost, apiDelete } from "@/lib/api";
import { useWindowManager } from "@/components/notebook/WindowManager";
import WindowCanvas from "@/components/notebook/WindowCanvas";

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
  const searchParams = useSearchParams();
  const t = useTranslations("console-notebooks");
  const router = useRouter();
  const { openWindow } = useWindowManager();
  const [notebook, setNotebook] = useState<NotebookInfo | null>(null);
  const [pages, setPages] = useState<PageItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [listCollapsed, setListCollapsed] = useState(false);
  const handledOpenTargetRef = useRef("");

  // Hydrate collapsed state from localStorage
  useEffect(() => {
    try {
      const v = localStorage.getItem("mrai.notebook-page-list.collapsed");
      if (v === "1") setListCollapsed(true);
    } catch { /* ignore */ }
  }, []);
  const toggleListCollapsed = useCallback(() => {
    setListCollapsed((prev) => {
      const next = !prev;
      try { localStorage.setItem("mrai.notebook-page-list.collapsed", next ? "1" : "0"); } catch { /* ignore */ }
      return next;
    });
  }, []);

  useEffect(() => {
    void apiGet<NotebookInfo>(`/api/v1/notebooks/${params.notebookId}`)
      .then(setNotebook)
      .catch(() => setNotebook(null));
  }, [params.notebookId]);

  useEffect(() => {
    const openPageId = searchParams.get("openPage");
    const openTarget = openPageId ? `${params.notebookId}:${openPageId}` : "";
    if (!openPageId || loading || handledOpenTargetRef.current === openTarget) {
      return;
    }

    const existingPage = pages.find((page) => page.id === openPageId);
    openWindow({
      type: "note",
      title: existingPage?.title || t("pages.untitled"),
      meta: { notebookId: params.notebookId, pageId: openPageId },
    });
    handledOpenTargetRef.current = openTarget;
    router.replace(`/app/notebooks/${params.notebookId}`);
  }, [loading, openWindow, pages, params.notebookId, router, searchParams, t]);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const data = await apiGet<{ items: PageItem[]; total: number }>(
          `/api/v1/notebooks/${params.notebookId}/pages`
        );
        if (!cancelled) {
          setPages(data.items || []);
        }
      } catch {
        if (!cancelled) {
          setPages([]);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [params.notebookId]);

  const handleCreate = useCallback(async () => {
    if (creating) return;
    setCreating(true);
    try {
      const page = await apiPost<PageItem>(
        `/api/v1/notebooks/${params.notebookId}/pages`,
        { title: "", page_type: "document" }
      );
      openWindow({
        type: "note",
        title: page.title || t("pages.untitled"),
        meta: { notebookId: params.notebookId, pageId: page.id },
      });
      setPages((prev) => [page, ...prev]);
    } catch {
      // ignore
    }
    setCreating(false);
  }, [creating, params.notebookId, openWindow, t]);

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
    <div style={{ display: "flex", width: "100%", height: "100%" }}>
      {/* Page list panel */}
      {listCollapsed ? (
        <div
          style={{
            width: 36, flexShrink: 0,
            borderRight: "1px solid var(--console-border-subtle, rgba(255,255,255,0.5))",
            display: "flex", flexDirection: "column", alignItems: "center",
            padding: "12px 0", gap: 8,
          }}
        >
          <button
            type="button"
            data-testid="notebook-page-list-expand"
            onClick={toggleListCollapsed}
            title={t("pages.expandList")}
            aria-label={t("pages.expandList")}
            style={{
              width: 28, height: 28, display: "flex", alignItems: "center", justifyContent: "center",
              background: "rgba(255,255,255,0.88)", backdropFilter: "blur(8px)",
              border: "1px solid rgba(15,42,45,0.1)", borderRadius: 8,
              color: "var(--console-text-primary, #1a1a2e)", cursor: "pointer",
            }}
          >
            <PanelLeftOpen size={14} />
          </button>
        </div>
      ) : (
      <div
        className="console-page-shell"
        style={{
          width: 320,
          flexShrink: 0,
          padding: "24px 20px",
          overflowY: "auto",
          borderRight: "1px solid var(--console-border-subtle, rgba(255,255,255,0.5))",
          position: "relative",
        }}
      >
        {/* Collapse button */}
        <button
          type="button"
          data-testid="notebook-page-list-collapse"
          onClick={toggleListCollapsed}
          title={t("pages.collapseList")}
          aria-label={t("pages.collapseList")}
          style={{
            position: "absolute", top: 12, right: 8,
            width: 28, height: 28, display: "flex", alignItems: "center", justifyContent: "center",
            background: "transparent", border: "none", borderRadius: 6,
            color: "var(--console-text-muted, #6b7280)", cursor: "pointer",
          }}
        >
          <PanelLeftClose size={14} />
        </button>
        {/* Breadcrumb */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 20, fontSize: "0.8125rem", color: "var(--console-text-muted, #6b7280)" }}>
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
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <h1 style={{ fontSize: "1.125rem", fontWeight: 700, color: "var(--console-text-primary)", fontFamily: "var(--font-sora, var(--font-sans))", margin: 0 }}>
            {notebook?.title || t("notebooks.untitled")}
          </h1>
          <button
            onClick={handleCreate}
            disabled={creating}
            style={{
              display: "inline-flex", alignItems: "center", gap: 4,
              padding: "6px 12px", background: "var(--console-accent-gradient, linear-gradient(135deg, #2563EB, #3B82F6))",
              color: "white", border: "none", borderRadius: 8,
              fontSize: "0.75rem", fontWeight: 600, cursor: creating ? "not-allowed" : "pointer",
              opacity: creating ? 0.6 : 1,
            }}
          >
            <Plus size={14} />
            {t("pages.create")}
          </button>
        </div>

        {pages.length > 0 && (
          <p style={{ fontSize: "0.75rem", color: "var(--console-text-muted)", margin: "0 0 12px" }}>
            {pages.length} {t("pages.title").toLowerCase()}
          </p>
        )}

        {/* Loading */}
        {loading && (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {[1, 2, 3].map((i) => (
              <div key={i} style={{
                height: 48, borderRadius: 8,
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
            justifyContent: "center", minHeight: 200, textAlign: "center",
          }}>
            <div style={{
              width: 56, height: 56, borderRadius: 14,
              background: "rgba(37, 99, 235, 0.06)",
              display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 16,
            }}>
              <FileText size={24} strokeWidth={1.5} color="#2563EB" />
            </div>
            <p style={{ fontSize: "0.8125rem", color: "var(--console-text-muted)", maxWidth: 240, marginBottom: 16, lineHeight: 1.6 }}>
              {t("pages.empty")}
            </p>
            <button
              onClick={handleCreate}
              disabled={creating}
              style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "8px 16px", background: "var(--console-accent-gradient, linear-gradient(135deg, #2563EB, #3B82F6))",
                color: "white", border: "none", borderRadius: 8,
                fontSize: "0.8125rem", fontWeight: 600, cursor: "pointer",
              }}
            >
              <Plus size={14} />
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
                onClick={() =>
                  openWindow({
                    type: "note",
                    title: page.title || t("pages.untitled"),
                    meta: { notebookId: params.notebookId, pageId: page.id },
                  })
                }
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
      )}

      {/* Window canvas */}
      <div style={{ flex: 1, minWidth: 0, position: "relative" }}>
        <WindowCanvas />
      </div>
    </div>
  );
}
