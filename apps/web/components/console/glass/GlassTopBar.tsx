"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";
import { logout } from "@/lib/api";
import { useMobileMenu } from "@/components/MobileMenuProvider";

function normalizeConsolePath(pathname: string): string {
  const withoutLocale = pathname.replace(/^\/(en|zh)(?=\/|$)/, "") || "/";
  return withoutLocale.replace(/^\/workspace(?=\/|$)/, "/app");
}

export function GlassTopBar() {
  const locale = useLocale();
  const pathname = usePathname();
  const consolePath = normalizeConsolePath(pathname);
  const t = useTranslations("console");
  const tCommon = useTranslations("common");
  const { openMenu } = useMobileMenu();
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement | null>(null);

  const targetLocale = locale === "zh" ? "en" : "zh";
  const targetLabel = locale === "zh" ? "EN" : "中文";
  const showBreadcrumb = consolePath !== "/app";
  const routeKey = consolePath.startsWith("/app/notebooks")
    ? "notebooks"
    : consolePath.startsWith("/app/settings")
      ? "settings"
      : "app";
  const breadcrumbLabel = t(`breadcrumb.${routeKey}`);

  useEffect(() => {
    if (!userMenuOpen) return;

    const handlePointerDown = (event: MouseEvent | TouchEvent) => {
      if (!userMenuRef.current?.contains(event.target as Node)) {
        setUserMenuOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setUserMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("touchstart", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("touchstart", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [userMenuOpen]);

  return (
    <header
      className="glass-topbar site-header-v2 is-console"
      style={{
        position: "fixed",
        top: 0,
        left: 56,
        right: 0,
        height: 56,
        background: "var(--console-topbar)",
        backdropFilter: "blur(24px)",
        WebkitBackdropFilter: "blur(24px)",
        borderBottom: "1px solid var(--console-border-subtle)",
        boxShadow: "0 1px 0 rgba(255,255,255,0.5)",
        zIndex: 45,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 16px",
      }}
    >
      <div
        className="console-topbar-compat"
        style={{
          flex: 1,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
        }}
      >
        <div className="inline-topbar-left" style={{ gap: 16 }}>
          <button
            type="button"
            className="glass-topbar-menu-btn inline-topbar-menu"
            onClick={openMenu}
            aria-label={t("topbar.openMenu")}
            style={{
              background: "none",
              border: "none",
              color: "var(--console-text-primary)",
              cursor: "pointer",
              padding: 8,
              display: "none",
            }}
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>

          <Link
            href="/"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              textDecoration: "none",
              color: "var(--console-text-primary)",
            }}
          >
            <span
              style={{
                fontWeight: 800,
                fontSize: 14,
                letterSpacing: "-0.01em",
              }}
            >
              {tCommon("brand.short")}
            </span>
          </Link>

          {showBreadcrumb ? (
            <div className="inline-topbar-breadcrumb" aria-label="Breadcrumb">
              <span>{breadcrumbLabel}</span>
            </div>
          ) : null}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button
            className="glass-topbar-cmdk"
            type="button"
            style={{
              background: "rgba(255,255,255,0.72)",
              border: "1px solid var(--console-border-subtle)",
              borderRadius: 999,
              padding: "8px 12px",
              color: "var(--console-text-secondary)",
              cursor: "pointer",
              fontSize: 12,
            }}
          >
            <kbd>⌘K</kbd>
          </button>

          <Link
            href={pathname}
            locale={targetLocale}
            className="glass-topbar-lang"
            style={{
              fontSize: 12,
              color: "var(--console-text-secondary)",
              textDecoration: "none",
              padding: "8px 10px",
              borderRadius: 999,
            }}
          >
            {targetLabel}
          </Link>

          <div ref={userMenuRef} style={{ position: "relative" }}>
            <button
              className="glass-topbar-avatar"
              type="button"
              aria-haspopup="menu"
              aria-expanded={userMenuOpen}
              aria-label="User menu"
              onClick={() => setUserMenuOpen((open) => !open)}
              style={{
                width: 36,
                height: 36,
                borderRadius: "50%",
                background:
                  "linear-gradient(135deg, var(--console-accent), var(--console-accent-secondary))",
                border: "1px solid rgba(255,255,255,0.75)",
                color: "#fff",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 12,
                fontWeight: 500,
              }}
            >
              U
            </button>
            {userMenuOpen ? (
              <div
                role="menu"
                className="glass-topbar-user-menu"
                style={{
                  position: "absolute",
                  top: "calc(100% + 10px)",
                  right: 0,
                  minWidth: 156,
                  padding: 6,
                  borderRadius: 14,
                  border: "1px solid var(--console-border-subtle)",
                  background: "rgba(255, 255, 255, 0.94)",
                  boxShadow: "0 24px 60px rgba(15, 118, 110, 0.16)",
                  backdropFilter: "blur(20px)",
                  WebkitBackdropFilter: "blur(20px)",
                  zIndex: 70,
                }}
              >
                <Link
                  href="/app/settings"
                  role="menuitem"
                  onClick={() => setUserMenuOpen(false)}
                  style={{
                    display: "block",
                    borderRadius: 10,
                    padding: "9px 10px",
                    color: "var(--console-text-primary)",
                    textDecoration: "none",
                    fontSize: 13,
                    fontWeight: 700,
                  }}
                >
                  {tCommon("user.settings")}
                </Link>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setUserMenuOpen(false);
                    void logout();
                  }}
                  style={{
                    width: "100%",
                    border: "none",
                    borderRadius: 10,
                    background: "transparent",
                    padding: "9px 10px",
                    color: "var(--console-text-secondary)",
                    cursor: "pointer",
                    fontSize: 13,
                    fontWeight: 700,
                    textAlign: "left",
                  }}
                >
                  {tCommon("user.logout")}
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </div>

      {/* Mobile menu button visibility via CSS */}
      <style>{`
        .glass-topbar-menu-btn {
          display: none !important;
        }
        @media (max-width: 768px) {
          .glass-topbar-menu-btn {
            display: flex !important;
          }
          .glass-topbar {
            left: 0 !important;
          }
        }
      `}</style>
    </header>
  );
}
