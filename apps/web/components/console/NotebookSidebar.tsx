"use client";

import { useCallback, useEffect, useState } from "react";
import { Link, usePathname } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import {
  ArrowLeft,
  Bell,
  FileText,
  Sparkles,
  Brain,
  Network,
  BookOpen,
  FolderOpen,
  Settings,
  Search,
  PanelLeftClose,
  PanelLeftOpen,
  X,
} from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import {
  useWindowManager,
  useWindows,
} from "@/components/notebook/WindowManager";
import { useDigestUnreadCount } from "@/hooks/useDigestUnreadCount";
import { useBillingMe } from "@/hooks/useBillingMe";
import MinimizedTray from "@/components/notebook/MinimizedTray";
import { requestGuestRegisterGate } from "@/components/console/GuestRegisterGate";
import {
  NOTEBOOK_PAGES_CHANGED_EVENT,
  dispatchNotebookPagesChanged,
} from "@/lib/notebook-events";

type SideTab =
  | "pages"
  | "ai_panel"
  | "memory"
  | "memory_graph"
  | "references"
  | "learn"
  | "digest"
  | "search"
  | null;

interface NotebookSidebarProps {
  notebookId: string;
  guestMode?: boolean;
}

const TABS = [
  { id: "pages" as const, Icon: FileText, key: "nav.pages" },
  { id: "search" as const, Icon: Search, key: "nav.search" },
  { id: "ai_panel" as const, Icon: Sparkles, key: "nav.aiPanel" },
  { id: "memory" as const, Icon: Brain, key: "nav.memory" },
  { id: "memory_graph" as const, Icon: Network, key: "nav.memoryGraph" },
  { id: "references" as const, Icon: FolderOpen, key: "nav.references" },
  { id: "learn" as const, Icon: BookOpen, key: "nav.learn" },
  { id: "digest" as const, Icon: Bell, key: "nav.digest" },
] as const;

export default function NotebookSidebar(props: NotebookSidebarProps) {
  if (props.guestMode) {
    return <GuestNotebookSidebar notebookId={props.notebookId} />;
  }
  return <AuthenticatedNotebookSidebar notebookId={props.notebookId} />;
}

