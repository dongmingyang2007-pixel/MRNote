"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  FileText,
  Layers,
  Plus,
  Search as SearchIcon,
  Sparkles,
} from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { requestGuestRegisterGate } from "@/components/console/GuestRegisterGate";
import {
  NOTEBOOK_PAGES_CHANGED_EVENT,
  dispatchNotebookPagesChanged,
} from "@/lib/notebook-events";
import { useWindowManager, useWindows } from "./WindowManager";
import Window from "./Window";
import type { WindowState } from "./WindowManager";

// ---------------------------------------------------------------------------
// Helpers (U-05)
// ---------------------------------------------------------------------------

function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  const diffSec = Math.max(0, (Date.now() - date.getTime()) / 1000);
  if (diffSec < 30) return "just now";
  if (diffSec < 60) return `${Math.floor(diffSec)}s ago`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  if (diffSec < 30 * 86400) return `${Math.floor(diffSec / 86400)}d ago`;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(date);
}

const WindowContentFallback = () => (
  <div
    style={{
      height: "100%",
      width: "100%",
      display: "grid",
      placeItems: "center",
      color: "var(--console-text-muted, #64748b)",
      fontSize: "0.875rem",
    }}
  >
    Loading...
  </div>
);

const NoteWindow = dynamic(() => import("./contents/NoteWindow"), {
  ssr: false,
  loading: WindowContentFallback,
});
const GuestLocalNoteWindow = dynamic(
  () => import("./contents/GuestLocalNoteWindow"),
  {
    ssr: false,
    loading: WindowContentFallback,
  },
);
const AIPanelWindow = dynamic(() => import("./contents/AIPanelWindow"), {
  ssr: false,
  loading: WindowContentFallback,
});
const FileWindow = dynamic(() => import("./contents/FileWindow"), {
  ssr: false,
  loading: WindowContentFallback,
});
const MemoryWindow = dynamic(() => import("./contents/MemoryWindow"), {
  ssr: false,
  loading: WindowContentFallback,
});
const MemoryGraphWindow = dynamic(
  () => import("./contents/MemoryGraphWindow"),
  {
    ssr: false,
    loading: WindowContentFallback,
  },
);
const StudyWindow = dynamic(() => import("./contents/StudyWindow"), {
  ssr: false,
  loading: WindowContentFallback,
});
const DigestWindow = dynamic(() => import("./contents/DigestWindow"), {
  ssr: false,
  loading: WindowContentFallback,
});
const SearchWindow = dynamic(() => import("./contents/SearchWindow"), {
  ssr: false,
  loading: WindowContentFallback,
});

// ---------------------------------------------------------------------------
// Window content router
// ---------------------------------------------------------------------------

