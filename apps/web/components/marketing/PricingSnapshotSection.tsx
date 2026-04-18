import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { Check, ArrowRight } from "lucide-react";

type PlanKey = "free" | "pro" | "power";

interface PlanShape {
  key: PlanKey;
  featureIndexes: number[];
  highlight?: boolean;
  cadenceKey: string;
  href: string;
}

const PLANS: PlanShape[] = [
  {
    key: "free",
    featureIndexes: [0, 1],
    cadenceKey: "plan.free.cadence",
    href: "/register",
  },
  {
    key: "pro",
    featureIndexes: [0, 1],
    highlight: true,
    cadenceKey: "plan.pro.cadence.monthly",
    href: "/register?plan=pro&cycle=monthly",
  },
  {
    key: "power",
    featureIndexes: [0, 1],
    cadenceKey: "plan.power.cadence.monthly",
    href: "/register?plan=power&cycle=monthly",
  },
];

export default async function PricingSnapshotSection() {
  const t = await getTranslations("marketing");
  return (
    <section className="marketing-section" id="pricing-snapshot">
      <div className="marketing-inner">
        <div
          className="marketing-inner--narrow"
          style={{ textAlign: "center", margin: "0 auto" }}
        >
          <span className="marketing-eyebrow">{t("pricing.kicker")}</span>
          <h2 className="marketing-h2 font-display tracking-tight text-3xl md:text-4xl lg:text-5xl">
            {t("pricing.title")}
          </h2>
          <p
            className="marketing-lead text-lg md:text-xl leading-relaxed"
            style={{ marginTop: 16, maxWidth: 560, marginInline: "auto" }}
          >
            {t("pricing.sub")}
          </p>
        </div>

        <div className="marketing-pricing-grid marketing-pricing-grid--3">
          {PLANS.map((plan) => (
            <div
              key={plan.key}
              className={`marketing-plan-card${plan.highlight ? " marketing-plan-card--highlight" : ""}`}
            >
              {plan.highlight && (
                <span className="marketing-plan-card__badge">
                  {t("plan.pro.badge")}
                </span>
              )}
              <div>
                <div
                  className="font-display tracking-tight"
                  style={{
                    fontSize: "1rem",
                    fontWeight: 600,
                    color: "var(--text-primary)",
                  }}
                >
                  {t(`plan.${plan.key}.name`)}
                </div>
                <div
                  className="marketing-body"
                  style={{ fontSize: "0.88rem", marginTop: 4 }}
                >
                  {t(`plan.${plan.key}.tagline`)}
                </div>
              </div>
              <div>
                <span className="marketing-plan-card__price">
                  {t(`plan.${plan.key}.price.monthly`)}
                </span>
                <span className="marketing-plan-card__cadence">
                  {t(plan.cadenceKey)}
                </span>
              </div>
              <ul className="marketing-plan-card__features">
                {plan.featureIndexes.map((idx) => (
                  <li key={idx} className="marketing-plan-card__feature">
                    <Check
                      size={16}
                      strokeWidth={2.4}
                      color="var(--brand-v2)"
                      style={{ marginTop: 3, flexShrink: 0 }}
                    />
                    <span>{t(`plan.${plan.key}.feat.${idx}`)}</span>
                  </li>
                ))}
              </ul>
              <Link
                href="/pricing"
                className="marketing-header__link"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  marginTop: 4,
                  color: "var(--brand-v2)",
                  fontWeight: 500,
                }}
              >
                {t("pricing.learn")}
                <ArrowRight size={14} />
              </Link>
            </div>
          ))}
        </div>

        <div style={{ textAlign: "center", marginTop: 32 }}>
          <Link
            href="/pricing"
            className="marketing-btn marketing-btn--secondary"
          >
            {t("pricing.view_all")}
            <ArrowRight size={14} />
          </Link>
        </div>
      </div>
    </section>
  );
}
