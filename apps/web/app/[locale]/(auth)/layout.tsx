import { Link } from "@/i18n/navigation";
import { getTranslations } from "next-intl/server";

import { AuthBrandPanel } from "@/components/auth/AuthBrandPanel";

export default async function AuthLayout({ children }: { children: React.ReactNode }) {
  const tConsole = await getTranslations("console");
  const tMarketing = await getTranslations("marketing");

  return (
    <div className="flex min-h-screen flex-col bg-[var(--bg-base)] text-[var(--text-primary)]">
      <header className="border-b border-[var(--border)] bg-[var(--bg-surface)]/60 backdrop-blur">
        <div className="mx-auto flex h-16 w-full items-center justify-between px-6 lg:px-10">
          <Link
            href="/app"
            className="flex items-center gap-2 text-sm font-semibold"
            aria-label={tConsole("brand")}
          >
            <span className="h-2.5 w-2.5 rounded-sm bg-[var(--brand-v2)]" />
            <span className="font-display tracking-tight">{tMarketing("brand.name")}</span>
          </Link>
          <span className="hidden text-xs uppercase tracking-widest text-[var(--text-secondary)] sm:inline">
            {tConsole("brand")}
          </span>
        </div>
      </header>

      <main className="flex-1">
        <div className="grid min-h-[calc(100vh-4rem)] grid-cols-1 lg:grid-cols-[6fr_5fr]">
          {/* Left column — auth form (children) */}
          <div className="flex w-full items-center justify-center px-6 py-16 md:px-10 lg:py-20">
            <div className="w-full max-w-md">{children}</div>
          </div>

          {/* Right column — brand panel (hidden < lg) */}
          <AuthBrandPanel />
        </div>
      </main>
    </div>
  );
}
