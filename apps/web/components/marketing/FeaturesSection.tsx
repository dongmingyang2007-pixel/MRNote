import { getTranslations } from "next-intl/server";
import { Brain, Bell, CalendarCheck } from "lucide-react";

const FEATURE_ICONS = {
  1: Brain,
  2: Bell,
  3: CalendarCheck,
} as const;

type FeatureKey = 1 | 2 | 3;

export default async function FeaturesSection() {
  const t = await getTranslations("marketing");
  const features: FeatureKey[] = [1, 2, 3];

  return (
    <section className="marketing-section" id="features">
      <div className="marketing-inner">
        <div
          className="marketing-inner--narrow"
          style={{ textAlign: "center", margin: "0 auto 24px" }}
        >
          <span className="marketing-eyebrow">{t("features.kicker")}</span>
          <h2 className="marketing-h2">{t("features.title")}</h2>
        </div>

        {features.map((i) => {
          const Icon = FEATURE_ICONS[i];
          const reverse = i % 2 === 0;
          return (
            <div
              key={i}
              className={`marketing-feature${reverse ? " marketing-feature--reverse" : ""}`}
            >
              <div className="marketing-feature__copy">
                <div className="marketing-problem-card__icon" style={{ marginBottom: 0 }}>
                  <Icon size={20} strokeWidth={2} />
                </div>
                <span className="marketing-eyebrow" style={{ marginBottom: 0 }}>
                  {t(`feature${i}.eyebrow`)}
                </span>
                <h3 className="marketing-h3">{t(`feature${i}.title`)}</h3>
                <p className="marketing-body">{t(`feature${i}.body`)}</p>
                <ul className="marketing-feature__bullets">
                  <li className="marketing-feature__bullet">
                    {t(`feature${i}.bullets.0`)}
                  </li>
                  <li className="marketing-feature__bullet">
                    {t(`feature${i}.bullets.1`)}
                  </li>
                  <li className="marketing-feature__bullet">
                    {t(`feature${i}.bullets.2`)}
                  </li>
                </ul>
              </div>
              <div className="marketing-feature__media">
                <div>
                  <div
                    style={{
                      fontWeight: 600,
                      color: "var(--text-primary)",
                      marginBottom: 6,
                    }}
                  >
                    {t(`feature${i}.screenshot.label`)}
                  </div>
                  <div>{t(`feature${i}.screenshot.hint`)}</div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
