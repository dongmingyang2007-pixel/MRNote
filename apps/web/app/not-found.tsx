import { headers } from "next/headers";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

function pickLocale(accept: string): "zh" | "en" {
  return accept.toLowerCase().includes("zh") ? "zh" : "en";
}

export default async function RootNotFound() {
  const h = await headers();
  const locale = pickLocale(h.get("accept-language") ?? "");
  const t = await getTranslations({ locale, namespace: "error" });
  const tCommon = await getTranslations({ locale, namespace: "common" });
  const year = new Date().getFullYear();

  return (
    <html lang={locale}>
      <body style={{ margin: 0 }}>
        <div className="not-found-page">
          <header className="not-found-header">
            <Link href="/" className="not-found-brand">
              <span className="not-found-dot" />
              <span className="not-found-brand-name">{tCommon("brand.company")}</span>
            </Link>
          </header>

          <main className="not-found-main">
            <div className="not-found-code-wrap" aria-hidden="true">
              <span className="not-found-code">{t("notFound.kicker")}</span>
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

          <footer className="not-found-footer">
            <p>{t("notFound.copyright", { year })}</p>
          </footer>
        </div>
      </body>
    </html>
  );
}
