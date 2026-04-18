import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import MobileNav from "./MobileNav";

export default async function PublicHeader() {
  const t = await getTranslations("marketing");
  return (
    <header className="marketing-header" data-testid="marketing-header">
      <div className="marketing-header__inner">
        <Link href="/" className="marketing-header__logo" aria-label={t("brand.name")}>
          <span className="marketing-header__logo-mark" aria-hidden="true" />
          <span>{t("brand.name")}</span>
        </Link>

        <nav className="marketing-header__nav" aria-label="Primary">
          <Link href="/#features" className="marketing-header__link">
            {t("nav.features")}
          </Link>
          <Link href="/pricing" className="marketing-header__link">
            {t("nav.pricing")}
          </Link>
        </nav>

        <div className="marketing-header__cta">
          <Link href="/login" className="marketing-header__link">
            {t("nav.login")}
          </Link>
          <Link href="/register" className="marketing-btn marketing-btn--primary">
            {t("nav.start")}
          </Link>
        </div>

        <MobileNav
          openLabel={t("nav.menu.open")}
          closeLabel={t("nav.menu.close")}
          featuresLabel={t("nav.features")}
          pricingLabel={t("nav.pricing")}
          loginLabel={t("nav.login")}
          startLabel={t("nav.start")}
        />
      </div>
    </header>
  );
}
