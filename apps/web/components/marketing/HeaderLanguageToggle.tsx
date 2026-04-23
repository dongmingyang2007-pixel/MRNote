"use client";

import { useTransition } from "react";
import { useLocale } from "next-intl";
import { usePathname, useRouter } from "@/i18n/navigation";

/**
 * Compact EN / 中 toggle for the marketing header. Minimal variant of
 * `LanguageSwitcher` — no external labels, just the two locale slugs
 * as a pair of buttons with a separator. Keeps the header row visually
 * tight next to the nav + CTAs.
 */
export default function HeaderLanguageToggle() {
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();

  const switchTo = (next: "en" | "zh") => {
    if (next === locale || pending) return;
    startTransition(() => {
      router.replace(pathname, { locale: next });
    });
  };

  return (
    <div className="marketing-header__lang" aria-label="Language">
      <button
        type="button"
        onClick={() => switchTo("zh")}
        className={
          locale === "zh"
            ? "marketing-header__lang-btn is-active"
            : "marketing-header__lang-btn"
        }
        disabled={pending}
        aria-pressed={locale === "zh"}
      >
        中
      </button>
      <span aria-hidden="true">·</span>
      <button
        type="button"
        onClick={() => switchTo("en")}
        className={
          locale === "en"
            ? "marketing-header__lang-btn is-active"
            : "marketing-header__lang-btn"
        }
        disabled={pending}
        aria-pressed={locale === "en"}
      >
        EN
      </button>
    </div>
  );
}
