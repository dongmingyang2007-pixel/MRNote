"use client";

import { useTransition } from "react";
import { useLocale } from "next-intl";
import { usePathname, useRouter } from "@/i18n/navigation";
import clsx from "clsx";

interface LanguageSwitcherProps {
  label: string;
  enLabel: string;
  zhLabel: string;
}

type SupportedLocale = "en" | "zh";

export default function LanguageSwitcher({ label, enLabel, zhLabel }: LanguageSwitcherProps) {
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();

  const switchTo = (next: SupportedLocale) => {
    if (next === locale || pending) return;
    startTransition(() => {
      router.replace(pathname, { locale: next });
    });
  };

  const linkStyle = (active: boolean) =>
    clsx("marketing-footer__link", {
      "marketing-footer__link--active": active,
    });

  return (
    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
      <span style={{ color: "var(--text-secondary)", fontSize: "0.85rem" }}>{label}:</span>
      <button
        type="button"
        onClick={() => switchTo("en")}
        className={linkStyle(locale === "en")}
        style={{
          background: "transparent",
          border: 0,
          padding: 0,
          cursor: "pointer",
          color: locale === "en" ? "var(--text-primary)" : "var(--text-secondary)",
          fontWeight: locale === "en" ? 600 : 400,
          transition: "color var(--motion-base) var(--motion-ease)",
        }}
        disabled={pending}
      >
        {enLabel}
      </button>
      <span style={{ color: "var(--border)" }}>·</span>
      <button
        type="button"
        onClick={() => switchTo("zh")}
        className={linkStyle(locale === "zh")}
        style={{
          background: "transparent",
          border: 0,
          padding: 0,
          cursor: "pointer",
          color: locale === "zh" ? "var(--text-primary)" : "var(--text-secondary)",
          fontWeight: locale === "zh" ? 600 : 400,
          transition: "color var(--motion-base) var(--motion-ease)",
        }}
        disabled={pending}
      >
        {zhLabel}
      </button>
    </div>
  );
}
