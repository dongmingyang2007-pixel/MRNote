"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import clsx from "clsx";
import { Link, usePathname } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useProjectContext } from "@/lib/ProjectContext";
import { buildProjectDisplayMap } from "@/lib/project-display";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  HomeIcon,
  NotebooksIcon,
} from "./NavIcons";

interface NavItem {
  href: string;
  key: string;
  Icon: () => JSX.Element;
}

/* ── Icons ── */

function SettingsIcon() {
  return (
    <svg
      width={20}
      height={20}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx={12} cy={12} r={3} />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

function FolderIcon() {
  return (
    <svg
      width={16}
      height={16}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
    </svg>
  );
}

/* ── Nav items ── */

const NAV_ITEMS: NavItem[] = [
  { href: "/app", key: "nav.home", Icon: HomeIcon },
  { href: "/app/notebooks", key: "nav.notebooks", Icon: NotebooksIcon },
];

/* ── Component ── */

export function Sidebar() {
  const pathname = usePathname();
  const t = useTranslations("console");
  const tCommon = useTranslations("common");
  const { projects } = useProjectContext();
  const [showExpanded, setShowExpanded] = useState(false);
  const [animState, setAnimState] = useState<"idle" | "opening" | "closing">(
    "idle",
  );
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const displayMap = buildProjectDisplayMap(projects);

  const isActive = (href: string) => {
    if (href === "/app") return pathname === "/app";
    return pathname.startsWith(href);
  };

  const handleExpand = useCallback(() => {
    if (closeTimer.current) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
    setShowExpanded(true);
    setAnimState("opening");
  }, []);

  const handleImmediateCollapse = useCallback(() => {
    if (closeTimer.current) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
    setShowExpanded(false);
    setAnimState("idle");
  }, []);

  const handleCollapse = useCallback(() => {
    if (closeTimer.current) {
      clearTimeout(closeTimer.current);
    }
    setAnimState("closing");
    closeTimer.current = setTimeout(() => {
      setShowExpanded(false);
      setAnimState("idle");
      closeTimer.current = null;
    }, 220);
  }, []);

  useEffect(() => {
    return () => {
      if (closeTimer.current) {
        clearTimeout(closeTimer.current);
      }
    };
  }, []);

  return (
    <TooltipProvider delayDuration={300}>
      {/* Collapsed sidebar -- always visible */}
      <nav
        className={clsx("glass-sidebar", "glass-sidebar--collapsed")}
        role="navigation"
        aria-label="Main"
        onMouseEnter={handleExpand}
      >
        {/* Logo */}
        <div className="glass-sidebar-logo">{tCommon("brand.glyph")}</div>

        {/* Nav items */}
        <div className="glass-sidebar-nav">
          {NAV_ITEMS.map((item) => (
            <Tooltip key={item.href}>
              <TooltipTrigger asChild>
                <Link
                  href={item.href}
                  prefetch={false}
                  className={clsx(
                    "glass-sidebar-nav-item",
                    isActive(item.href) && "is-active",
                  )}
                  aria-current={isActive(item.href) ? "page" : undefined}
                  aria-label={t(item.key)}
                  onClick={handleImmediateCollapse}
                >
                  <span className="glass-sidebar-icon">
                    <item.Icon />
                  </span>
                </Link>
              </TooltipTrigger>
              <TooltipContent side="right" sideOffset={8}>
                {t(item.key)}
              </TooltipContent>
            </Tooltip>
          ))}
        </div>

        {/* New assistant button */}
        <div style={{ padding: "8px 0" }}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Link
                href="/app/notebooks"
                prefetch={false}
                className="glass-sidebar-nav-item"
                style={{
                  background:
                    "var(--console-accent-soft, rgba(37,99,235,0.1))",
                  color: "var(--console-accent, #2563EB)",
                }}
                aria-label={t("sidebar.newProject")}
                onClick={handleImmediateCollapse}
              >
                <span
                  className="glass-sidebar-icon"
                  style={{ color: "var(--console-accent, #2563EB)" }}
                >
                  <svg
                    width={18}
                    height={18}
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <line x1="12" y1="5" x2="12" y2="19" />
                    <line x1="5" y1="12" x2="19" y2="12" />
                  </svg>
                </span>
              </Link>
            </TooltipTrigger>
            <TooltipContent side="right" sideOffset={8}>
              {t("sidebar.newProject")}
            </TooltipContent>
          </Tooltip>
        </div>

        {/* Settings */}
        <div className="glass-sidebar-footer">
          <Tooltip>
            <TooltipTrigger asChild>
              <Link
                href="/app/settings"
                prefetch={false}
                className={clsx(
                  "glass-sidebar-nav-item",
                  isActive("/app/settings") && "is-active",
                )}
                aria-current={isActive("/app/settings") ? "page" : undefined}
                aria-label={t("nav.settings")}
                onClick={handleImmediateCollapse}
              >
                <span className="glass-sidebar-icon">
                  <SettingsIcon />
                </span>
              </Link>
            </TooltipTrigger>
            <TooltipContent side="right" sideOffset={8}>
              {t("nav.settings")}
            </TooltipContent>
          </Tooltip>
        </div>
      </nav>

      {/* Expanded overlay sidebar — animated */}
      {showExpanded && (
        <>
          {/* Backdrop overlay */}
          <div
            className={clsx(
              "glass-sidebar-overlay",
              animState === "closing" && "glass-sidebar-overlay--closing",
            )}
            onClick={handleCollapse}
            aria-hidden="true"
          />

          {/* Expanded sidebar */}
          <nav
            className={clsx(
              "glass-sidebar",
              "glass-sidebar--expanded",
              animState === "opening" && "glass-sidebar--opening",
              animState === "closing" && "glass-sidebar--closing",
            )}
            role="navigation"
            aria-label="Main expanded"
            onMouseLeave={handleCollapse}
          >
            {/* Header */}
            <div className="glass-sidebar-header">
              <div className="glass-sidebar-logo">{tCommon("brand.glyph")}</div>
              <div className="glass-sidebar-header-text">
                <div className="glass-sidebar-brand">{tCommon("brand.company")}</div>
                <div className="glass-sidebar-subtitle">{tCommon("brand.tagline")}</div>
              </div>
            </div>

            {/* Full nav items */}
            <div className="glass-sidebar-nav-full">
              {NAV_ITEMS.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  prefetch={false}
                  className={clsx(
                    "glass-sidebar-nav-item-full",
                    isActive(item.href) && "is-active",
                  )}
                  aria-current={isActive(item.href) ? "page" : undefined}
                  onClick={handleCollapse}
                >
                  <span className="glass-sidebar-icon">
                    <item.Icon />
                  </span>
                  <span className="glass-sidebar-label">{t(item.key)}</span>
                </Link>
              ))}
            </div>

            {/* Divider */}
            <div className="glass-sidebar-divider" />

            {/* Projects section */}
            <div className="glass-sidebar-projects">
              <div className="glass-sidebar-projects-title">
                {t("sidebar.projects")}
                {projects.length > 0 && (
                  <span className="glass-sidebar-projects-count">
                    {projects.length}
                  </span>
                )}
              </div>
              <div className="glass-sidebar-projects-list">
                {projects.length === 0 ? (
                  <span
                    className="glass-sidebar-projects-empty"
                    style={{
                      color: "var(--console-text-faint, #9ca3af)",
                    }}
                  >
                    {t("sidebar.noProjects")}
                  </span>
                ) : (
                  projects.map((project) => (
                    <span
                      key={project.id}
                      className="glass-sidebar-project-item"
                      style={{ color: "inherit" }}
                    >
                      <span className="glass-sidebar-project-icon">
                        <FolderIcon />
                      </span>
                      <span className="glass-sidebar-project-name">
                        {displayMap.get(project.id) ?? project.name}
                      </span>
                    </span>
                  ))
                )}
              </div>
            </div>

            {/* Footer */}
            <div className="glass-sidebar-footer-full">
              <Link
                href="/app/settings"
                prefetch={false}
                className={clsx(
                  "glass-sidebar-nav-item-full",
                  isActive("/app/settings") && "is-active",
                )}
                aria-current={isActive("/app/settings") ? "page" : undefined}
                onClick={handleCollapse}
              >
                <span className="glass-sidebar-icon">
                  <SettingsIcon />
                </span>
                <span className="glass-sidebar-label">{t("nav.settings")}</span>
              </Link>
            </div>
          </nav>
        </>
      )}
    </TooltipProvider>
  );
}
