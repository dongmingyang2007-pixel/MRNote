"use client";

import { useEffect, useSyncExternalStore } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Link, usePathname } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import clsx from "clsx";
import {
  getAuthStateServerSnapshot,
  getAuthStateSnapshot,
  subscribeAuthState,
} from "@/lib/auth-state";
import { logout } from "@/lib/api";
import { useMobileMenu } from "@/components/MobileMenuProvider";

const CONSOLE_NAV_ITEMS = [
  { href: "/app", navKey: "home" },
  { href: "/app/notebooks", navKey: "notebooks" },
  { href: "/app/settings", navKey: "settings" },
] as const;

function normalizeConsolePath(pathname: string): string {
  const withoutLocale = pathname.replace(/^\/(en|zh)(?=\/|$)/, "") || "/";
  return withoutLocale.replace(/^\/workspace(?=\/|$)/, "/app");
}

export function UnifiedMobileNav() {
  const { open, closeMenu } = useMobileMenu();
  const pathname = usePathname();
  const tCommon = useTranslations("common");
  const tConsole = useTranslations("console");
  const loggedIn = useSyncExternalStore(
    subscribeAuthState,
    getAuthStateSnapshot,
    getAuthStateServerSnapshot,
  );

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  const consolePath = normalizeConsolePath(pathname);
  const isConsoleActive = (href: string) =>
    href === "/app" ? consolePath === "/app" : consolePath === href || consolePath.startsWith(`${href}/`);

  const handleLogout = async () => {
    closeMenu();
    await logout();
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex flex-col bg-[rgba(247,254,252,0.92)] backdrop-blur-xl"
          style={{ WebkitBackdropFilter: "blur(20px)" }}
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -20 }}
          transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-[var(--console-border-subtle)] p-4">
            <span className="text-sm font-semibold text-[var(--text-primary)]">
              {tConsole("brand")}
            </span>
            <button
              onClick={closeMenu}
              className="p-2 text-[var(--console-text-muted,var(--text-secondary))] hover:text-[var(--text-primary)]"
              aria-label={tCommon("nav.closeMenu")}
            >
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Nav Items */}
          <nav className="flex flex-col gap-1 p-4">
            {CONSOLE_NAV_ITEMS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={closeMenu}
                className={clsx(
                  "flex items-center justify-between rounded-lg px-4 py-3 text-sm transition-colors",
                  isConsoleActive(item.href)
                    ? "bg-[var(--console-accent-soft,var(--brand-soft))] text-[var(--console-accent,var(--brand-v2))] font-medium"
                    : "text-[var(--console-text-muted,var(--text-secondary))] hover:bg-[var(--console-accent-soft)] hover:text-[var(--text-primary)]",
                )}
              >
                <span>{tConsole(`nav.${item.navKey}`)}</span>
                <span className="text-xs opacity-60">
                  {tConsole(`mobile.${item.navKey}.meta`)}
                </span>
              </Link>
            ))}
          </nav>

          {/* Auth Section */}
          <div className="px-4 pb-2">
            <div className="flex flex-col gap-1 border-t border-[var(--console-border-subtle)] pt-4">
              {loggedIn ? (
                <>
                  <Link
                    href="/app/settings"
                    onClick={closeMenu}
                    className="flex items-center rounded-lg px-4 py-3 text-sm text-[var(--console-text-muted,var(--text-secondary))] transition-colors hover:bg-[var(--console-accent-soft)] hover:text-[var(--text-primary)]"
                  >
                    {tCommon("user.settings")}
                  </Link>
                  <button
                    onClick={handleLogout}
                    className="flex items-center rounded-lg px-4 py-3 text-left text-sm text-[var(--console-text-muted,var(--text-secondary))] transition-colors hover:bg-[var(--console-accent-soft)] hover:text-[var(--text-primary)]"
                  >
                    {tCommon("user.logout")}
                  </button>
                </>
              ) : (
                <Link
                  href="/login"
                  onClick={closeMenu}
                  className="flex items-center rounded-lg px-4 py-3 text-sm text-[var(--console-text-muted,var(--text-secondary))] transition-colors hover:bg-[var(--console-accent-soft)] hover:text-[var(--text-primary)]"
                >
                  {tCommon("user.login")}
                </Link>
              )}
            </div>
          </div>

          {/* Footer */}
          <div className="mt-auto border-t border-[var(--console-border-subtle)] p-4">
            <Link
              href="/app/notebooks"
              onClick={closeMenu}
              className="block text-center text-sm text-[var(--console-text-muted,var(--text-secondary))] hover:text-[var(--text-primary)]"
            >
              {tConsole("nav.notebooks")}
            </Link>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
