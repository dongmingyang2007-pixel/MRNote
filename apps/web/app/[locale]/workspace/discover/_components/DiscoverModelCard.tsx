"use client";

import { Link } from "@/i18n/navigation";
import { getProviderStyle } from "@/lib/model-utils";
import {
  labelForToken,
  providerDisplayLabel,
  filterCardTokens,
} from "@/lib/discover-labels";

interface DiscoverModelCardProps {
  model: {
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
  };
  detailHref: string;
  locale: string;
  t: (key: string) => string;
  availableLabel: string;
  browseOnlyLabel: string;
  openDetailLabel: string;
}

function dedupeTokens(values: string[]): string[] {
  return [
    ...new Set(
      values.filter((v) => typeof v === "string" && v.trim().length > 0),
    ),
  ];
}

export function DiscoverModelCard({
  model,
  detailHref,
  locale,
  t,
  availableLabel,
  browseOnlyLabel,
  openDetailLabel,
}: DiscoverModelCardProps) {
  const providerStyle = getProviderStyle(model.provider);
  const providerName = providerDisplayLabel(
    model.provider,
    model.provider_display,
    locale,
    t,
  );
  const isSelectable = model.is_selectable_in_console !== false;

  const allTokens = dedupeTokens([
    ...(model.input_modalities ?? []),
    ...(model.output_modalities ?? []),
    ...(model.supported_tools ?? []),
    ...(model.supported_features ?? []),
  ]);
  const visibleTokens = filterCardTokens(allTokens).slice(0, 4);

  return (
    <Link href={detailHref} className="dhub-model-card">
      <div className="dhub-model-card-main">
        <div className="dhub-model-card-head">
          <div
            className="dhub-model-card-logo"
            style={{ background: providerStyle.bg }}
          >
            {providerStyle.label}
          </div>
          <div className="dhub-model-card-meta">
            <strong className="dhub-model-card-name">
              {model.display_name}
            </strong>
            <span className="dhub-model-card-provider">{providerName}</span>
          </div>
        </div>
        <p className="dhub-model-card-desc">
          {model.description || model.display_name}
        </p>
      </div>

      <div
        className={`dhub-model-card-tags${visibleTokens.length === 0 ? " is-empty" : ""}`}
      >
        {visibleTokens.map((token) => (
          <span key={token} className="dhub-model-card-tag">
            {labelForToken(token, t)}
          </span>
        ))}
      </div>

      <div className="dhub-model-card-footer">
        <span
          className={`dhub-model-card-status${isSelectable ? " is-ready" : ""}`}
        >
          {isSelectable ? availableLabel : browseOnlyLabel}
        </span>
        <span className="dhub-model-card-action">{openDetailLabel}</span>
      </div>
    </Link>
  );
}