function GuestNotebookSidebar({ notebookId }: { notebookId: string }) {
  const t = useTranslations("console");
  const tn = useTranslations("console-notebooks");
  const { openWindow } = useWindowManager();

  const openDraft = useCallback(() => {
    openWindow({
      type: "guest_note",
      title: tn("pages.untitled"),
      meta: { notebookId, guestPageId: "guest-draft" },
    });
  }, [notebookId, openWindow, tn]);

  return (
    <div style={{ display: "flex", height: "100%" }}>
      <nav
        className="glass-sidebar glass-sidebar--collapsed"
        style={{
          position: "fixed",
          top: 56,
          left: 0,
          bottom: 0,
          width: 56,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          paddingTop: 12,
          paddingBottom: 12,
          gap: 4,
          flexShrink: 0,
          zIndex: 40,
        }}
      >
        <Link
          href="/app/notebooks"
          prefetch={false}
          className="glass-sidebar-nav-item"
          title={t("nav.back")}
          aria-label={t("nav.back")}
          style={{ marginBottom: 12 }}
        >
          <ArrowLeft size={20} strokeWidth={1.8} />
        </Link>

        <button
          type="button"
          className="glass-sidebar-nav-item is-active"
          title={t("nav.pages")}
          aria-label={t("nav.pages")}
          onClick={openDraft}
        >
          <FileText size={20} strokeWidth={2} />
        </button>
        <button
          type="button"
          className="glass-sidebar-nav-item"
          title={t("nav.search")}
          aria-label={t("nav.search")}
          onClick={() => requestGuestRegisterGate("search")}
        >
          <Search size={20} strokeWidth={1.8} />
        </button>
        <button
          type="button"
          className="glass-sidebar-nav-item"
          title={t("nav.aiPanel")}
          aria-label={t("nav.aiPanel")}
          onClick={() => requestGuestRegisterGate("ai")}
        >
          <Sparkles size={20} strokeWidth={1.8} />
        </button>
        <button
          type="button"
          className="glass-sidebar-nav-item"
          title={t("nav.memory")}
          aria-label={t("nav.memory")}
          onClick={() => requestGuestRegisterGate("memory")}
        >
          <Brain size={20} strokeWidth={1.8} />
        </button>
        <button
          type="button"
          className="glass-sidebar-nav-item"
          title={t("nav.memoryGraph")}
          aria-label={t("nav.memoryGraph")}
          onClick={() => requestGuestRegisterGate("memory")}
        >
          <Network size={20} strokeWidth={1.8} />
        </button>
        <button
          type="button"
          className="glass-sidebar-nav-item"
          title={t("nav.references")}
          aria-label={t("nav.references")}
          onClick={() => requestGuestRegisterGate("upload")}
        >
          <FolderOpen size={20} strokeWidth={1.8} />
        </button>
        <button
          type="button"
          className="glass-sidebar-nav-item"
          title={t("nav.learn")}
          aria-label={t("nav.learn")}
          onClick={() => requestGuestRegisterGate("upload")}
        >
          <BookOpen size={20} strokeWidth={1.8} />
        </button>
        <button
          type="button"
          className="glass-sidebar-nav-item"
          title={t("nav.digest")}
          aria-label={t("nav.digest")}
          onClick={() => requestGuestRegisterGate("digest")}
        >
          <Bell size={20} strokeWidth={1.8} />
        </button>

        <div style={{ flex: 1 }} />
        <MinimizedTray />
        <button
          type="button"
          className="glass-sidebar-nav-item"
          title={t("nav.notebookSettings")}
          aria-label={t("nav.notebookSettings")}
          onClick={() => requestGuestRegisterGate("settings")}
        >
          <Settings size={20} strokeWidth={1.8} />
        </button>
      </nav>

      <div
        className="notebook-side-panel"
        style={{
          width: 240,
          borderRight: "1px solid var(--console-border, rgba(255,255,255,0.7))",
          background: "rgba(255, 255, 255, 0.55)",
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
          overflowY: "auto",
          padding: "16px 12px",
          flexShrink: 0,
        }}
      >
        <div
          style={{
            fontSize: "0.6875rem",
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
            color: "var(--console-text-muted, #6b7280)",
            marginBottom: 12,
          }}
        >
          {t("nav.pages")}
        </div>
        <button
          type="button"
          onClick={openDraft}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "8px 12px",
            borderRadius: 8,
            color: "var(--console-text-primary, #1a1a2e)",
            background: "rgba(13, 148, 136, 0.1)",
            border: "none",
            cursor: "pointer",
            fontSize: "0.8125rem",
            fontWeight: 700,
            width: "100%",
            textAlign: "left",
          }}
        >
          <FileText size={14} />
          {tn("pages.untitled")}
        </button>
        <button
          type="button"
          onClick={() => requestGuestRegisterGate("newPage")}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "8px 12px",
            borderRadius: 6,
            color: "var(--console-accent, #0D9488)",
            background: "none",
            border: "none",
            cursor: "pointer",
            fontSize: "0.8125rem",
            fontWeight: 500,
            marginTop: 8,
            width: "100%",
            textAlign: "left",
          }}
        >
          + {tn("pages.create")}
        </button>
      </div>
    </div>
  );
}

