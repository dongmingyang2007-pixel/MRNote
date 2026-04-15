"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Brain, FileText, Loader2 } from "lucide-react";
import { apiGet } from "@/lib/api";
import MemoryLinksPanel from "@/components/console/editor/MemoryLinksPanel";
import { useWindowManager, useWindows } from "../WindowManager";

interface MemoryWindowProps {
  notebookId: string;
  initialPageId?: string;
}

interface PageItem {
  id: string;
  notebook_id: string;
  title: string;
  page_type: string;
  updated_at: string;
}

export default function MemoryWindow({
  notebookId,
  initialPageId,
}: MemoryWindowProps) {
  const t = useTranslations("console-notebooks");
  const windows = useWindows();
  const { openWindow } = useWindowManager();
  const [pages, setPages] = useState<PageItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedPageId, setSelectedPageId] = useState<string>("");

  const preferredPageId = useMemo(() => {
    if (initialPageId) {
      return initialPageId;
    }

    const activeNoteWindow = [...windows]
      .filter(
        (windowState) =>
          windowState.type === "note" &&
          windowState.meta.notebookId === notebookId &&
          windowState.meta.pageId,
      )
      .sort((a, b) => b.zIndex - a.zIndex)[0];

    return activeNoteWindow?.meta.pageId || "";
  }, [initialPageId, notebookId, windows]);

  useEffect(() => {
    let cancelled = false;

    void apiGet<{ items: PageItem[] }>(`/api/v1/notebooks/${notebookId}/pages`)
      .then((data) => {
        if (cancelled) {
          return;
        }
        setPages(data.items || []);
      })
      .catch(() => {
        if (!cancelled) {
          setPages([]);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [notebookId]);

  const resolvedSelectedPageId = useMemo(() => {
    if (pages.length === 0) {
      return "";
    }

    const pageExists = pages.some((page) => page.id === selectedPageId);
    if (pageExists) {
      return selectedPageId;
    }

    const preferredExists = pages.some((page) => page.id === preferredPageId);
    return preferredExists ? preferredPageId : pages[0]?.id || "";
  }, [pages, preferredPageId, selectedPageId]);

  const selectedPage =
    pages.find((page) => page.id === resolvedSelectedPageId) || null;

  const handleOpenPage = useCallback(
    (page: PageItem) => {
      openWindow({
        type: "note",
        title: page.title || t("pages.untitled"),
        meta: { notebookId, pageId: page.id },
      });
    },
    [notebookId, openWindow, t],
  );

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "220px minmax(0, 1fr)",
        height: "100%",
        minHeight: 0,
      }}
    >
      <aside
        style={{
          borderRight: "1px solid var(--console-border, #e2e8f0)",
          padding: "12px",
          overflowY: "auto",
          background: "var(--bg-surface, #ffffff)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: "0.875rem",
            fontWeight: 600,
            color: "var(--console-text-primary, #1a1a2e)",
            marginBottom: 12,
          }}
        >
          <Brain size={16} />
          <span>{t("memory.title")}</span>
        </div>

        {loading && (
          <div
            style={{
              display: "flex",
              justifyContent: "center",
              paddingTop: 24,
              color: "var(--console-text-muted, #6b7280)",
            }}
          >
            <Loader2 size={18} className="ai-panel-spinner" />
          </div>
        )}

        {!loading && pages.length === 0 && (
          <div
            style={{
              fontSize: "0.8125rem",
              lineHeight: 1.5,
              color: "var(--console-text-muted, #6b7280)",
            }}
          >
            {t("memory.pageListEmpty")}
          </div>
        )}

        {!loading && pages.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {pages.map((page) => {
              const isSelected = page.id === resolvedSelectedPageId;
              return (
                <button
                  key={page.id}
                  type="button"
                  onClick={() => setSelectedPageId(page.id)}
                  onDoubleClick={() => handleOpenPage(page)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    width: "100%",
                    border: "1px solid transparent",
                    borderRadius: 10,
                    padding: "9px 10px",
                    textAlign: "left",
                    background: isSelected
                      ? "rgba(37, 99, 235, 0.08)"
                      : "transparent",
                    borderColor: isSelected
                      ? "rgba(37, 99, 235, 0.16)"
                      : "transparent",
                    color: isSelected
                      ? "var(--console-accent, #2563EB)"
                      : "var(--console-text-secondary, #475569)",
                    cursor: "pointer",
                  }}
                  title={page.title || t("pages.untitled")}
                >
                  <FileText size={15} />
                  <span
                    style={{
                      fontSize: "0.8125rem",
                      fontWeight: isSelected ? 600 : 500,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {page.title || t("pages.untitled")}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </aside>

      <section
        style={{
          display: "flex",
          flexDirection: "column",
          minWidth: 0,
          minHeight: 0,
          background: "var(--bg-surface, #ffffff)",
        }}
      >
        {selectedPage ? (
          <>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
                padding: "12px 16px",
                borderBottom: "1px solid var(--console-border, #e2e8f0)",
              }}
            >
              <div style={{ minWidth: 0 }}>
                <div
                  style={{
                    fontSize: "0.75rem",
                    color: "var(--console-text-muted, #6b7280)",
                    marginBottom: 2,
                  }}
                >
                  {t("memory.currentPage")}
                </div>
                <div
                  style={{
                    fontSize: "0.875rem",
                    fontWeight: 600,
                    color: "var(--console-text-primary, #1a1a2e)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {selectedPage.title || t("pages.untitled")}
                </div>
              </div>
              <button
                type="button"
                className="mem-action-btn"
                onClick={() => handleOpenPage(selectedPage)}
              >
                {t("memory.openPage")}
              </button>
            </div>
            <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
              <MemoryLinksPanel key={selectedPage.id} pageId={selectedPage.id} embedded />
            </div>
          </>
        ) : (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              height: "100%",
              padding: 24,
              color: "var(--console-text-muted, #6b7280)",
              fontSize: "0.875rem",
              textAlign: "center",
            }}
          >
            {t("memory.selectPage")}
          </div>
        )}
      </section>
    </div>
  );
}