function WindowContent({ windowState }: { windowState: WindowState }) {
  switch (windowState.type) {
    case "note":
      return <NoteWindow pageId={windowState.meta.pageId || ""} />;

    case "guest_note":
      return <GuestLocalNoteWindow />;

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
      return <DigestWindow notebookId={windowState.meta.notebookId || ""} />;

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
// Note titlebar extras (U-05 / Spec §19.3)
// ---------------------------------------------------------------------------

interface NoteTitlebarExtrasProps {
  pageId: string;
  notebookId: string;
  title: string;
}

function NoteTitlebarExtras({
  pageId,
  notebookId,
  title,
}: NoteTitlebarExtrasProps) {
  const t = useTranslations("console-notebooks");
  const { openWindow } = useWindowManager();
  const [meta, setMeta] = useState<{
    page_type: string | null;
    page_icon: string | null;
    updated_at: string | null;
  }>({ page_type: null, page_icon: null, updated_at: null });
  const [savePulse, setSavePulse] = useState(false);

  // Initial fetch + listen for page-changed events (fires after saves /
  // title edits via dispatchNotebookPagesChanged in NoteWindow). Kept
  // inlined so we don't trip react-hooks/set-state-in-effect on an
  // eagerly-invoked callback.
  useEffect(() => {
    if (!pageId) return;
    let cancelled = false;

    const fetchMeta = () => {
      void apiGet<{
        page_type?: string;
        page_icon?: string;
        updated_at?: string;
      }>(`/api/v1/pages/${pageId}`)
        .then((data) => {
          if (cancelled) return;
          setMeta({
            page_type: data.page_type ?? null,
            page_icon: data.page_icon ?? null,
            updated_at: data.updated_at ?? null,
          });
        })
        .catch(() => {
          /* silent */
        });
    };

    fetchMeta();
    const handler = () => {
      fetchMeta();
      // Brief pulse on the save dot so the user sees that a save happened.
      setSavePulse(true);
      window.setTimeout(() => setSavePulse(false), 1200);
    };
    window.addEventListener(NOTEBOOK_PAGES_CHANGED_EVENT, handler);
    return () => {
      cancelled = true;
      window.removeEventListener(NOTEBOOK_PAGES_CHANGED_EVENT, handler);
    };
  }, [pageId]);

  // Re-render so the relative time string drifts forward.
  const [, force] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => force((x) => x + 1), 60_000);
    return () => clearInterval(timer);
  }, []);

  const pageTypeLabel = (() => {
    switch (meta.page_type) {
      case "document":
        return t("pages.document");
      case "canvas":
        return t("pages.canvas");
      case "mixed":
        return t("pages.mixed");
      case "study":
        return t("pages.study");
      default:
        return null;
    }
  })();

  const handleOpenAi = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      openWindow({
        type: "ai_panel",
        title: `AI · ${title}`,
        meta: { pageId, notebookId },
      });
    },
    [openWindow, pageId, notebookId, title],
  );

  return (
    <>
      {meta.page_icon && (
        <span
          className="wm-titlebar-meta wm-titlebar-meta--icon"
          aria-hidden="true"
        >
          {meta.page_icon}
        </span>
      )}
      {pageTypeLabel && (
        <span
          className="wm-titlebar-meta wm-titlebar-meta--type"
          title={pageTypeLabel}
        >
          {pageTypeLabel}
        </span>
      )}
      {meta.updated_at && (
        <span
          className="wm-titlebar-meta wm-titlebar-meta--time"
          title={new Date(meta.updated_at).toLocaleString()}
        >
          {formatRelativeTime(meta.updated_at)}
        </span>
      )}
      <span
        className={`wm-titlebar-save-dot${savePulse ? " is-pulsing" : ""}`}
        aria-label={t("pages.saved")}
        title={t("pages.saved")}
      />
      <button
        type="button"
        className="wm-titlebar-btn"
        onClick={handleOpenAi}
        // Shift-click hint: since ai_panel is multi-open, users can open
        // an additional panel even for the same page — kept in tooltip.
        title={t("sidebar.openAIPanel")}
        data-testid="note-open-ai-panel"
      >
        <Sparkles size={14} />
      </button>
    </>
  );
}

// ---------------------------------------------------------------------------
// Empty state (U-02)
// ---------------------------------------------------------------------------