function AuthenticatedNotebookSidebar({ notebookId }: NotebookSidebarProps) {
  const pathname = usePathname();
  const t = useTranslations("console");
  const tn = useTranslations("console-notebooks");
  const [activeTab, setActiveTab] = useState<SideTab>(null);
  const [collapsed, setCollapsed] = useState(false);

  // Hydrate collapsed state from localStorage on mount.
  useEffect(() => {
    try {
      const v = localStorage.getItem("mrai.notebook-sidebar.collapsed");
      if (v === "1") setCollapsed(true);
    } catch {
      /* ignore */
    }
  }, []);
  const setCollapsedPersist = useCallback((next: boolean) => {
    setCollapsed(next);
    try {
      localStorage.setItem("mrai.notebook-sidebar.collapsed", next ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, []);
  const [pages, setPages] = useState<
    Array<{ id: string; title: string; page_type: string }>
  >([]);
  const [creatingPage, setCreatingPage] = useState(false);

  const loadPages = useCallback(async () => {
    try {
      const data = await apiGet<{
        items: Array<{ id: string; title: string; page_type: string }>;
      }>(`/api/v1/notebooks/${notebookId}/pages`);
      setPages(data.items || []);
    } catch {
      setPages([]);
    }
  }, [notebookId]);

  useEffect(() => {
    void loadPages();
  }, [loadPages]);

  useEffect(() => {
    const handlePagesChanged = (event: Event) => {
      const detail = (event as CustomEvent<{ notebookId?: string }>).detail;
      if (!detail?.notebookId || detail.notebookId === notebookId) {
        void loadPages();
      }
    };
    window.addEventListener(NOTEBOOK_PAGES_CHANGED_EVENT, handlePagesChanged);
    return () => {
      window.removeEventListener(
        NOTEBOOK_PAGES_CHANGED_EVENT,
        handlePagesChanged,
      );
    };
  }, [loadPages, notebookId]);

  const basePath = `/app/notebooks/${notebookId}`;

  const isRouteActive = (tabId: string) => {
    if (tabId === "pages") {
      return (
        pathname === basePath ||
        pathname.endsWith(`/notebooks/${notebookId}`) ||
        pathname.includes(`/notebooks/${notebookId}/pages/`)
      );
    }
      if (tabId === "memory")
      return pathname.includes(`/notebooks/${notebookId}/memory`);
    if (tabId === "references")
      return pathname.includes(`/notebooks/${notebookId}/references`);
    if (tabId === "learn")
      return pathname.includes(`/notebooks/${notebookId}/learn`);
    return false;
  };

  const { openWindow } = useWindowManager();

  const handleCreatePage = useCallback(async () => {
    if (creatingPage) return;
    setCreatingPage(true);
    try {
      const page = await apiPost<{
        id: string;
        title: string;
        page_type: string;
      }>(`/api/v1/notebooks/${notebookId}/pages`, {
        title: "",
        page_type: "document",
      });
      setPages((prev) => [page, ...prev]);
      dispatchNotebookPagesChanged(notebookId);
      openWindow({
        type: "note",
        title: page.title || tn("common.untitled"),
        meta: { notebookId, pageId: page.id },
      });
    } catch {
      /* ignore */
    } finally {
      setCreatingPage(false);
    }
  }, [creatingPage, notebookId, openWindow, tn]);
  const windows = useWindows();
  const unreadCount = useDigestUnreadCount();
  const billingMe = useBillingMe();

  const handleTabClick = useCallback(
    (tabId: SideTab) => {
      if (tabId === "pages") {
        setActiveTab((prev) => (prev === tabId ? null : tabId));
        return;
      }
      if (tabId === "ai_panel") {
        // Spec §4.7 — find the focused, non-minimized note window.
        const focusedNote = [...windows]
          .filter((w) => w.type === "note" && !w.minimized && w.meta.pageId)
          .sort((a, b) => b.zIndex - a.zIndex)[0];
        if (!focusedNote) {
          console.warn(
            "ai-panel-sidebar: no focused note window; open a page first",
          );
          return;
        }
        openWindow({
          type: "ai_panel",
          title: `AI · ${focusedNote.title}`,
          meta: {
            pageId: focusedNote.meta.pageId || "",
            notebookId: focusedNote.meta.notebookId || notebookId,
          },
        });
        return;
      }
      if (tabId === "memory") {
        openWindow({
          type: "memory",
          title: tn("sidebar.openMemory"),
          meta: { notebookId },
        });
      } else if (tabId === "memory_graph") {
        openWindow({
          type: "memory_graph",
          title: tn("memoryGraph.title"),
          meta: { notebookId },
        });
      } else if (tabId === "references") {
        openWindow({
          type: "references",
          title: tn("references.windowTitle"),
          meta: { notebookId },
        });
      } else if (tabId === "learn") {
        openWindow({
          type: "study",
          title: "Study",
          meta: { notebookId },
        });
      } else if (tabId === "digest") {
        openWindow({
          type: "digest",
          title: tn("digest.windowTitle"),
          meta: { notebookId },
        });
      } else if (tabId === "search") {
        openWindow({
          type: "search",
          title: tn("search.windowTitle"),
          meta: { notebookId },
        });
      }
    },
    [openWindow, notebookId, tn, windows],
  );

  const panelOpen = activeTab === "pages";

  // When collapsed: render only a floating expand button at top-left.
  if (collapsed) {
    return (
      <button
        type="button"
        data-testid="sidebar-expand"
        onClick={() => setCollapsedPersist(false)}
        title={t("nav.expandSidebar")}
        aria-label={t("nav.expandSidebar")}
        style={{
          position: "fixed",
          top: 64,
          left: 8,
          width: 32,
          height: 32,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "rgba(255,255,255,0.9)",
          backdropFilter: "blur(12px)",
          border: "1px solid rgba(15,42,45,0.1)",
          borderRadius: 10,
          color: "var(--console-text-primary, #0f172a)",
          cursor: "pointer",
          zIndex: 40,
        }}
      >
        <PanelLeftOpen size={16} strokeWidth={1.8} />
      </button>
    );
  }

  return (
    <div style={{ display: "flex", height: "100%" }}>
      {/* 56px icon rail */}
      <nav
        className="glass-sidebar glass-sidebar--collapsed"
        style={{
          position: "fixed",
          top: 56,
          left: 0,
          bottom: 0,
          width: 56,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          paddingTop: 12,
          paddingBottom: 12,
          gap: 4,
          flexShrink: 0,
          zIndex: 40,
        }}
      >
        <Link
          href="/app/notebooks"
          prefetch={false}
          className="glass-sidebar-nav-item"
          title={t("nav.back")}
          aria-label={t("nav.back")}
          style={{ marginBottom: 12 }}
        >
          <ArrowLeft size={20} strokeWidth={1.8} />
        </Link>

        {TABS.map((tab) => {
          const active = isRouteActive(tab.id) || activeTab === tab.id;
          // U-21 — AI tab tooltip describes multi-open behavior so first-time
          // users discover they can bind separate panels to separate pages.
          const tooltip =
            tab.id === "ai_panel"
              ? `${t(tab.key)} · ${tn("sidebar.aiPanelHint")}`
              : t(tab.key);
          return (
            <button
              key={tab.id}
              type="button"
              data-testid={`sidebar-tab-${tab.id}`}
              className={`glass-sidebar-nav-item${active ? " is-active" : ""}`}
              title={tooltip}
              aria-label={tooltip}
              aria-current={active ? "page" : undefined}
              onClick={() => handleTabClick(tab.id)}
              style={{ position: "relative" }}
            >
              <tab.Icon size={20} strokeWidth={active ? 2 : 1.8} />
              {tab.id === "digest" && unreadCount > 0 && (
                <span
                  data-testid="sidebar-digest-badge"
                  style={{
                    position: "absolute",
                    top: 4,
                    right: 4,
                    minWidth: 14,
                    height: 14,
                    borderRadius: 999,
                    background: "#ef4444",
                    color: "#fff",
                    fontSize: 9,
                    lineHeight: "14px",
                    textAlign: "center",
                    padding: "0 3px",
                    fontWeight: 700,
                  }}
                >
                  {unreadCount > 99 ? "99+" : unreadCount}
                </span>
              )}
            </button>
          );
        })}

        <div style={{ flex: 1 }} />

        <button
          type="button"
          data-testid="sidebar-collapse"
          onClick={() => setCollapsedPersist(true)}
          className="glass-sidebar-nav-item"
          title={t("nav.collapseSidebar")}
          aria-label={t("nav.collapseSidebar")}
          style={{ marginBottom: 8 }}
        >
          <PanelLeftClose size={18} strokeWidth={1.8} />
        </button>

        <MinimizedTray />

        <Link
          href={`${basePath}/settings`}
          prefetch={false}
          className={`glass-sidebar-nav-item${
            pathname.includes("/settings") ? " is-active" : ""
          }`}
          title={t("nav.notebookSettings")}
          aria-label={t("nav.notebookSettings")}
          style={{ position: "relative" }}
        >
          <Settings
            size={20}
            strokeWidth={pathname.includes("/settings") ? 2 : 1.8}
          />
          {billingMe && billingMe.plan !== "free" && (
            <span
              data-testid="sidebar-plan-badge"
              style={{
                position: "absolute",
                bottom: 4,
                right: 4,
                background: "var(--console-accent, #0D9488)",
                color: "#fff",
                fontSize: 8,
                fontWeight: 700,
                padding: "1px 4px",
                borderRadius: 3,
                lineHeight: 1,
              }}
            >
              {billingMe.plan.toUpperCase()}
            </span>
          )}
        </Link>
      </nav>

      {panelOpen && (
        <div
          className="notebook-side-panel"
          style={{
            width: 240,
            borderRight:
              "1px solid var(--console-border, rgba(255,255,255,0.7))",
            background: "rgba(255, 255, 255, 0.55)",
            backdropFilter: "blur(16px)",
            WebkitBackdropFilter: "blur(16px)",
            overflowY: "auto",
            padding: "16px 12px",
            flexShrink: 0,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              fontSize: "0.6875rem",
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
              color: "var(--console-text-muted, #6b7280)",
              marginBottom: 12,
            }}
          >
            <span>{t("nav.pages")}</span>
            <button
              type="button"
              data-testid="sidebar-panel-close"
              onClick={() => setActiveTab(null)}
              title={tn("sidebar.closePanel")}
              aria-label={tn("sidebar.closePanel")}
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: 22,
                height: 22,
                border: "none",
                borderRadius: 6,
                background: "transparent",
                cursor: "pointer",
                color: "var(--console-text-muted, #6b7280)",
              }}
            >
              <X size={13} strokeWidth={1.8} />
            </button>
          </div>

          <div style={{ fontSize: "0.8125rem" }}>
            {pages.map((page) => (
              <button
                key={page.id}
                type="button"
                onClick={() =>
                  openWindow({
                    type: "note",
                    title: page.title || tn("common.untitled"),
                    meta: { notebookId, pageId: page.id },
                  })
                }
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "6px 12px",
                  borderRadius: 6,
                  color: "var(--console-text-primary, #1a1a2e)",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  fontSize: "0.8125rem",
                  transition: "background 100ms ease",
                  width: "100%",
                  textAlign: "left",
                }}
              >
                <FileText size={14} />
                {page.title || tn("common.untitled")}
              </button>
            ))}
            <button
              type="button"
              onClick={handleCreatePage}
              disabled={creatingPage}
              data-testid="notebook-sidebar-create-page"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "8px 12px",
                borderRadius: 6,
                color: "var(--console-accent, var(--console-accent, #0D9488))",
                background: "none",
                border: "none",
                cursor: creatingPage ? "default" : "pointer",
                fontSize: "0.8125rem",
                fontWeight: 500,
                marginTop: 8,
                width: "100%",
                textAlign: "left",
                opacity: creatingPage ? 0.6 : 1,
              }}
            >
              + {tn("pages.create")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
