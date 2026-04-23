import { getTranslations } from "next-intl/server";
import { ArrowRight } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { isLoggedInFromCookies } from "@/lib/auth/is-logged-in";
import HeaderLanguageToggle from "./HeaderLanguageToggle";
import MobileNav from "./MobileNav";
import PublicHeaderScrollState from "./PublicHeaderScrollState";
import UserMenu from "./UserMenu";

/**
 * Public marketing header. Sticky, translucent, backdrop-blurred.
 * Visual language matches the MRNote prototype:
 * - teal logo mark with a tiny orange dot
 * - tight-spaced nav in semi-muted text, teal tint on hover
 * - ghost "Login" + orange primary "Start free →"
 * - border-bottom appears only after scroll > 12px (handled by the
 *   client `PublicHeaderScrollState` sibling which toggles .is-scrolled)
 */
export default async function PublicHeader() {
  const t = await getTranslations("marketing");
  const tCommon = await getTranslations("common");
  const loggedIn = await isLoggedInFromCookies();

  return (
    <header className="marketing-header" data-testid="marketing-header">
      <PublicHeaderScrollState />
      <div className="marketing-header__inner">
        <Link
          href="/"
          className="marketing-header__logo"
          aria-label={t("brand.name")}
        >
          <span className="marketing-header__logo-mark" aria-hidden="true">
            <span className="marketing-header__logo-dot" />
          </span>
          <span>{t("brand.name")}</span>
        </Link>

        <nav className="marketing-header__nav" aria-label="Primary">
          <Link href="/#features" className="marketing-header__link">
            {t("nav.features")}
          </Link>
          <Link href="/#memory" className="marketing-header__link">
            {t("nav.memory")}
          </Link>
          <Link href="/pricing" className="marketing-header__link">
            {t("nav.pricing")}
          </Link>
          <Link href="/#changelog" className="marketing-header__link">
            {t("nav.changelog")}
          </Link>
        </nav>

        <div className="marketing-header__cta">
          <HeaderLanguageToggle />
          {loggedIn ? (
            <>
              <Link
                href="/app"
                className="marketing-btn marketing-btn--primary marketing-btn--sm"
              >
                {t("nav.openWorkspace")}
                <ArrowRight size={14} aria-hidden="true" />
              </Link>
              <UserMenu />
            </>
          ) : (
            <>
              <Link
                href="/login"
                className="marketing-btn marketing-btn--ghost marketing-btn--sm"
              >
                {t("nav.login")}
              </Link>
              <Link
                href="/register"
                className="marketing-btn marketing-btn--primary marketing-btn--sm"
              >
                {t("nav.start")}
                <ArrowRight size={14} aria-hidden="true" />
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
