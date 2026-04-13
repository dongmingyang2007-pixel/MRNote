import { Link } from "@/i18n/navigation";
import { getTranslations } from "next-intl/server";

export default async function NotFound() {
  const t = await getTranslations("error");

  return (
    <div className="not-found-page">
      {/* Brand header */}
      <header className="not-found-header">
        <Link href="/" className="not-found-brand">
          <span className="not-found-dot" />
          <span className="not-found-brand-name">{t("notFound.brand")}</span>
        </Link>
      </header>

      {/* Main content */}
      <main className="not-found-main">
        <div className="not-found-code-wrap" aria-hidden="true">
          <span className="not-found-code">404</span>
          <span className="not-found-scanline" />
        </div>

        <h1 className="not-found-title">{t("notFound.title")}</h1>
        <p className="not-found-body">{t("notFound.body")}</p>

        <div className="not-found-actions">
          <Link href="/" className="not-found-btn-primary">
            {t("notFound.home")}
          </Link>
          <Link href="/app" className="not-found-btn-secondary">
            {t("notFound.console")}
          </Link>
        </div>
      </main>

      {/* Footer */}
      <footer className="not-found-footer">
        <p>© 2026 {t("notFound.brand")}</p>
      </footer>
    </div>
  );
}
