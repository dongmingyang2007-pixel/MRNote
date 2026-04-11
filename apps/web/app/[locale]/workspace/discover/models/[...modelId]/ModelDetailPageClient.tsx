"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/navigation";
import { apiGet } from "@/lib/api";
import { DISCOVER_ENABLED } from "@/lib/feature-flags";
import {
  MODEL_PICKER_SELECTION_KEY,
  categoryLabel,
  groupLabel,
  labelForToken,
  providerDisplayLabel,
} from "@/lib/discover-labels";

interface ModelDetail {
  id: string;
  model_id: string;
  canonical_model_id?: string | null;
  display_name: string;
  provider: string;
  provider_display: string;
  official_group_key?: string | null;
  official_group?: string | null;
  official_category_key?: string | null;
  official_category?: string | null;
  description: string;
  input_modalities: string[];
  output_modalities: string[];
  supported_tools: string[];
  supported_features: string[];
  official_url?: string | null;
  aliases: string[];
  pipeline_slot?: string | null;
  is_selectable_in_console?: boolean | null;
}

function ArrowLeftIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <line x1="19" y1="12" x2="5" y2="12" />
      <polyline points="12 19 5 12 12 5" />
    </svg>
  );
}

function ArrowUpRightIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M7 17 17 7" />
      <path d="M8 7h9v9" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
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

function formatPipelineSlot(
  value: string | null | undefined,
  t?: (key: string) => string,
): string | null {
  if (!value) {
    return null;
  }
  const slotLabelMap: Record<string, string> = {
    llm: "dashboard.slot.llm",
    asr: "dashboard.slot.asr",
    tts: "dashboard.slot.tts",
    vision: "dashboard.slot.vision",
    realtime: "dashboard.slot.realtime",
    realtime_asr: "dashboard.slot.realtimeAsr",
    realtime_tts: "dashboard.slot.realtimeTts",
  };
  if (t && slotLabelMap[value]) {
    return t(slotLabelMap[value]);
  }
  return value
    .split("_")
    .map((part) => {
      if (part === "llm" || part === "asr" || part === "tts") {
        return part.toUpperCase();
      }
      return part.charAt(0).toUpperCase() + part.slice(1);
    })
    .join(" ");
}

function ModelDetailSkeleton({
  backLabel,
  from,
}: {
  backLabel: string;
  from: string;
}) {
  return (
    <div className="model-detail">
      <div className="model-detail-topbar">
        <Link href={from} className="model-detail-back">
          <ArrowLeftIcon />
          {backLabel}
        </Link>
      </div>
      <div
        className="model-detail-console-shell model-detail-console-shell--loading"
        aria-hidden="true"
      >
        <div className="model-detail-console-skeleton xl" />
        <div className="model-detail-console-skeleton lg" />
        <div className="model-detail-console-skeleton md" />
        <div className="model-detail-console-skeleton-grid">
          {[0, 1, 2, 3].map((index) => (
            <div key={index} className="model-detail-console-skeleton card" />
          ))}
        </div>
      </div>
    </div>
  );
}