function EmptyState() {
  const t = useTranslations("console-notebooks");
  const params = useParams<{ notebookId?: string }>();
  const notebookId = params?.notebookId || "";
  const isGuestNotebook = notebookId === "guest";
  const { openWindow } = useWindowManager();
  const [firstPage, setFirstPage] = useState<{
    id: string;
    title: string;
  } | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (isGuestNotebook) return;
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
  }, [isGuestNotebook, notebookId]);

  const handleOpenGuestDraft = useCallback(() => {
    openWindow({
      type: "guest_note",
      title: t("pages.untitled"),
      meta: { notebookId, guestPageId: "guest-draft" },
    });
  }, [notebookId, openWindow, t]);

  const handleOpenFirstPage = useCallback(() => {
    if (!firstPage || !notebookId) return;
    // U-02 — only open the page, do NOT also pop the AI panel. Users asked
    // why two windows appeared; make opening a page a single-window action.
    openWindow({
      type: "note",
      title: firstPage.title || t("common.untitled"),
      meta: { notebookId, pageId: firstPage.id },
    });
  }, [firstPage, notebookId, openWindow, t]);

  const handleCreatePage = useCallback(async () => {
    if (isGuestNotebook) {
      requestGuestRegisterGate("newPage");
      return;
    }
    if (!notebookId || creating) return;
    setCreating(true);
    try {
      const page = await apiPost<{
        id: string;
        title: string;
        page_type: string;
      }>(`/api/v1/notebooks/${notebookId}/pages`, {
        title: "",
        page_type: "document",
      });
      dispatchNotebookPagesChanged(notebookId);
      openWindow({
        type: "note",
        title: page.title || t("common.untitled"),
        meta: { notebookId, pageId: page.id },
      });
    } catch {
      /* silent */
    } finally {
      setCreating(false);
    }
  }, [isGuestNotebook, notebookId, creating, openWindow, t]);

  const handleSearch = useCallback(() => {
    if (isGuestNotebook) {
      requestGuestRegisterGate("search");
      return;
    }
    openWindow({
      type: "search",
      title: t("search.windowTitle"),
      meta: { notebookId },
    });
  }, [isGuestNotebook, notebookId, openWindow, t]);

  return (
    <div className="wm-empty-state">
      <div className="wm-empty-state-shell">
        <div className="wm-empty-state-kicker">
          <Layers size={14} />
          {t("home.kicker")}
        </div>
        <div className="wm-empty-state-icon-stack" aria-hidden="true">
          <Layers size={30} strokeWidth={1.3} />
        </div>
        <div className="wm-empty-state-title">{t("canvas.emptyTitle")}</div>
        <div className="wm-empty-state-hint">{t("canvas.emptyHint")}</div>

        <div className="wm-empty-state-actions">
          {firstPage ? (
            <button
              type="button"
              className="wm-empty-state-action wm-empty-state-action--primary"
              onClick={handleOpenFirstPage}
              data-testid="empty-canvas-open-recent-page"
            >
              <FileText size={14} />
              {t("canvas.openRecentPage")}
            </button>
          ) : null}
          {isGuestNotebook ? (
            <button
              type="button"
              className="wm-empty-state-action wm-empty-state-action--primary"
              onClick={handleOpenGuestDraft}
              data-testid="empty-canvas-open-guest-draft"
            >
              <FileText size={14} />
              {t("canvas.createFirstPage")}
            </button>
          ) : null}
          <button
            type="button"
            className="wm-empty-state-action wm-empty-state-action--primary"
            onClick={handleCreatePage}
            disabled={creating}
            data-testid="empty-canvas-create-page"
          >
            <Plus size={14} />
            {creating ? t("common.loading") : t("canvas.createFirstPage")}
          </button>
          <button
            type="button"
            className="wm-empty-state-action"
            onClick={handleSearch}
            data-testid="empty-canvas-search"
          >
            <SearchIcon size={14} />
            {t("canvas.search")}
          </button>
        </div>

        <div className="wm-empty-state-guide" aria-hidden="true">
          {[
            { icon: FileText, label: t("notebooks.title") },
            { icon: Sparkles, label: t("sidebar.openAIPanel") },
            { icon: SearchIcon, label: t("canvas.search") },
          ].map((item) => (
            <div key={item.label} className="wm-empty-state-guide-item">
              <item.icon size={14} />
              <span>{item.label}</span>
            </div>
          ))}
        </div>
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
  const visibleWindows = windows.filter((w) => !w.minimized);

  const buildNoteExtras = useCallback((w: WindowState) => {
    if (w.type !== "note" || !w.meta.pageId) return undefined;
    return (
      <NoteTitlebarExtras
        pageId={w.meta.pageId}
        notebookId={w.meta.notebookId || ""}
        title={w.title}
      />
    );
  }, []);

  return (
    <div ref={canvasRef} className="wm-canvas">
      {visibleWindows.map((w) => (
        <Window key={w.id} windowState={w} titlebarExtras={buildNoteExtras(w)}>
          <WindowContent windowState={w} />
        </Window>
      ))}

      {visibleWindows.length === 0 && <EmptyState />}
    </div>
  );
}
