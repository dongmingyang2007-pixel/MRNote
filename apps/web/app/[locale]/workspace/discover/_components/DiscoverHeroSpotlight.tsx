"use client";

import type { CSSProperties } from "react";

import { Link } from "@/i18n/navigation";
import {
  categoryLabel,
  filterCardTokens,
  labelForToken,
  providerDisplayLabel,
} from "@/lib/discover-labels";

interface SpotlightModel {
  canonical_model_id: string;
  display_name: string;
  provider: string;
  provider_display: string;
  description: string;
  official_category_key?: string | null;
  official_category?: string | null;
  input_modalities?: string[];
  output_modalities?: string[];
  supported_tools: string[];
  supported_features: string[];
  is_selectable_in_console?: boolean | null;
}

interface SpotlightStat {
  label: string;
  value: string;
  meta: string;
  isTextValue?: boolean;
}

interface DiscoverHeroSpotlightProps {
  model: SpotlightModel;
  locale: string;
  t: (key: string) => string;
  stats: SpotlightStat[];
  availableLabel: string;
  browseOnlyLabel: string;
  openDetailLabel: string;
  buildDetailHref: (modelId: string) => string;
  imageSrc?: string;
  tone?: "gradient" | "glass";
}

function dedupeTokens(values: string[]): string[] {
  return [
    ...new Set(
      values.filter(
        (value) => typeof value === "string" && value.trim().length > 0,
      ),
    ),
  ];
}

function spotlightGradientForCategory(
  categoryKey: string | null | undefined,
): string {
  if (!categoryKey) {
    return "linear-gradient(145deg, #0f172a, #4338ca)";
  }
  if (
    categoryKey.includes("vision") ||
    categoryKey.includes("image") ||
    categoryKey.includes("video")
  ) {
    return "linear-gradient(145deg, #082f49, #0284c7)";
  }
  if (
    categoryKey.includes("speech") ||
    categoryKey.includes("tts") ||
    categoryKey.includes("asr")
  ) {
    return "linear-gradient(145deg, #052e2b, #0f766e)";
  }
  if (categoryKey.includes("realtime")) {
    return "linear-gradient(145deg, #1e1b4b, #7c3aed)";
  }
  if (categoryKey.includes("embedding") || categoryKey.includes("thinking")) {
    return "linear-gradient(145deg, #111827, #2563eb)";
  }
  return "linear-gradient(145deg, #0f172a, #4338ca)";
}

function spotlightImageOverlay(categoryKey: string | null | undefined): string {
  if (
    categoryKey?.includes("vision") ||
    categoryKey?.includes("image") ||
    categoryKey?.includes("video")
  ) {
    return "linear-gradient(180deg, rgba(6, 13, 24, 0.12), rgba(4, 13, 28, 0.84)), linear-gradient(120deg, rgba(13, 63, 92, 0.16), rgba(5, 10, 20, 0.2))";
  }
  if (
    categoryKey?.includes("speech") ||
    categoryKey?.includes("tts") ||
    categoryKey?.includes("asr")
  ) {
    return "linear-gradient(180deg, rgba(8, 13, 22, 0.12), rgba(7, 18, 23, 0.84)), linear-gradient(120deg, rgba(7, 80, 73, 0.16), rgba(5, 10, 20, 0.2))";
  }
  return "linear-gradient(180deg, rgba(8, 14, 26, 0.1), rgba(8, 14, 26, 0.86)), linear-gradient(120deg, rgba(20, 54, 92, 0.12), rgba(9, 12, 19, 0.16))";
}

export function DiscoverHeroSpotlight({
  model,
  locale,
  t,
  stats,
  availableLabel,
  browseOnlyLabel,
  openDetailLabel,
  buildDetailHref,
  imageSrc,
  tone = "gradient",
}: DiscoverHeroSpotlightProps) {
  const categoryName = categoryLabel(
    model.official_category_key,
    model.official_category,
    locale,
    t,
  );
  const providerName = providerDisplayLabel(
    model.provider,
    model.provider_display,
    locale,
    t,
  );
  const isSelectable = model.is_selectable_in_console !== false;
  const tokens = filterCardTokens(
    dedupeTokens([
      ...(model.input_modalities ?? []),
      ...(model.output_modalities ?? []),
      ...(model.supported_tools ?? []),
      ...(model.supported_features ?? []),
    ]),
  ).slice(0, 4);
  const cardStyle: CSSProperties | undefined = imageSrc
    ? {
        backgroundImage: `${spotlightImageOverlay(model.official_category_key)}, url("${imageSrc}")`,
        backgroundSize: "cover",
        backgroundPosition: "center",
      }
    : tone === "gradient"
      ? {
          background: spotlightGradientForCategory(model.official_category_key),
        }
      : undefined;

  return (
    <Link
      href={buildDetailHref(model.canonical_model_id)}
      className={`dhub-spotlight-card${imageSrc ? " has-image" : ""}${tone === "glass" ? " is-glass" : ""}`}
      style={cardStyle}
    >
      <div className="dhub-spotlight-head">
        <span className="dhub-spotlight-kicker">
          {t("discover.featured")} / {categoryName}
        </span>
        <span
          className={`dhub-spotlight-status${isSelectable ? " is-ready" : ""}`}
        >
          {isSelectable ? availableLabel : browseOnlyLabel}
        </span>
      </div>

      <div className="dhub-spotlight-copy">
        <span className="dhub-spotlight-provider">{providerName}</span>
        <strong className="dhub-spotlight-name">{model.display_name}</strong>
        <p className="dhub-spotlight-desc">{model.description}</p>
      </div>

      {tokens.length > 0 ? (
        <div className="dhub-spotlight-tags">
          {tokens.map((token) => (
            <span key={token} className="dhub-spotlight-tag">
              {labelForToken(token, t)}
            </span>
          ))}
        </div>
      ) : null}

      <div className="dhub-spotlight-stats">
        {stats.map((card) => (
          <div key={card.label} className="dhub-spotlight-stat">
            <span className="dhub-spotlight-stat-label">{card.label}</span>
            <strong
              className={`dhub-spotlight-stat-value${card.isTextValue ? " is-text" : ""}`}
            >
              {card.value}
            </strong>
            <span className="dhub-spotlight-stat-meta">{card.meta}</span>
          </div>
        ))}
      </div>

      <div className="dhub-spotlight-footer">
        <span>{providerName}</span>
        <span>{openDetailLabel}</span>
      </div>
    </Link>
  );
}
