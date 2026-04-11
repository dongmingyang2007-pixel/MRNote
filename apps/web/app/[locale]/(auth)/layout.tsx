import { Link } from "@/i18n/navigation";
import { getTranslations } from "next-intl/server";

export default async function AuthLayout({ children }: { children: React.ReactNode }) {
  const t = await getTranslations("console");

  return (
    <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)]">
      <header className="border-b border-[var(--border)] bg-[var(--bg-surface)]">
        <div className="mx-auto flex h-16 max-w-[var(--site-width)] items-center px-6">
          <Link href="/app/assistants" className="flex items-center gap-2 text-sm font-semibold">
            <span className="h-2.5 w-2.5 rounded-sm bg-[var(--brand-v2)]" />
            <span>{t("brand")}</span>
          </Link>
        </div>
      </header>
      <main>{children}</main>
    </div>
  );
}
