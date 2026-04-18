import { getTranslations } from "next-intl/server";

export default async function PricingHero() {
  const t = await getTranslations("marketing");
  return (
    <section className="marketing-section" style={{ paddingTop: 128, paddingBottom: 56 }}>
      <div
        className="marketing-inner marketing-inner--narrow"
        style={{ margin: "0 auto", textAlign: "center" }}
      >
        <span className="marketing-eyebrow mb-4">{t("pricingPage.hero.kicker")}</span>
        <h1
          className="marketing-h1 font-display tracking-tight text-4xl md:text-6xl lg:text-7xl mb-6 md:mb-8"
        >
          {t("pricingPage.hero.title")}
        </h1>
        <p
          className="marketing-lead text-lg md:text-xl leading-relaxed"
          style={{ maxWidth: 560, margin: "0 auto" }}
        >
          {t("pricingPage.hero.sub")}
        </p>
      </div>
    </section>
  );
}
