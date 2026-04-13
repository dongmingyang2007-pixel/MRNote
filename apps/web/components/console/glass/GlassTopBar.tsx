"use client";

import { useLocale, useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";
import { logout } from "@/lib/api";
import { useMobileMenu } from "@/components/MobileMenuProvider";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export function GlassTopBar() {
  const locale = useLocale();
  const pathname = usePathname();
  const t = useTranslations("console");
  const tCommon = useTranslations("common");
  const { openMenu } = useMobileMenu();

  const targetLocale = locale === "zh" ? "en" : "zh";
  const targetLabel = locale === "zh" ? "EN" : "中文";
  const showBreadcrumb = pathname !== "/app";
  const routeKey = pathname.startsWith("/app/notebooks")
    ? "notebooks"
    : pathname.startsWith("/app/settings")
      ? "settings"
      : "app";
  const breadcrumbLabel = t(`breadcrumb.${routeKey}`);

  return (
    <header
      className="glass-topbar site-header-v2 is-console"
      style={{
        position: "fixed",
        top: 0,
        left: 56,
        right: 0,
        height: 48,
        background: "var(--console-topbar)",
        backdropFilter: "blur(16px)",
        WebkitBackdropFilter: "blur(16px)",
        borderBottom: "1px solid rgba(255,255,255,0.05)",
        zIndex: 45,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 16px",
      }}
    >
      <div className="console-topbar-compat" style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
        <div className="inline-topbar-left" style={{ gap: 16 }}>
        <button
          type="button"
          className="glass-topbar-menu-btn inline-topbar-menu"
          onClick={openMenu}
          aria-label={t("topbar.openMenu")}
          style={{
            background: "none",
            border: "none",
            color: "var(--text-primary)",
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
          href="/app"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            textDecoration: "none",
            color: "var(--text-primary)",
          }}
        >
          <span style={{ fontWeight: 600, fontSize: 14 }}>{tCommon("brand.short")}</span>
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
            background: "rgba(255,255,255,0.06)",
            border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 6,
            padding: "8px 12px",
            color: "var(--text-secondary)",
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
            color: "var(--text-secondary)",
            textDecoration: "none",
            padding: "8px 10px",
            borderRadius: 6,
          }}
        >
          {targetLabel}
        </Link>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              className="glass-topbar-avatar"
              type="button"
              style={{
                width: 36,
                height: 36,
                borderRadius: "50%",
                background: "rgba(255,255,255,0.1)",
                border: "1px solid rgba(255,255,255,0.15)",
                color: "var(--text-primary)",
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
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" sideOffset={8}>
            <DropdownMenuItem asChild>
              <Link href="/app/settings">Settings</Link>
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => void logout()}>
              Logout
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
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
