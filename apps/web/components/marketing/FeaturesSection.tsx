import { getTranslations } from "next-intl/server";
import { Brain, Bell, CalendarCheck } from "lucide-react";

import MemoryMock from "./mocks/MemoryMock";
import FollowupMock from "./mocks/FollowupMock";
import DigestMock from "./mocks/DigestMock";

const FEATURE_ICONS = {
  1: Brain,
  2: Bell,
  3: CalendarCheck,
} as const;

// Map feature index → mock component. Kept here (not in mocks/) so
// the feature→mock pairing is visible at the call site.
const FEATURE_MOCKS = {
  1: MemoryMock,
  2: FollowupMock,
  3: DigestMock,
} as const;

type FeatureKey = 1 | 2 | 3;

export default async function FeaturesSection() {
  const t = await getTranslations("marketing");
  const features: FeatureKey[] = [1, 2, 3];

  return (
    <section className="marketing-section" id="features">
      <div className="marketing-inner">
        <div
          className="marketing-inner--narrow mb-10 md:mb-16"
          style={{ textAlign: "center", margin: "0 auto" }}
        >
          <span className="marketing-eyebrow">{t("features.kicker")}</span>
          <h2 className="marketing-h2 font-display tracking-tight text-3xl md:text-4xl lg:text-5xl">
            {t("features.title")}
          </h2>
        </div>

        {features.map((i) => {
          const Icon = FEATURE_ICONS[i];
          const Mock = FEATURE_MOCKS[i];
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
                <h3 className="marketing-h3 font-display tracking-tight text-xl md:text-2xl">
                  {t(`feature${i}.title`)}
                </h3>
                <p className="marketing-body text-base md:text-lg leading-relaxed">
                  {t(`feature${i}.body`)}
                </p>
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
              <div className="marketing-feature__media-wrap">
                <Mock />
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
