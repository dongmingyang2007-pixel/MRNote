import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { ArrowRight } from "lucide-react";

/**
 * CTAFooterSection — the full-bleed "start working in the notebook OS"
 * call to action. Mirrors the `.cta` block in MRNote sections.css: deep
 * teal gradient, fine radial grid overlay, big display heading, and the
 * orange primary CTA in inverse-on-dark treatment.
 */
export default async function CTAFooterSection() {
  const t = await getTranslations("marketing");
  return (
    <section className="marketing-cta-footer" id="start">
      <div
        className="marketing-cta-footer__grid-bg"
        aria-hidden="true"
      />
      <div className="marketing-cta-footer__inner">
        <span className="marketing-eyebrow marketing-cta-footer__eyebrow">
          {t("cta.kicker")}
        </span>
        <h2 className="marketing-h2 marketing-cta-footer__title">
          {t("cta.title")}
          <br />
          <span className="marketing-cta-footer__title-accent">
            {t("cta.titleAccent")}
          </span>
        </h2>
        <p className="marketing-cta-footer__sub">{t("cta.sub")}</p>
        <div className="marketing-cta-footer__actions">
          <Link
            href="/register"
            className="marketing-btn marketing-btn--primary marketing-btn--lg"
          >
            {t("cta.primary")}
            <ArrowRight size={16} />
          </Link>
        </div>
        <p className="marketing-cta-footer__footnote">{t("cta.footnote")}</p>
      </div>
    </section>
  );
}
