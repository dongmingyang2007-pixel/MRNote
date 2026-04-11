"use client";

import clsx from "clsx";
import { Link, usePathname } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { DISCOVER_ENABLED } from "@/lib/feature-flags";
import {
  HomeIcon,
  ChatIcon,
  MemoryIcon,
  DiscoverIcon,
} from "./NavIcons";

const MAIN_TABS = [
  {
    href: "/app",
    labelKey: "nav.home" as const,
    short: "首页",
    Icon: HomeIcon,
  },
  {
    href: "/app/chat",
    labelKey: "nav.chat" as const,
    short: "对话",
    Icon: ChatIcon,
  },
  {
    href: "/app/memory",
    labelKey: "nav.memory" as const,
    short: "记忆",
    Icon: MemoryIcon,
  },
  ...(DISCOVER_ENABLED
    ? [
        {
          href: "/app/discover",
          labelKey: "nav.discover" as const,
          short: "发现",
          Icon: DiscoverIcon,
        },
      ]
    : []),
];

export function MobileTabBar() {
  const pathname = usePathname();
  const t = useTranslations("console");

  const isActive = (href: string) =>
    href === "/app" ? pathname === "/app" : pathname.startsWith(href);

  return (
    <nav
      className="mobile-tab-bar"
      role="navigation"
      aria-label="Mobile navigation"
    >
      {MAIN_TABS.map((tab) => {
        const active = isActive(tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={clsx("mobile-tab-item", active && "is-active")}
            aria-current={active ? "page" : undefined}
            aria-label={t(tab.labelKey)}
          >
            <span className="mobile-tab-icon">
              <tab.Icon />
            </span>
            <span>{tab.short}</span>
          </Link>
        );
      })}
    </nav>
  );
}
