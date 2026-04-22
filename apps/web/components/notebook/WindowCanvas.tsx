"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { FileText, Layers, Search as SearchIcon, Sparkles } from "lucide-react";
import { apiGet } from "@/lib/api";
import { useWindowManager, useWindows } from "./WindowManager";
import Window from "./Window";
import NoteWindow from "./contents/NoteWindow";
import AIPanelWindow from "./contents/AIPanelWindow";
import FileWindow from "./contents/FileWindow";
import MemoryWindow from "./contents/MemoryWindow";
import MemoryGraphWindow from "./contents/MemoryGraphWindow";
import StudyWindow from "./contents/StudyWindow";
import DigestWindow from "./contents/DigestWindow";
import SearchWindow from "./contents/SearchWindow";
import type { WindowState } from "./WindowManager";

// ---------------------------------------------------------------------------
// Window content router
// ---------------------------------------------------------------------------

function WindowContent({ windowState }: { windowState: WindowState }) {
  switch (windowState.type) {
    case "note":
      return <NoteWindow pageId={windowState.meta.pageId || ""} />;

    case "ai_panel":
      return (
        <AIPanelWindow
          notebookId={windowState.meta.notebookId || ""}
          pageId={windowState.meta.pageId || ""}
        />
      );

    case "file":
      return (
        <FileWindow
          url={windowState.meta.url}
          previewUrl={windowState.meta.previewUrl}
          downloadUrl={windowState.meta.downloadUrl}
          mimeType={windowState.meta.mimeType}
          filename={windowState.meta.filename}
        />
      );

    case "memory":
      return (
        <MemoryWindow
          notebookId={windowState.meta.notebookId || ""}
          initialPageId={windowState.meta.pageId}
        />
      );

    case "memory_graph":
      return (
        <MemoryGraphWindow
          notebookId={windowState.meta.notebookId || ""}
          initialSelectedId={windowState.meta.memoryId}
          initialMemoryViewId={windowState.meta.memoryViewId}
        />
      );

    case "study":
      return (
        <StudyWindow
          notebookId={windowState.meta.notebookId || ""}
          initialAssetId={windowState.meta.assetId}
        />
      );

    case "digest":
      return (
        <DigestWindow notebookId={windowState.meta.notebookId || ""} />
      );

    case "search":
      return (
        <SearchWindow
          notebookId={windowState.meta.notebookId}
          projectId={windowState.meta.projectId}
        />
      );

    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState() {
  const t = useTranslations("console-notebooks");
  const params = useParams<{ notebookId?: string }>();
  const notebookId = params?.notebookId || "";
  const { openWindow } = useWindowManager();
  const [firstPage, setFirstPage] = useState<{
    id: string;
    title: string;
  } | null>(null);

  useEffect(() => {
    if (!notebookId) return;
    let cancelled = false;
    void apiGet<{
      items: Array<{ id: string; title: string; page_type: string }>;
    }>(`/api/v1/notebooks/${notebookId}/pages`)
      .then((data) => {
        if (cancelled) return;
        const first = data.items?.[0];
        if (first) setFirstPage({ id: first.id, title: first.title });
      })
      .catch(() => {
        /* silent */
      });
    return () => {
      cancelled = true;
    };
  }, [notebookId]);

  const handleOpenFirstPage = useCallback(() => {
    if (!firstPage || !notebookId) return;
    openWindow({
      type: "note",
      title: firstPage.title || t("common.untitled"),
      meta: { notebookId, pageId: firstPage.id },
    });
  }, [firstPage, notebookId, openWindow, t]);

  const handleAskAi = useCallback(() => {
    if (!firstPage || !notebookId) return;
    // Open the first page + AI panel together so the panel has a page context.
    openWindow({
      type: "note",
      title: firstPage.title || t("common.untitled"),
      meta: { notebookId, pageId: firstPage.id },
    });
    openWindow({
      type: "ai_panel",
      title: `AI · ${firstPage.title || t("common.untitled")}`,
      meta: { notebookId, pageId: firstPage.id },
    });
  }, [firstPage, notebookId, openWindow, t]);

  const handleSearch = useCallback(() => {
    openWindow({
      type: "search",
      title: t("search.windowTitle"),
      meta: { notebookId },
    });
  }, [notebookId, openWindow, t]);

  return (
    <div className="wm-empty-state">
      <Layers size={48} strokeWidth={1.2} className="wm-empty-state-icon" />
      <div className="wm-empty-state-title">{t("canvas.emptyTitle")}</div>
      <div className="wm-empty-state-hint">{t("canvas.emptyHint")}</div>
      <div className="wm-empty-state-actions">
        {firstPage && (
          <button
            type="button"
            className="wm-empty-state-action"
            onClick={handleOpenFirstPage}
            data-testid="empty-canvas-open-first-page"
          >
            <FileText size={12} />
            {t("canvas.openFirstPage")}
          </button>
        )}
        {firstPage && (
          <button
            type="button"
            className="wm-empty-state-action"
            onClick={handleAskAi}
            data-testid="empty-canvas-ask-ai"
          >
            <Sparkles size={12} />
            {t("canvas.askAi")}
          </button>
        )}
        <button
          type="button"
          className="wm-empty-state-action"
          onClick={handleSearch}
          data-testid="empty-canvas-search"
        >
          <SearchIcon size={12} />
          {t("canvas.search")}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Canvas
// ---------------------------------------------------------------------------

export default function WindowCanvas() {
  const canvasRef = useRef<HTMLDivElement>(null);
  const windows = useWindows();
  const { openWindow } = useWindowManager();
  const visibleWindows = windows.filter((w) => !w.minimized);

  const buildNoteExtras = useCallback(
    (w: WindowState) => {
      if (w.type !== "note" || !w.meta.pageId) return undefined;
      return (
        <button
          type="button"
          className="wm-titlebar-btn"
          onClick={(e) => {
            e.stopPropagation();
            openWindow({
              type: "ai_panel",
              title: `AI · ${w.title}`,
              meta: {
                pageId: w.meta.pageId || "",
                notebookId: w.meta.notebookId || "",
              },
            });
          }}
          title="Open AI Panel"
          data-testid="note-open-ai-panel"
        >
          <Sparkles size={14} />
        </button>
      );
    },
    [openWindow],
  );

  return (
    <div ref={canvasRef} className="wm-canvas">
      {visibleWindows.map((w) => (
        <Window
          key={w.id}
          windowState={w}
          titlebarExtras={buildNoteExtras(w)}
        >
          <WindowContent windowState={w} />
        </Window>
      ))}

      {visibleWindows.length === 0 && <EmptyState />}
    </div>
  );
}
