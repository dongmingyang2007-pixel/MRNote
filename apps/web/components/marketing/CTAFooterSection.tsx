import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { ArrowRight } from "lucide-react";

export default async function CTAFooterSection() {
  const t = await getTranslations("marketing");
  return (
    <section className="marketing-cta-strip">
      <div className="marketing-inner marketing-inner--narrow" style={{ margin: "0 auto" }}>
        <h2 className="marketing-h2">
          {t("cta.title")}
          <br />
          <span style={{ color: "var(--brand-v2)" }}>{t("cta.titleAccent")}</span>
        </h2>
        <p
          className="marketing-lead"
          style={{ marginTop: 20, marginBottom: 32, maxWidth: 560, marginInline: "auto" }}
        >
          {t("cta.sub")}
        </p>
        <Link
          href="/register"
          className="marketing-btn marketing-btn--primary marketing-btn--lg"
        >
          {t("cta.primary")}
          <ArrowRight size={16} />
        </Link>
        <p
          className="marketing-body"
          style={{ marginTop: 16, fontSize: "0.85rem" }}
        >
          {t("cta.footnote")}
        </p>
      </div>
    </section>
  );
}
