"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { LayoutDashboard, BookOpen, Settings } from "lucide-react";

const NAV_ITEMS = [
  { href: "/app", key: "nav.dashboard", Icon: LayoutDashboard },
  { href: "/app/notebooks", key: "nav.notebooks", Icon: BookOpen },
  { href: "/app/settings", key: "nav.settings", Icon: Settings },
] as const;

export default function GlobalSidebar() {
  const pathname = usePathname();
  const t = useTranslations("console");
  const tCommon = useTranslations("common");

  const isActive = (href: string) => {
    if (href === "/app") return pathname === "/app" || pathname.endsWith("/workspace");
    return pathname.startsWith(href);
  };

  // Don't render if user is inside a notebook (NotebookSidebar handles that)
  const isInsideNotebook = /\/notebooks\/[^/]+/.test(pathname);
  if (isInsideNotebook) return null;

  return (
    <nav
      className="glass-sidebar glass-sidebar--collapsed"
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        bottom: 0,
        width: 56,
        zIndex: 40,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        paddingTop: 12,
        paddingBottom: 12,
        gap: 4,
      }}
    >
      {/* Logo */}
      <Link href="/app" className="glass-sidebar-logo" style={{ marginBottom: 16 }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: "white" }}>{tCommon("brand.glyph")}</span>
      </Link>

      {/* Nav items */}
      <div className="glass-sidebar-nav" style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1 }}>
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            prefetch={false}
            className={`glass-sidebar-nav-item${isActive(item.href) ? " is-active" : ""}`}
            title={t(item.key)}
            aria-label={t(item.key)}
          >
            <item.Icon size={20} strokeWidth={1.8} />
          </Link>
        ))}
      </div>
    </nav>
  );
}
