"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";

interface PlanRequiredDetail {
  code?: string;
  message?: string;
  details?: { key?: string; current?: number; limit?: number };
}

type TranslationFn = (
  key: string,
  values?: Record<string, string | number>,
) => string;

function getFeatureLabel(
  key: string | undefined,
  t: TranslationFn,
): string | null {
  const labels: Record<string, string> = {
    "notebooks.max": t("upgrade.feature.notebooks"),
    "pages.max": t("upgrade.feature.pages"),
    "study_assets.max": t("upgrade.feature.studyAssets"),
    "ai.actions.monthly": t("upgrade.feature.aiActions"),
    "book_upload.enabled": t("upgrade.feature.bookUpload"),
    "daily_digest.enabled": t("upgrade.feature.dailyDigest"),
    "voice.enabled": t("upgrade.feature.voice"),
    "advanced_memory_insights.enabled": t("upgrade.feature.insights"),
  };
  return key ? labels[key] || null : null;
}

export default function UpgradeModal() {
  const t = useTranslations("billing");
  const router = useRouter();
  const [detail, setDetail] = useState<PlanRequiredDetail | null>(null);

  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent<PlanRequiredDetail>;
      setDetail(ce.detail || {});
    };
    window.addEventListener("mrai:plan-required", handler);
    return () => window.removeEventListener("mrai:plan-required", handler);
  }, []);

  if (!detail) return null;

  const featureLabel = getFeatureLabel(detail.details?.key, t);
  const body =
    detail.code === "plan_limit_reached" &&
    featureLabel &&
    detail.details?.current !== undefined &&
    detail.details?.limit !== undefined
      ? t("upgrade.required.limitBody", {
          feature: featureLabel,
          current: detail.details.current,
          limit: detail.details.limit,
        })
      : featureLabel
        ? t("upgrade.required.featureBody", { feature: featureLabel })
        : detail.message || t("upgrade.required.body");

  const handleUpgrade = () => {
    setDetail(null);
    router.push("/app/settings/billing");
  };

  return (
    <div
      data-testid="upgrade-modal"
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
        zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      <div style={{
        background: "#fff", borderRadius: 8, padding: 24,
        maxWidth: 420, width: "90%",
      }}>
        <h2 style={{ marginTop: 0 }}>{t("upgrade.required.title")}</h2>
        <p>{body}</p>
        {featureLabel && detail.details?.current !== undefined && detail.details?.limit !== undefined ? (
          <p style={{ fontSize: 12, color: "#6b7280" }}>
            {t("upgrade.limit.label", {
              feature: featureLabel,
              current: detail.details.current,
              limit: detail.details.limit,
            })}
          </p>
        ) : null}
        {featureLabel && (!detail.details || detail.details.limit === undefined) ? (
          <p style={{ fontSize: 12, color: "#6b7280" }}>
            {t("upgrade.limit.featureOnly", { feature: featureLabel })}
          </p>
        ) : null}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>
          <button
            type="button"
            onClick={() => setDetail(null)}
            style={{ padding: "6px 12px", background: "transparent", border: "1px solid #d1d5db", borderRadius: 6, cursor: "pointer" }}
          >
            {t("upgrade.modal.dismiss")}
          </button>
          <button
            type="button"
            onClick={handleUpgrade}
            data-testid="upgrade-modal-go"
            style={{ padding: "6px 12px", background: "#2563eb", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer" }}
          >
            {t("upgrade.modal.see_plans")}
          </button>
        </div>
      </div>
    </div>
  );
}
