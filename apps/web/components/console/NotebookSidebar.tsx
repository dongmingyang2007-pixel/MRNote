"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowLeft, FileText, MessageSquare, Brain, BookOpen, Settings } from "lucide-react";
import { apiGet } from "@/lib/api";

type SideTab = "pages" | "chat" | "memory" | "learn" | null;

interface NotebookSidebarProps {
  notebookId: string;
  notebookTitle?: string;
}

const TABS = [
  { id: "pages" as const, Icon: FileText, key: "nav.pages" },
  { id: "chat" as const, Icon: MessageSquare, key: "nav.chat" },
  { id: "memory" as const, Icon: Brain, key: "nav.memory" },
  { id: "learn" as const, Icon: BookOpen, key: "nav.learn" },
] as const;

export default function NotebookSidebar({ notebookId, notebookTitle }: NotebookSidebarProps) {
  const pathname = usePathname();
  const t = useTranslations("console");
  const tn = useTranslations("console-notebooks");
  const [activeTab, setActiveTab] = useState<SideTab>("pages");
  const [pages, setPages] = useState<Array<{ id: string; title: string; page_type: string }>>([]);

  useEffect(() => {
    void apiGet<{ items: Array<{ id: string; title: string; page_type: string }> }>(
      `/api/v1/notebooks/${notebookId}/pages`,
    )
      .then((data) => setPages(data.items || []))
      .catch(() => setPages([]));
  }, [notebookId]);

  const basePath = `/app/notebooks/${notebookId}`;

  const isRouteActive = (tabId: string) => {
    if (tabId === "pages") {
      return pathname === basePath ||
        pathname.endsWith(`/notebooks/${notebookId}`) ||
        pathname.includes(`/notebooks/${notebookId}/pages/`);
    }
    if (tabId === "chat") return pathname.includes(`/notebooks/${notebookId}/chat`);
    if (tabId === "memory") return pathname.includes(`/notebooks/${notebookId}/memory`);
    if (tabId === "learn") return pathname.includes(`/notebooks/${notebookId}/learn`);
    return false;
  };

  const handleTabClick = useCallback((tabId: SideTab) => {
    setActiveTab((prev) => (prev === tabId ? null : tabId));
  }, []);

  const panelOpen = activeTab !== null;

  return (
    <div style={{ display: "flex", height: "100%" }}>
      {/* 56px icon rail */}
      <nav
        className="glass-sidebar glass-sidebar--collapsed"
        style={{
          position: "relative",
          width: 56,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          paddingTop: 12,
          paddingBottom: 12,
          gap: 4,
          flexShrink: 0,
          zIndex: 2,
        }}
      >
        {/* Back button */}
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

        {/* Tab icons */}
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`glass-sidebar-nav-item${isRouteActive(tab.id) || activeTab === tab.id ? " is-active" : ""}`}
            title={t(tab.key)}
            aria-label={t(tab.key)}
            onClick={() => handleTabClick(tab.id)}
          >
            <tab.Icon size={20} strokeWidth={1.8} />
          </button>
        ))}

        {/* Spacer */}
        <div style={{ flex: 1 }} />

        {/* Settings */}
        <Link
          href={`${basePath}/settings`}
          prefetch={false}
          className={`glass-sidebar-nav-item${pathname.includes("/settings") ? " is-active" : ""}`}
          title={t("nav.notebookSettings")}
          aria-label={t("nav.notebookSettings")}
        >
          <Settings size={20} strokeWidth={1.8} />
        </Link>
      </nav>

      {/* 240px expandable panel */}
      {panelOpen && (
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
          {/* Panel header */}
          <div style={{
            fontSize: "0.6875rem",
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
            color: "var(--console-text-muted, #6b7280)",
            marginBottom: 12,
          }}>
            {activeTab && t(`nav.${activeTab}` as "nav.pages")}
          </div>

          {/* Panel content based on active tab */}
          {activeTab === "pages" && (
            <div style={{ fontSize: "0.8125rem" }}>
              {pages.map((page) => (
                <Link
                  key={page.id}
                  href={`${basePath}/pages/${page.id}`}
                  prefetch={false}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "6px 12px",
                    borderRadius: 6,
                    color: "var(--console-text-primary, #1a1a2e)",
                    textDecoration: "none",
                    fontSize: "0.8125rem",
                    transition: "background 100ms ease",
                  }}
                >
                  <FileText size={14} />
                  {page.title || tn("common.untitled")}
                </Link>
              ))}
              <Link
                href={basePath}
                prefetch={false}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "8px 12px",
                  borderRadius: 6,
                  color: "var(--console-accent, #2563EB)",
                  textDecoration: "none",
                  fontSize: "0.8125rem",
                  fontWeight: 500,
                  marginTop: 8,
                }}
              >
                + {tn("pages.create")}
              </Link>
            </div>
          )}

          {activeTab === "chat" && (
            <div style={{ fontSize: "0.8125rem" }}>
              <Link
                href={`${basePath}/chat`}
                prefetch={false}
                style={{
                  display: "block",
                  padding: "8px 12px",
                  borderRadius: 8,
                  color: "var(--console-text-primary, #1a1a2e)",
                  textDecoration: "none",
                }}
              >
                {tn("sidebar.openChat")}
              </Link>
            </div>
          )}

          {activeTab === "memory" && (
            <div style={{ fontSize: "0.8125rem" }}>
              <Link
                href={`${basePath}/memory`}
                prefetch={false}
                style={{
                  display: "block",
                  padding: "8px 12px",
                  borderRadius: 8,
                  color: "var(--console-text-primary, #1a1a2e)",
                  textDecoration: "none",
                }}
              >
                {tn("sidebar.openMemory")}
              </Link>
            </div>
          )}

          {activeTab === "learn" && (
            <div style={{
              fontSize: "0.8125rem",
              color: "var(--console-text-muted, #6b7280)",
              padding: "8px 12px",
            }}>
              {tn("sidebar.comingSoon")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
