"use client";

import { createElement } from "react";

import { ArrowRightIcon, categoryIconForKey } from "./discover-icons";
import { DiscoverModelCard } from "./DiscoverModelCard";

interface CatalogModel {
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

interface DiscoverCatalogSectionProps {
  sectionIndex: string;
  categoryKey: string;
  categoryName: string;
  models: CatalogModel[];
  isHighlighted: boolean;
  isMuted: boolean;
  locale: string;
  t: (key: string) => string;
  countLabel: string;
  viewAllLabel: string;
  availableLabel: string;
  browseOnlyLabel: string;
  openDetailLabel: string;
  buildDetailHref: (modelId: string) => string;
  onViewAll: (categoryKey: string) => void;
  sectionRef?: (el: HTMLElement | null) => void;
}

export function DiscoverCatalogSection({
  sectionIndex,
  categoryKey,
  categoryName,
  models,
  isHighlighted,
  isMuted,
  locale,
  t,
  countLabel,
  viewAllLabel,
  availableLabel,
  browseOnlyLabel,
  openDetailLabel,
  buildDetailHref,
  onViewAll,
  sectionRef,
}: DiscoverCatalogSectionProps) {
  const renderCategoryIcon = categoryIconForKey(categoryKey);
  const previewNames = models
    .slice(0, 3)
    .map((model) => model.display_name)
    .join(" · ");

  return (
    <section
      ref={sectionRef}
      className={`dhub-catalog-section${isHighlighted ? " is-highlighted" : ""}${isMuted ? " is-muted" : ""}`}
      data-category={categoryKey}
    >
      <div className="dhub-catalog-section-layout">
        <div className="dhub-catalog-section-sidebar">
          <div className="dhub-catalog-section-head">
            <span className="dhub-catalog-section-index">{sectionIndex}</span>
            <div className="dhub-catalog-section-copy">
              <div className="dhub-catalog-section-title-row">
                <span className="dhub-catalog-section-icon" aria-hidden="true">
                  {createElement(renderCategoryIcon, { size: 16 })}
                </span>
                <span className="dhub-catalog-section-name">
                  {categoryName}
                </span>
                <span className="dhub-catalog-section-count">{countLabel}</span>
              </div>
              {previewNames ? (
                <p className="dhub-catalog-section-preview">{previewNames}</p>
              ) : null}
            </div>
          </div>
          <button
            type="button"
            className="dhub-catalog-section-viewall"
            onClick={() => onViewAll(categoryKey)}
          >
            {viewAllLabel} <ArrowRightIcon size={12} />
          </button>
        </div>
        <div className="dhub-catalog-section-body">
          <div className="dhub-catalog-scroll">
            {models.map((model) => (
              <DiscoverModelCard
                key={model.canonical_model_id}
                model={model}
                detailHref={buildDetailHref(model.canonical_model_id)}
                locale={locale}
                t={t}
                availableLabel={availableLabel}
                browseOnlyLabel={browseOnlyLabel}
                openDetailLabel={openDetailLabel}
              />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
