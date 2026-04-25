import { getTranslations } from "next-intl/server";

import { MarketingGraphPreview } from "./ProductPreviews";

const STAT_KEYS = ["a", "b", "c"] as const;

export default async function MemorySection() {
  const t = await getTranslations("marketing");

  return (
    <section className="marketing-memory" id="memory">
      <div className="marketing-memory__inner">
        <div className="marketing-memory__copy">
          <span className="marketing-eyebrow marketing-memory__eyebrow">
            {t("memorySection.eyebrow")}
          </span>
          <h2 className="marketing-h2 marketing-memory__title">
            {t("memorySection.title")}
          </h2>
          <p className="marketing-memory__lead">{t("memorySection.lead")}</p>

          <dl className="marketing-memory__stats">
            {STAT_KEYS.map((k) => (
              <div key={k} className="marketing-memory__stat">
                <dt className="marketing-memory__stat-num">
                  {t(`memorySection.stats.${k}.num`)}
                </dt>
                <dd className="marketing-memory__stat-label">
                  {t(`memorySection.stats.${k}.label`)}
                </dd>
              </div>
            ))}
          </dl>
        </div>

        <div className="marketing-memory__graph marketing-memory__graph--screen">
          <MarketingGraphPreview variant="dark" surface="memory" />
        </div>
      </div>
    </section>
  );
}
