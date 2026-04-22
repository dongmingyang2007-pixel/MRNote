import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { isLoggedInFromCookies } from "@/lib/auth/is-logged-in";
import MobileNav from "./MobileNav";
import UserMenu from "./UserMenu";

export default async function PublicHeader() {
  const t = await getTranslations("marketing");
  const tCommon = await getTranslations("common");
  const loggedIn = await isLoggedInFromCookies();

  return (
    <header className="marketing-header" data-testid="marketing-header">
      <div className="marketing-header__inner">
        <Link href="/" className="marketing-header__logo" aria-label={t("brand.name")}>
          <span className="marketing-header__logo-mark" aria-hidden="true" />
          <span className="font-display tracking-tight">{t("brand.name")}</span>
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
          {loggedIn ? (
            <>
              <Link href="/app" className="marketing-btn marketing-btn--primary">
                {t("nav.openWorkspace")}
              </Link>
              <UserMenu />
            </>
          ) : (
            <>
              <Link href="/login" className="marketing-header__link">
                {t("nav.login")}
              </Link>
              <Link href="/register" className="marketing-btn marketing-btn--primary">
                {t("nav.start")}
              </Link>
            </>
          )}
        </div>

        <MobileNav
          loggedIn={loggedIn}
          openLabel={t("nav.menu.open")}
          closeLabel={t("nav.menu.close")}
          featuresLabel={t("nav.features")}
          pricingLabel={t("nav.pricing")}
          loginLabel={t("nav.login")}
          startLabel={t("nav.start")}
          openWorkspaceLabel={t("nav.openWorkspace")}
          settingsLabel={tCommon("user.settings")}
          logoutLabel={tCommon("user.logout")}
        />
      </div>
    </header>
  );
}
