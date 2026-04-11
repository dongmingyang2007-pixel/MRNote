"use client";

import type { CSSProperties } from "react";

import { Link } from "@/i18n/navigation";
import { categoryLabel, providerDisplayLabel } from "@/lib/discover-labels";

interface FeaturedModel {
  canonical_model_id: string;
  display_name: string;
  provider: string;
  provider_display: string;
  description: string;
  official_category_key?: string | null;
  official_category?: string | null;
}

interface DiscoverFeaturedProps {
  models: FeaturedModel[];
  locale: string;
  t: (key: string) => string;
  title: string;
  subtitle: string;
  buildDetailHref: (modelId: string) => string;
  heroImageSrc?: string;
  supportImageSrc?: string;
  supportEyebrow?: string;
  supportTitle?: string;
  supportSubtitle?: string;
  supportActionLabel?: string;
  onSelectScene?: (slot: string | null) => void;
}

export function DiscoverFeatured({
  models,
  locale,
  t,
  title,
  subtitle,
  buildDetailHref,
  heroImageSrc,
  supportImageSrc,
  supportEyebrow,
  supportTitle,
  supportSubtitle,
  supportActionLabel,
  onSelectScene,
}: DiscoverFeaturedProps) {
  if (models.length === 0) {
    return null;
  }

  const displayed = models.slice(0, 3);
  const [heroModel, ...secondaryModels] = displayed;
  const hasSideColumn = secondaryModels.length > 0 || Boolean(supportImageSrc);
  const heroStyle: CSSProperties | undefined = heroImageSrc
    ? {
        backgroundImage: `linear-gradient(180deg, rgba(11, 17, 26, 0.12), rgba(11, 17, 26, 0.84)), linear-gradient(120deg, rgba(103, 86, 54, 0.08), rgba(9, 14, 22, 0.18)), url("${heroImageSrc}")`,
        backgroundSize: "cover",
        backgroundPosition: "center",
      }
    : undefined;
  const supportStyle: CSSProperties | undefined = supportImageSrc
    ? {
        backgroundImage: `linear-gradient(180deg, rgba(9, 14, 24, 0.12), rgba(9, 14, 24, 0.82)), linear-gradient(120deg, rgba(8, 13, 22, 0.16), rgba(9, 14, 24, 0.18)), url("${supportImageSrc}")`,
        backgroundSize: "cover",
        backgroundPosition: "center",
      }
    : undefined;

  return (
    <section className="dhub-featured">
      <div className="dhub-section-head">
        <div>
          <h2 className="dhub-section-title">{title}</h2>
          <p className="dhub-section-subtitle">{subtitle}</p>
        </div>
      </div>

      <div className={`dhub-featured-grid${hasSideColumn ? "" : " is-single"}`}>
        <Link
          href={buildDetailHref(heroModel.canonical_model_id)}
          className={`dhub-featured-card dhub-featured-card--hero${heroImageSrc ? " has-image" : ""}`}
          style={heroStyle}
        >
          <div className="dhub-featured-card-rail">
            <span className="dhub-featured-card-index">01</span>
            <span className="dhub-featured-card-meta-label">{title}</span>
          </div>
          <div className="dhub-featured-card-body">
            <span className="dhub-featured-card-cat">
              {categoryLabel(
                heroModel.official_category_key,
                heroModel.official_category,
                locale,
                t,
              )}
            </span>
            <strong className="dhub-featured-card-name">
              {heroModel.display_name}
            </strong>
            <span className="dhub-featured-card-desc">
              {heroModel.description}
            </span>
          </div>
          <div className="dhub-featured-card-meta">
            <span>
              {providerDisplayLabel(
                heroModel.provider,
                heroModel.provider_display,
                locale,
                t,
              )}
            </span>
            <span>{t("discover.openDetail")}</span>
          </div>
        </Link>

        {hasSideColumn ? (
          <div className="dhub-featured-side">
            {supportImageSrc ? (
              <button
                type="button"
                className="dhub-featured-support"
                style={supportStyle}
                onClick={() => onSelectScene?.("realtime")}
              >
                <div className="dhub-featured-support-copy">
                  {supportEyebrow ? (
                    <span className="dhub-featured-support-kicker">
                      {supportEyebrow}
                    </span>
                  ) : null}
                  {supportTitle ? (
                    <strong className="dhub-featured-support-title">
                      {supportTitle}
                    </strong>
                  ) : null}
                  {supportSubtitle ? (
                    <span className="dhub-featured-support-desc">
                      {supportSubtitle}
                    </span>
                  ) : null}
                </div>
                {supportActionLabel ? (
                  <span className="dhub-featured-support-action">
                    {supportActionLabel}
                  </span>
                ) : null}
              </button>
            ) : null}

            {secondaryModels.length > 0 ? (
              <div className="dhub-featured-list">
                {secondaryModels.map((model, index) => {
                  const catName = categoryLabel(
                    model.official_category_key,
                    model.official_category,
                    locale,
                    t,
                  );

                  return (
                    <Link
                      key={model.canonical_model_id}
                      href={buildDetailHref(model.canonical_model_id)}
                      className="dhub-featured-list-item"
                    >
                      <div className="dhub-featured-list-index">
                        <span className="dhub-featured-card-index">
                          {String(index + 2).padStart(2, "0")}
                        </span>
                      </div>
                      <div className="dhub-featured-list-copy">
                        <span className="dhub-featured-card-cat">
                          {catName}
                        </span>
                        <strong className="dhub-featured-list-name">
                          {model.display_name}
                        </strong>
                        <span className="dhub-featured-list-desc">
                          {model.description}
                        </span>
                      </div>
                      <div className="dhub-featured-list-meta">
                        <span className="dhub-featured-list-provider">
                          {providerDisplayLabel(
                            model.provider,
                            model.provider_display,
                            locale,
                            t,
                          )}
                        </span>
                        <span className="dhub-featured-list-action">
                          {t("discover.openDetail")}
                        </span>
                      </div>
                    </Link>
                  );
                })}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}
