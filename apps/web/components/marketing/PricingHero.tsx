import { getTranslations } from "next-intl/server";

export default async function PricingHero() {
  const t = await getTranslations("marketing");
  return (
    <section className="marketing-section" style={{ paddingTop: 128, paddingBottom: 56 }}>
      <div
        className="marketing-inner marketing-inner--narrow"
        style={{ margin: "0 auto", textAlign: "center" }}
      >
        <span className="marketing-eyebrow">{t("pricingPage.hero.kicker")}</span>
        <h1 className="marketing-h1" style={{ marginBottom: 20 }}>
          {t("pricingPage.hero.title")}
        </h1>
        <p className="marketing-lead" style={{ maxWidth: 560, margin: "0 auto" }}>
          {t("pricingPage.hero.sub")}
        </p>
      </div>
    </section>
  );
}