function ModelDetailPageContent() {
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();
  const locale = useLocale();
  const t = useTranslations("console");

  const rawId = params.modelId;
  const modelId = decodeURIComponent(
    Array.isArray(rawId)
      ? rawId
          .filter((segment): segment is string => typeof segment === "string")
          .join("/")
      : (rawId as string),
  );

  const pickerMode = searchParams.get("picker") === "1";
  const pickerCategory = searchParams.get("category");
  const currentModelId = searchParams.get("current_model_id");
  const from = searchParams.get("from") || "/app/discover";
  const backLabel = pickerMode
    ? t("modelDetail.backToPrevious")
    : t("modelDetail.backToDiscover");

  const [model, setModel] = useState<ModelDetail | null>(null);
  const [loadedModelId, setLoadedModelId] = useState(modelId);
  const [loading, setLoading] = useState(Boolean(modelId));
  const [error, setError] = useState(false);

  if (!DISCOVER_ENABLED) {
    const fallbackHref = from === "/app/discover" ? "/app" : from;
    const unavailableTitle = locale.startsWith("en")
      ? "Discover is temporarily unavailable"
      : "发现页暂时下线";
    const unavailableBody = locale.startsWith("en")
      ? "Model details will come back after the discover experience is rebuilt."
      : "发现页重做期间，模型详情入口也暂时关闭。";
    const backLabel = locale.startsWith("en")
      ? "Back to console"
      : "返回控制台";

    return (
      <div className="model-detail">
        <div className="model-detail-topbar">
          <Link href={fallbackHref} className="model-detail-back">
            <ArrowLeftIcon />
            {backLabel}
          </Link>
        </div>
        <div className="model-detail-console-shell">
          <div className="model-detail-console-empty">
            <strong>{unavailableTitle}</strong>
            <span>{unavailableBody}</span>
          </div>
        </div>
      </div>
    );
  }

  useEffect(() => {
    if (!modelId) {
      return;
    }
    let cancelled = false;

    apiGet<ModelDetail>(`/api/v1/models/catalog/${encodeURIComponent(modelId)}`)
      .then((data) => {
        if (!cancelled) {
          setModel(data);
          setLoadedModelId(modelId);
          setError(false);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setModel(null);
          setLoadedModelId(modelId);
          setError(true);
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [modelId]);

  if (loading || loadedModelId !== modelId) {
    return <ModelDetailSkeleton backLabel={backLabel} from={from} />;
  }

  if (error || !model) {
    return (
      <div className="model-detail">
        <div className="model-detail-topbar">
          <Link href={from} className="model-detail-back">
            <ArrowLeftIcon />
            {backLabel}
          </Link>
        </div>
        <div className="model-detail-console-shell">
          <div className="model-detail-console-empty">
            {t("modelDetail.notFound")}
          </div>
        </div>
      </div>
    );
  }

  const currentModel = model;
  const providerName = providerDisplayLabel(
    currentModel.provider,
    currentModel.provider_display,
    locale,
    t,
  );
  const categoryName = currentModel.official_category
    ? categoryLabel(
        currentModel.official_category_key,
        currentModel.official_category,
        locale,
        t,
      )
    : null;
  const groupName = currentModel.official_group
    ? groupLabel(
        currentModel.official_group_key,
        currentModel.official_group,
        locale,
        t,
      )
    : null;
  const statusLabel =
    currentModel.is_selectable_in_console === false
      ? t("modelDetail.browseOnly")
      : t("modelDetail.availableInConsole");
  const pipelineSlotLabel =
    formatPipelineSlot(currentModel.pipeline_slot) ||
    t("modelDetail.notDeclared");
  const codeValue = currentModel.canonical_model_id || currentModel.model_id;
  const capabilityRows = [
    {
      label: t("modelDetail.inputModalities"),
      items: currentModel.input_modalities ?? [],
    },
    {
      label: t("modelDetail.outputModalities"),
      items: currentModel.output_modalities ?? [],
    },
    {
      label: t("modelDetail.supportedTools"),
      items: currentModel.supported_tools ?? [],
    },
    {
      label: t("modelDetail.supportedFeatures"),
      items: currentModel.supported_features ?? [],
    },
  ];
  const summaryStats = [
    {
      label: t("modelDetail.inputModalities"),
      value: currentModel.input_modalities?.length ?? 0,
    },
    {
      label: t("modelDetail.outputModalities"),
      value: currentModel.output_modalities?.length ?? 0,
    },
    {
      label: t("modelDetail.supportedTools"),
      value: currentModel.supported_tools?.length ?? 0,
    },
    {
      label: t("modelDetail.aliases"),
      value: currentModel.aliases?.length ?? 0,
    },
  ];
  const summaryTokens = dedupeTokens([
    ...(currentModel.input_modalities ?? []),
    ...(currentModel.supported_tools ?? []),
    ...(currentModel.supported_features ?? []),
  ]).slice(0, 6);
  const metaRows = [
    { label: t("modelDetail.providerLabel"), value: providerName },
    {
      label: t("modelDetail.categoryLabel"),
      value: categoryName || t("modelDetail.notDeclared"),
    },
    {
      label: t("modelDetail.groupLabel"),
      value: groupName || t("modelDetail.notDeclared"),
    },
    { label: t("modelDetail.pipelineSlot"), value: pipelineSlotLabel },
    { label: t("modelDetail.catalogId"), value: codeValue, code: true },
  ];

  function handleUseModel() {
    if (
      currentModel.is_selectable_in_console === false ||
      typeof window === "undefined" ||
      !pickerCategory
    ) {
      return;
    }
    window.sessionStorage.setItem(
      MODEL_PICKER_SELECTION_KEY,
      JSON.stringify({
        from,
        category: pickerCategory,
        modelId: currentModel.model_id,
        displayName: currentModel.display_name,
      }),
    );
    router.push(from);
  }

  return (
    <div className="model-detail">
      <div className="model-detail-topbar">
        <Link href={from} className="model-detail-back">
          <ArrowLeftIcon />
          {backLabel}
        </Link>
      </div>

      <div className="model-detail-console-shell">
        <div className="model-detail-console-head">
          <div className="model-detail-console-head-copy">
            <span className="model-detail-console-kicker">
              {groupName || categoryName || t("modelDetail.consoleFit")}
            </span>
            <h1 className="model-detail-console-title">
              {currentModel.display_name}
            </h1>
            <p className="model-detail-console-provider model-detail-provider">
              {providerName}
            </p>
          </div>

          <div className="model-detail-console-actions">
            {pickerMode ? (
              <button
                type="button"
                className={`model-detail-console-primary${currentModel.is_selectable_in_console === false ? " is-disabled" : ""}`}
                onClick={handleUseModel}
                disabled={currentModel.is_selectable_in_console === false}
              >
                {currentModel.is_selectable_in_console === false
                  ? t("modelDetail.browseOnly")
                  : t("modelDetail.useModel")}
              </button>
            ) : null}
            {currentModel.official_url ? (
              <a
                className="model-detail-console-secondary"
                href={currentModel.official_url}
                target="_blank"
                rel="noreferrer"
              >
                {t("modelDetail.openOfficialSource")}
                <ArrowUpRightIcon />
              </a>
            ) : null}
          </div>
        </div>

        <div className="model-detail-console-codebar">
          <div className="model-detail-console-codegroup">
            <span className="model-detail-console-field-label">
              {t("modelDetail.modelCode")}
            </span>
            <div className="model-detail-console-codefield">{codeValue}</div>
          </div>
          <div className="model-detail-console-badges model-detail-tags">
            {categoryName ? (
              <span className="model-detail-console-chip model-card-tag highlight is-strong">
                {categoryName}
              </span>
            ) : null}
            {groupName ? (
              <span className="model-detail-console-chip model-card-tag">
                {groupName}
              </span>
            ) : null}
            <span className="model-detail-console-chip model-card-tag">
              {pipelineSlotLabel}
            </span>
            <span className="model-detail-console-chip model-card-tag model-detail-status is-status">
              {statusLabel}
            </span>
          </div>
        </div>

        <div className="model-detail-console-statstrip">
          {summaryStats.map((stat, index) => (
            <div
              key={stat.label}
              className={`model-detail-console-stat${index > 0 ? " has-divider" : ""}`}
            >
              <strong>{stat.value}</strong>
              <span>{stat.label}</span>
            </div>
          ))}
        </div>

        <div className="model-detail-console-layout">
          <main className="model-detail-console-main">
            <section className="model-detail-console-section">
              <div className="model-detail-console-section-head">
                <h2>{t("modelDetail.description")}</h2>
              </div>
              <p className="model-detail-console-description">
                {currentModel.description || currentModel.display_name}
              </p>
              {summaryTokens.length ? (
                <div className="model-detail-console-tokenrow">
                  {summaryTokens.map((token) => (
                    <span key={token} className="model-detail-console-token">
                      {labelForToken(token, t)}
                    </span>
                  ))}
                </div>
              ) : null}
            </section>

            <section className="model-detail-console-section">
              <div className="model-detail-console-section-head">
                <h2>{t("modelDetail.capabilities")}</h2>
                <p>{t("modelDetail.capabilitySummary")}</p>
              </div>
              <div className="model-detail-console-rowlist">
                {capabilityRows.map((row) => (
                  <div key={row.label} className="model-detail-console-row">
                    <div className="model-detail-console-rowlabel">
                      {row.label}
                    </div>
                    <div className="model-detail-console-rowvalue">
                      {row.items.length ? (
                        row.items.map((item) => (
                          <span
                            key={item}
                            className="model-detail-console-valuepill"
                          >
                            <CheckIcon />
                            {labelForToken(item, t)}
                          </span>
                        ))
                      ) : (
                        <span className="model-detail-console-muted">
                          {t("modelDetail.notDeclared")}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </section>

            {currentModel.aliases?.length ? (
              <section className="model-detail-console-section">
                <div className="model-detail-console-section-head">
                  <h2>{t("modelDetail.aliases")}</h2>
                  <p>{t("modelDetail.aliasHint")}</p>
                </div>
                <div className="model-detail-console-tokenrow">
                  {currentModel.aliases.map((alias) => (
                    <span
                      key={alias}
                      className="model-detail-console-token is-code"
                    >
                      {alias}
                    </span>
                  ))}
                </div>
              </section>
            ) : null}
          </main>

          <aside className="model-detail-console-side">
            {pickerMode ? (
              <section className="model-detail-console-section">
                <div className="model-detail-console-section-head">
                  <h2>{t("modelDetail.selectionContext")}</h2>
                </div>
                <div className="model-detail-console-meta">
                  <div className="model-detail-console-metaitem">
                    <span>{t("discover.pickerSlot")}</span>
                    <strong>
                      {formatPipelineSlot(pickerCategory, t) ||
                        t("modelDetail.notDeclared")}
                    </strong>
                  </div>
                  <div className="model-detail-console-metaitem">
                    <span>{t("discover.pickerModel")}</span>
                    <strong>
                      {currentModelId || t("modelDetail.notDeclared")}
                    </strong>
                  </div>
                </div>
              </section>
            ) : null}

            <section className="model-detail-console-section">
              <div className="model-detail-console-section-head">
                <h2>{t("modelDetail.consoleFit")}</h2>
              </div>
              <div className="model-detail-console-meta">
                {metaRows.map((row) => (
                  <div
                    key={row.label}
                    className="model-detail-console-metaitem"
                  >
                    <span>{row.label}</span>
                    <strong className={row.code ? "is-code" : undefined}>
                      {row.value}
                    </strong>
                  </div>
                ))}
              </div>
              {currentModel.official_url ? (
                <a
                  className="model-detail-console-source"
                  href={currentModel.official_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("modelDetail.officialSource")}
                  <ArrowUpRightIcon />
                </a>
              ) : null}
            </section>
          </aside>
        </div>
      </div>
    </div>
  );
}

export default function ModelDetailPage() {
  return (
    <Suspense fallback={<div className="model-detail" />}>
      <ModelDetailPageContent />
    </Suspense>
  );
}
