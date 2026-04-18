import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import LanguageSwitcher from "./LanguageSwitcher";

export default async function PublicFooter() {
  const t = await getTranslations("marketing");
  const year = new Date().getFullYear();

  return (
    <footer className="marketing-footer" data-testid="marketing-footer">
      <div className="marketing-footer__inner">
        <div className="marketing-footer__col">
          <div
            className="marketing-header__logo"
            style={{ marginBottom: 8, fontSize: "1rem" }}
          >
            <span className="marketing-header__logo-mark" aria-hidden="true" />
            <span>{t("brand.name")}</span>
          </div>
          <p className="marketing-body" style={{ fontSize: "0.88rem", maxWidth: 280 }}>
            {t("footer.tagline")}
          </p>
        </div>

        <div className="marketing-footer__col">
          <div className="marketing-footer__heading">{t("footer.col.product")}</div>
          <Link href="/#features" className="marketing-footer__link">
            {t("footer.link.features")}
          </Link>
          <Link href="/pricing" className="marketing-footer__link">
            {t("footer.link.pricing")}
          </Link>
          <a
            href="https://mingrun-tech.com/changelog"
            className="marketing-footer__link"
            rel="noreferrer"
          >
            {t("footer.link.changelog")}
          </a>
        </div>

        <div className="marketing-footer__col">
          <div className="marketing-footer__heading">{t("footer.col.company")}</div>
          <a
            href="https://mingrun-tech.com/about"
            className="marketing-footer__link"
            rel="noreferrer"
          >
            {t("footer.link.about")}
          </a>
          <a
            href="mailto:hello@mingrun-tech.com"
            className="marketing-footer__link"
          >
            {t("footer.link.contact")}
          </a>
        </div>

        <div className="marketing-footer__col">
          <div className="marketing-footer__heading">{t("footer.col.legal")}</div>
          <Link href="/privacy" className="marketing-footer__link">
            {t("footer.link.privacy")}
          </Link>
          <Link href="/terms" className="marketing-footer__link">
            {t("footer.link.terms")}
          </Link>
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
