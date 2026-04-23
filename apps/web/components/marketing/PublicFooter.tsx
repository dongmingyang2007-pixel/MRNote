import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import LanguageSwitcher from "./LanguageSwitcher";

/**
 * PublicFooter — mirrors `.footer` in MRNote sections.css.
 *
 * Grid layout:  brand (2fr) | product | company | legal
 * Brand column carries the logomark, name, and tagline. Column headings
 * are mono + uppercase + tertiary. Link hover pulls to `--mkt-primary`.
 * Divider strip at the bottom carries copyright + language switcher.
 */
export default async function PublicFooter() {
  const t = await getTranslations("marketing");
  const year = new Date().getFullYear();

  return (
    <footer className="marketing-footer" data-testid="marketing-footer">
      <div className="marketing-footer__inner">
        <div className="marketing-footer__brand">
          <div className="marketing-footer__brand-row">
            <span
              className="marketing-header__logo-mark"
              aria-hidden="true"
            />
            <span className="marketing-footer__brand-name font-display tracking-tight">
              {t("brand.name")}
            </span>
          </div>
          <p className="marketing-footer__tagline">{t("footer.tagline")}</p>
        </div>

        <div className="marketing-footer__col">
          <div className="marketing-footer__heading">
            {t("footer.col.product")}
          </div>
          <ul className="marketing-footer__list">
            <li>
              <Link href="/#features" className="marketing-footer__link">
                {t("footer.link.features")}
              </Link>
            </li>
            <li>
              <Link href="/pricing" className="marketing-footer__link">
                {t("footer.link.pricing")}
              </Link>
            </li>
            <li>
              <a
                href="https://mingrun-tech.com/changelog"
                className="marketing-footer__link"
                rel="noreferrer"
              >
                {t("footer.link.changelog")}
              </a>
            </li>
          </ul>
        </div>

        <div className="marketing-footer__col">
          <div className="marketing-footer__heading">
            {t("footer.col.company")}
          </div>
          <ul className="marketing-footer__list">
            <li>
              <a
                href="https://mingrun-tech.com/about"
                className="marketing-footer__link"
                rel="noreferrer"
              >
                {t("footer.link.about")}
              </a>
            </li>
            <li>
              <a
                href="mailto:hello@mingrun-tech.com"
                className="marketing-footer__link"
              >
                {t("footer.link.contact")}
              </a>
            </li>
          </ul>
        </div>

        <div className="marketing-footer__col">
          <div className="marketing-footer__heading">
            {t("footer.col.legal")}
          </div>
          <ul className="marketing-footer__list">
            <li>
              <Link href="/privacy" className="marketing-footer__link">
                {t("footer.link.privacy")}
              </Link>
            </li>
            <li>
              <Link href="/terms" className="marketing-footer__link">
                {t("footer.link.terms")}
              </Link>
            </li>
          </ul>
        </div>
      </div>

      <div className="marketing-footer__bottom">
        <div>
          &copy; {year} {t("brand.company")}. {t("footer.rights")}
        </div>
        <LanguageSwitcher
          label={t("footer.lang.label")}
          enLabel={t("footer.lang.en")}
          zhLabel={t("footer.lang.zh")}
        />
      </div>
    </footer>
  );
}
