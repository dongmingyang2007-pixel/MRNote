import { ArrowLeft } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";

/**
 * Auth-only header. Replaces the bare wordmark on login / register /
 * forgot-password so returning users who got bounced from /app/* can
 * (a) see what product they're logging into and (b) exit to the
 * marketing page without manually editing the URL.
 *
 * Layout mirrors the previous wordmark block's position (top-left),
 * but adds the tagline beside the brand and a muted "← 返回首页"
 * link at the top-right.
 */
export default async function AuthBrandHeader() {
  const t = await getTranslations("auth");
  const tMarketing = await getTranslations("marketing");

  return (
    <header className="flex items-center justify-between px-6 pt-8 md:px-10">
      <Link
        href="/"
        className="inline-flex items-center gap-3 text-sm"
        aria-label={tMarketing("brand.name")}
      >
        <span className="h-2.5 w-2.5 rounded-sm bg-[var(--brand-v2)]" />
        <span className="font-display font-semibold tracking-tight">
          {tMarketing("brand.name")}
        </span>
        <span className="hidden text-[var(--text-secondary)] md:inline">
          · {t("brand.tagline")}
        </span>
      </Link>

      <Link
        href="/"
        className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] px-3 py-1.5 text-xs font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-surface)] hover:text-[var(--text-primary)]"
      >
        <ArrowLeft size={14} strokeWidth={2} />
        {t("brand.back")}
      </Link>
    </header>
  );
}
