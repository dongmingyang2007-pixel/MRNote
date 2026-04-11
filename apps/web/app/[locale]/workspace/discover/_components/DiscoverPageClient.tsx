"use client";

import {
  Suspense,
  startTransition,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useLocale, useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { Link, usePathname, useRouter } from "@/i18n/navigation";
import { apiGet, isApiRequestError } from "@/lib/api";
import { DISCOVER_ENABLED } from "@/lib/feature-flags";
import {
  categoryLabel,
  providerDisplayLabel,
  sceneLabel,
} from "@/lib/discover-labels";
import { DiscoverCatalogSection } from "./DiscoverCatalogSection";
import { DiscoverFeatured } from "./DiscoverFeatured";
import { DiscoverHeroSpotlight } from "./DiscoverHeroSpotlight";
import { DiscoverMemoryPacks } from "./DiscoverMemoryPacks";
import { DiscoverSceneNav } from "./DiscoverSceneNav";
import { DiscoverSearch } from "./DiscoverSearch";

interface DiscoverTaxonomyItem {
  key: string;
  label: string;
  order: number;
  count: number;
}

interface DiscoverModel {
  canonical_model_id: string;
  model_id?: string;
  display_name: string;
  provider: string;
  provider_display: string;
  official_category_key?: string | null;
  official_category?: string | null;
  official_order?: number | null;
  description: string;
  aliases: string[];
  input_modalities?: string[];
  output_modalities?: string[];
  supported_tools: string[];
  supported_features: string[];
  pipeline_slot?:
    | "llm"
    | "asr"
    | "tts"
    | "vision"
    | "realtime"
    | "realtime_asr"
    | "realtime_tts"
    | null;
  is_selectable_in_console?: boolean | null;
  featured?: boolean | null;
  is_featured?: boolean | null;
}

interface DiscoverResponse {
  taxonomy: DiscoverTaxonomyItem[];
  items: DiscoverModel[];
}

type DiscoverPipelineSlot = NonNullable<DiscoverModel["pipeline_slot"]>;

interface MemoryPack {
  id: string;
  title: string;
  description: string;
  author: {
    id: string;
    name: string;
    avatar_seed: string;
  };
  created_at: string;
  likes_count: number;
  downloads_count: number;
}

const SEARCH_QUERY_KEY = "q";
const SLOT_QUERY_KEY = "slot";
const CATEGORY_QUERY_KEY = "category";

const MEMORY_PACK_MOCKS: MemoryPack[] = [
  {
    id: "memory-pack-sales-coach",
    title: "销售跟进副驾",
    description: "把客户画像、跟进节奏和成交异议整理成可复用的对话记忆链。",
    author: { id: "author-anna", name: "Anna Li", avatar_seed: "amber" },
    created_at: "2 小时前",
    likes_count: 182,
    downloads_count: 428,
  },
  {
    id: "memory-pack-research-ops",
    title: "研究员资料台",
    description: "长期保存行业脉络、竞品结论和关键链接，适合深度研究场景。",
    author: { id: "author-zhou", name: "Zhou", avatar_seed: "indigo" },
    created_at: "昨天",
    likes_count: 136,
    downloads_count: 301,
  },
  {
    id: "memory-pack-voice-agent",
    title: "语音客服起步包",
    description:
      "预设欢迎语、FAQ、升级路径和品牌语气，给实时语音助手直接复用。",
    author: { id: "author-mira", name: "Mira", avatar_seed: "rose" },
    created_at: "3 天前",
    likes_count: 94,
    downloads_count: 214,
  },
];

function categoryKeyForModel(item: DiscoverModel): string {
  return item.official_category_key || item.official_category || "unknown";
}

function normalizeDiscoverPayload(raw: unknown): DiscoverResponse {
  if (Array.isArray(raw)) {
    const items = raw.filter(
      (item): item is DiscoverModel =>
        typeof item === "object" && item !== null,
    );
    const taxonomyMap = new Map<string, DiscoverTaxonomyItem>();
    items.forEach((item) => {
      const key = categoryKeyForModel(item);
      const current = taxonomyMap.get(key);
      if (current) {
        current.count += 1;
        return;
      }
      taxonomyMap.set(key, {
        key,
        label: item.official_category || key,
        order: item.official_order || 0,
        count: 1,
      });
    });
    return {
      taxonomy: Array.from(taxonomyMap.values()).sort(
        (a, b) => a.order - b.order,
      ),
      items,
    };
  }

  if (typeof raw !== "object" || raw === null) {
    return { taxonomy: [], items: [] };
  }

  const response = raw as Partial<DiscoverResponse>;
  return {
    taxonomy: Array.isArray(response.taxonomy) ? response.taxonomy : [],
    items: Array.isArray(response.items) ? response.items : [],
  };
}

function sortModels(items: DiscoverModel[]): DiscoverModel[] {
  return [...items].sort((a, b) => {
    const orderA = a.official_order ?? Number.MAX_SAFE_INTEGER;
    const orderB = b.official_order ?? Number.MAX_SAFE_INTEGER;
    if (orderA !== orderB) {
      return orderA - orderB;
    }
    return a.display_name.localeCompare(b.display_name);
  });
}

function pickFeaturedModels(items: DiscoverModel[]): DiscoverModel[] {
  const selectable = sortModels(
    items.filter((item) => item.is_selectable_in_console !== false),
  );
  const explicit = selectable.filter(
    (item) => item.featured === true || item.is_featured === true,
  );
  if (explicit.length > 0) {
    return explicit.slice(0, 3);
  }

  const picked = new Map<string, DiscoverModel>();
  selectable.forEach((item) => {
    const key = categoryKeyForModel(item);
    if (!picked.has(key)) {
      picked.set(key, item);
    }
  });

  const featured = Array.from(picked.values());
  if (featured.length >= 3) {
    return featured.slice(0, 3);
  }

  selectable.forEach((item) => {
    if (featured.length >= 3) {
      return;
    }
    if (
      !featured.some(
        (candidate) => candidate.canonical_model_id === item.canonical_model_id,
      )
    ) {
      featured.push(item);
    }
  });
  return featured;
}

function buildModelSearchText(
  model: DiscoverModel,
  locale: string,
  t: (key: string, values?: Record<string, string | number>) => string,
): string {
  return [
    model.display_name,
    model.provider,
    providerDisplayLabel(model.provider, model.provider_display, locale, t),
    model.description,
    model.official_category || "",
    categoryLabel(
      model.official_category_key,
      model.official_category,
      locale,
      t,
    ),
    ...(model.aliases ?? []),
  ]
    .join(" ")
    .toLowerCase();
}

function DiscoverHubSkeleton() {
  return (
    <div className="discover-page dhub-page">
      <section
        className="dhub-search-panel dhub-skeleton-shell"
        aria-hidden="true"
      >
        <div className="dhub-skeleton dhub-skeleton-title" />
        <div className="dhub-skeleton dhub-skeleton-search" />
      </section>
      <div
        className="dhub-scenes-grid dhub-scenes-grid--loading"
        aria-hidden="true"
      >
        {[0, 1, 2, 3, 4, 5, 6].map((index) => (
          <div key={index} className="dhub-skeleton dhub-skeleton-scene" />
        ))}
      </div>
      <div className="dhub-featured-grid" aria-hidden="true">
        {[0, 1, 2].map((index) => (
          <div
            key={index}
            className={`dhub-skeleton dhub-skeleton-featured${index === 0 ? " is-hero" : ""}`}
          />
        ))}
      </div>
    </div>
  );
}

function DiscoverPageContent() {
  const t = useTranslations("console");
  const locale = useLocale();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();

  const pickerMode = searchParams.get("picker") === "1";
  const pickerCategory = searchParams.get("category");
  const currentModelId = searchParams.get("current_model_id");
  const from = searchParams.get("from");
  const querySearch = searchParams.get(SEARCH_QUERY_KEY) || "";
  const selectedSlot = searchParams.get(SLOT_QUERY_KEY);
  const requestedCategory = searchParams.get(CATEGORY_QUERY_KEY);

  const [payload, setPayload] = useState<DiscoverResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const deferredSearch = useDeferredValue(querySearch);
  const catalogRef = useRef<HTMLElement | null>(null);
  const categorySectionRefs = useRef<Record<string, HTMLElement | null>>({});

  useEffect(() => {
    if (!DISCOVER_ENABLED || !pickerMode || !from?.startsWith("/")) {
      return;
    }

    startTransition(() => {
      router.replace(from);
    });
    window.location.replace(from);
  }, [from, pickerMode, router]);

  if (!DISCOVER_ENABLED) {
    const fallbackHref = from && from.startsWith("/") ? from : "/app";
    const unavailableTitle = locale.startsWith("en")
      ? "Discover is temporarily unavailable"
      : "发现页暂时下线";
    const unavailableBody = locale.startsWith("en")
      ? "This section is being reworked. Use the rest of the console for now."
      : "这一部分正在重做，暂时先从控制台其他入口继续。";
    const backLabel = locale.startsWith("en")
      ? "Back to console"
      : "返回控制台";

    return pickerMode && from?.startsWith("/") ? null : (
      <div className="discover-page dhub-page">
        <section className="dhub-section">
          <div className="dhub-empty">
            <strong>{unavailableTitle}</strong>
            <span>{unavailableBody}</span>
            <Link href={fallbackHref} className="dhub-link-chip">
              {backLabel}
            </Link>
          </div>
        </section>
      </div>
    );
  }

  useEffect(() => {
    let cancelled = false;

    apiGet<DiscoverResponse | DiscoverModel[]>(
      "/api/v1/models/catalog?view=discover",
    )
      .then((data) => {
        if (!cancelled) {
          setPayload(normalizeDiscoverPayload(data));
          setErrorMessage(null);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setPayload({ taxonomy: [], items: [] });
          setErrorMessage(
            isApiRequestError(error) ? error.message : t("discover.loadFailed"),
          );
        }
      });

    return () => {
      cancelled = true;
    };
  }, [t]);

  function replaceDiscoverQuery(next: {
    q?: string | null;
    slot?: string | null;
    category?: string | null;
  }) {
    const params = new URLSearchParams(searchParams.toString());

    const trimmedQuery =
      next.q === undefined ? querySearch.trim() : next.q?.trim();
    if (trimmedQuery) {
      params.set(SEARCH_QUERY_KEY, trimmedQuery);
    } else {
      params.delete(SEARCH_QUERY_KEY);
    }

    const slot = next.slot === undefined ? selectedSlot : next.slot;
    if (slot) {
      params.set(SLOT_QUERY_KEY, slot);
    } else {
      params.delete(SLOT_QUERY_KEY);
    }

    const category =
      next.category === undefined ? requestedCategory : next.category;
    if (category) {
      params.set(CATEGORY_QUERY_KEY, category);
    } else {
      params.delete(CATEGORY_QUERY_KEY);
    }

    const nextQuery = params.toString();
    const currentQuery = searchParams.toString();
    const nextHref = nextQuery ? `${pathname}?${nextQuery}` : pathname;
    const currentHref = currentQuery ? `${pathname}?${currentQuery}` : pathname;
    if (nextHref === currentHref) {
      return;
    }

    startTransition(() => {
      router.replace(nextHref);
    });
  }

  const loading = payload === null && errorMessage === null;
  const normalizedQuery = deferredSearch.trim().toLowerCase();

  const baseItems = useMemo(() => {
    const items = payload?.items ?? [];
    if (!pickerMode || !pickerCategory) {
      return items;
    }
    return items.filter(
      (item) =>
        item.pipeline_slot === pickerCategory &&
        item.is_selectable_in_console !== false,
    );
  }, [payload, pickerCategory, pickerMode]);

  const filteredModels = useMemo(() => {
    if (!normalizedQuery) {
      return sortModels(baseItems);
    }
    return sortModels(
      baseItems.filter((item) =>
        buildModelSearchText(item, locale, t).includes(normalizedQuery),
      ),
    );
  }, [baseItems, locale, normalizedQuery, t]);

  const taxonomyByKey = useMemo(() => {
    return new Map((payload?.taxonomy ?? []).map((item) => [item.key, item]));
  }, [payload]);

  const catalogSections = useMemo(() => {
    const grouped = new Map<string, DiscoverModel[]>();
    filteredModels.forEach((model) => {
      const key = categoryKeyForModel(model);
      const current = grouped.get(key);
      if (current) {
        current.push(model);
      } else {
        grouped.set(key, [model]);
      }
    });

    return Array.from(grouped.entries())
      .map(([key, models]) => {
        const taxonomyItem = taxonomyByKey.get(key);
        return {
          key,
          label: models[0]?.official_category || taxonomyItem?.label || key,
          order:
            taxonomyItem?.order ??
            models[0]?.official_order ??
            Number.MAX_SAFE_INTEGER,
          models,
        };
      })
      .sort((a, b) => a.order - b.order);
  }, [filteredModels, taxonomyByKey]);

  const activeSlots = useMemo(() => {
    return Array.from(
      new Set(
        baseItems
          .map((item) => item.pipeline_slot)
          .filter((slot): slot is DiscoverPipelineSlot => Boolean(slot)),
      ),
    );
  }, [baseItems]);

  const sceneMatches = useMemo(() => {
    if (!normalizedQuery) {
      return new Set(activeSlots);
    }
    const matches = new Set<string>();
    activeSlots.forEach((slot) => {
      if (sceneLabel(slot, t).toLowerCase().includes(normalizedQuery)) {
        matches.add(slot);
      }
    });
    filteredModels.forEach((model) => {
      if (model.pipeline_slot) {
        matches.add(model.pipeline_slot);
      }
    });
    return matches;
  }, [activeSlots, filteredModels, normalizedQuery, t]);

  const highlightedCategoryKeys = useMemo(() => {
    if (!selectedSlot) {
      return new Set<string>();
    }
    return new Set(
      filteredModels
        .filter((model) => model.pipeline_slot === selectedSlot)
        .map((model) => categoryKeyForModel(model)),
    );
  }, [filteredModels, selectedSlot]);

  const activeCategoryKey = useMemo(() => {
    return catalogSections.some((section) => section.key === requestedCategory)
      ? requestedCategory
      : null;
  }, [catalogSections, requestedCategory]);

  const visibleCatalogSections = useMemo(() => {
    if (!activeCategoryKey) {
      return catalogSections;
    }
    return catalogSections.filter(
      (section) => section.key === activeCategoryKey,
    );
  }, [activeCategoryKey, catalogSections]);

  const featuredModels = useMemo(
    () => pickFeaturedModels(baseItems),
    [baseItems],
  );

  const filteredMemoryPacks = useMemo(() => {
    if (!normalizedQuery) {
      return MEMORY_PACK_MOCKS;
    }
    return MEMORY_PACK_MOCKS.filter((pack) =>
      [pack.title, pack.description, pack.author.name]
        .join(" ")
        .toLowerCase()
        .includes(normalizedQuery),
    );
  }, [normalizedQuery]);

  useEffect(() => {
    if (!selectedSlot) {
      return;
    }
    const firstHighlightedKey = catalogSections.find((section) =>
      section.models.some((model) => model.pipeline_slot === selectedSlot),
    )?.key;
    const target =
      (firstHighlightedKey &&
        categorySectionRefs.current[firstHighlightedKey]) ||
      catalogRef.current;
    if (!target) {
      return;
    }
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [catalogSections, selectedSlot]);

  function buildDetailHref(modelId: string): string {
    const params = new URLSearchParams();
    if (pickerMode) {
      params.set("picker", "1");
    }
    if (pickerCategory) {
      params.set("category", pickerCategory);
    }
    if (currentModelId) {
      params.set("current_model_id", currentModelId);
    }
    if (from) {
      params.set("from", from);
    }
    return `/app/discover/models/${encodeURIComponent(modelId)}${params.size ? `?${params.toString()}` : ""}`;
  }

  const pickerSlotLabel = pickerCategory ? sceneLabel(pickerCategory, t) : null;
  const resultsLabel = t("discover.toolbarMetaResults", {
    count: filteredModels.length,
  });
  const categoryCountLabel = t("discover.toolbarMetaCategories", {
    count: visibleCatalogSections.length,
  });
  const activeSlotLabel = selectedSlot ? sceneLabel(selectedSlot, t) : null;
  const activeCategoryLabel = activeCategoryKey
    ? categoryLabel(
        activeCategoryKey,
        taxonomyByKey.get(activeCategoryKey)?.label || activeCategoryKey,
        locale,
        t,
      )
    : null;
  const activeSignals = [activeSlotLabel, activeCategoryLabel].filter(
    (value): value is string => Boolean(value),
  );
  const searchStatusCards = [
    {
      label: t("discover.models"),
      value: String(filteredModels.length).padStart(2, "0"),
      meta: resultsLabel,
    },
    {
      label: t("discover.filterCategories"),
      value: String(visibleCatalogSections.length).padStart(2, "0"),
      meta: categoryCountLabel,
    },
    {
      label: t("discover.activeFilters"),
      value:
        activeSignals[0] ||
        (pickerMode
          ? pickerSlotLabel || t("discover.modelsOfficial")
          : t("discover.tabAll")),
      meta:
        activeSignals.length > 1
          ? activeSignals.slice(1).join(" / ")
          : pickerMode
            ? t("discover.catalogSubtitlePicker")
            : t("discover.catalogSubtitleHub"),
      isTextValue: true,
    },
  ];
  const spotlightModel = featuredModels[0] ?? null;
  const featuredRailModels = spotlightModel
    ? featuredModels.slice(1)
    : featuredModels;

  return (
    <div className="discover-page dhub-page">
      {pickerMode ? (
        <div
          className="dhub-picker-context"
          data-testid="discover-picker-context"
        >
          <div className="dhub-picker-context-stat">
            <span>{t("discover.pickerSlot")}</span>
            <strong>{pickerSlotLabel || t("discover.modelsOfficial")}</strong>
          </div>
          <div className="dhub-picker-context-stat">
            <span>{t("discover.pickerModel")}</span>
            <strong>{currentModelId || t("dashboard.modelFallback")}</strong>
          </div>
          {from ? (
            <Link href={from} className="dhub-picker-context-link">
              {t("discover.pickerReturn")}
            </Link>
          ) : null}
        </div>
      ) : null}

      <section className={`dhub-search-panel${pickerMode ? " is-picker" : ""}`}>
        <div className="dhub-search-layout">
          <div className="dhub-search-copy">
            <span className="dhub-search-kicker">
              DISCOVER / {t("nav.discover")}
            </span>
            <h1 className="dhub-search-title">
              {t("discover.modelsOfficial")}
            </h1>
            <p className="dhub-search-subtitle">
              {pickerMode
                ? t("discover.catalogSubtitlePicker")
                : t("discover.catalogSubtitleHub")}
            </p>
            <DiscoverSearch
              value={querySearch}
              placeholder={t("discover.searchPlaceholderHub")}
              clearLabel={t("discover.clearSearch")}
              onChange={(value) => replaceDiscoverQuery({ q: value })}
              onClear={() => replaceDiscoverQuery({ q: null })}
            />
            <div
              className="dhub-search-meta"
              aria-label={t("discover.activeFilters")}
            >
              <span>{resultsLabel}</span>
              <span>{categoryCountLabel}</span>
              {activeSlotLabel ? <span>{activeSlotLabel}</span> : null}
              {activeCategoryLabel ? <span>{activeCategoryLabel}</span> : null}
            </div>
            {activeSignals.length > 0 ? (
              <div className="dhub-search-filter-row">
                {activeSignals.map((signal) => (
                  <span key={signal} className="dhub-search-filter-pill">
                    {signal}
                  </span>
                ))}
              </div>
            ) : null}
          </div>

          <div className="dhub-search-aside">
            {spotlightModel ? (
              <DiscoverHeroSpotlight
                model={spotlightModel}
                locale={locale}
                t={t}
                stats={searchStatusCards}
                availableLabel={t("discover.availableNow")}
                browseOnlyLabel={t("discover.browseOnlyShort")}
                openDetailLabel={t("discover.openDetail")}
                buildDetailHref={buildDetailHref}
                tone="glass"
              />
            ) : null}
          </div>
        </div>

        {!loading && !errorMessage && !pickerMode ? (
          <DiscoverSceneNav
            activeSlots={activeSlots}
            selectedSlot={selectedSlot}
            matchingSlots={sceneMatches}
            onSelect={(slot) => replaceDiscoverQuery({ slot })}
            t={t}
            sectionLabel={t("discover.sceneNav")}
          />
        ) : null}
      </section>

      {loading ? <DiscoverHubSkeleton /> : null}

      {!loading && featuredRailModels.length > 0 ? (
        <DiscoverFeatured
          models={featuredRailModels}
          locale={locale}
          t={t}
          title={t("discover.featured")}
          subtitle={t("discover.featuredSubtitle")}
          buildDetailHref={buildDetailHref}
          heroImageSrc="/discover/discover-vision.png"
          supportImageSrc="/discover/discover-audio.png"
          supportEyebrow={t("discover.scene.realtime")}
          supportTitle={t("discover.audioLaneTitle")}
          supportSubtitle={t("discover.audioLaneSubtitle")}
          supportActionLabel={t("discover.audioLaneAction")}
          onSelectScene={(slot) => replaceDiscoverQuery({ slot })}
        />
      ) : null}

      <section className="dhub-catalog" ref={catalogRef}>
        <div className="dhub-section-head">
          <div>
            <h2 className="dhub-section-title">{t("discover.catalog")}</h2>
            <p className="dhub-section-subtitle">
              {t("discover.catalogSubtitleHub")}
            </p>
          </div>
          {activeCategoryKey ? (
            <div className="dhub-catalog-actions">
              <span className="dhub-catalog-active-pill">
                {activeCategoryLabel}
              </span>
              <button
                type="button"
                className="dhub-catalog-reset"
                onClick={() => replaceDiscoverQuery({ category: null })}
              >
                {t("discover.tabAll")}
              </button>
            </div>
          ) : null}
        </div>

        {errorMessage ? (
          <div className="dhub-empty">
            <strong>{t("discover.loadFailed")}</strong>
            <span>{errorMessage}</span>
          </div>
        ) : visibleCatalogSections.length === 0 ? (
          <div className="dhub-empty">
            <strong>{t("discover.noModelsFound")}</strong>
            <span>{t("discover.searchPlaceholderHub")}</span>
          </div>
        ) : (
          <div className="dhub-catalog-stack">
            {visibleCatalogSections.map((section, index) => (
              <DiscoverCatalogSection
                key={section.key}
                sectionIndex={String(index + 1).padStart(2, "0")}
                categoryKey={section.key}
                categoryName={categoryLabel(
                  section.key,
                  section.label,
                  locale,
                  t,
                )}
                models={section.models}
                isHighlighted={highlightedCategoryKeys.has(section.key)}
                isMuted={
                  highlightedCategoryKeys.size > 0 &&
                  !highlightedCategoryKeys.has(section.key)
                }
                locale={locale}
                t={t}
                countLabel={t("discover.catalogModelsCount", {
                  count: section.models.length,
                })}
                viewAllLabel={t("discover.catalogViewAll")}
                availableLabel={t("discover.availableNow")}
                browseOnlyLabel={t("discover.browseOnlyShort")}
                openDetailLabel={t("discover.openDetail")}
                buildDetailHref={buildDetailHref}
                onViewAll={(categoryKey) =>
                  replaceDiscoverQuery({ category: categoryKey })
                }
                sectionRef={(element) => {
                  categorySectionRefs.current[section.key] = element;
                }}
              />
            ))}
          </div>
        )}
      </section>

      {!pickerMode ? (
        <DiscoverMemoryPacks
          title={t("discover.memoryPacks")}
          subtitle={t("discover.memoryPacksSubtitle")}
          comingSoonLabel={t("discover.memoryPacksComingSoon")}
          roadmapLabels={[
            t("discover.packsRoadmap0"),
            t("discover.packsRoadmap1"),
            t("discover.packsRoadmap2"),
          ]}
          packs={filteredMemoryPacks}
          stageImageSrc="/discover/discover-memory.png"
        />
      ) : null}
    </div>
  );
}

export default function DiscoverPage() {
  return (
    <Suspense fallback={<DiscoverHubSkeleton />}>
      <DiscoverPageContent />
    </Suspense>
  );
}
