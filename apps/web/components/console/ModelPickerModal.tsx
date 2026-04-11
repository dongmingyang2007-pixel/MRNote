"use client";

import { useEffect, useMemo, useReducer } from "react";
import { createPortal } from "react-dom";
import { useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";
import { apiGet } from "@/lib/api";
import { DISCOVER_ENABLED } from "@/lib/feature-flags";
import { MODEL_PICKER_SELECTION_KEY } from "@/lib/discover-labels";

interface CatalogModel {
  id: string;
  model_id: string;
  display_name: string;
  provider: string;
  category:
    | "llm"
    | "asr"
    | "tts"
    | "vision"
    | "realtime"
    | "realtime_asr"
    | "realtime_tts";
  description: string;
  capabilities: string[];
  input_price: number;
  output_price: number;
  context_window: number;
  max_output: number;
}

interface ModelPickerModalProps {
  open: boolean;
  onClose: () => void;
  category:
    | "llm"
    | "asr"
    | "tts"
    | "vision"
    | "realtime"
    | "realtime_asr"
    | "realtime_tts";
  currentModelId?: string;
  onSelect: (modelId: string, displayName: string) => void;
}

type PickerState = {
  loading: boolean;
  models: CatalogModel[];
};

type PickerAction =
  | { type: "request" }
  | { type: "success"; models: CatalogModel[] }
  | { type: "failure" };

const PROVIDER_GRADIENTS: Record<string, string> = {
  alibaba: "linear-gradient(135deg, #c8734a, #e8925a)",
  qwen: "linear-gradient(135deg, #c8734a, #e8925a)",
  deepseek: "linear-gradient(135deg, #3a6a9a, #4a8ac8)",
};

function getProviderGradient(provider: string): string {
  const key = provider.toLowerCase();
  for (const [prefix, gradient] of Object.entries(PROVIDER_GRADIENTS)) {
    if (key.includes(prefix)) return gradient;
  }
  return "linear-gradient(135deg, #6b7280, #9ca3af)";
}

function formatPrice(price: number, t: (key: string) => string): string {
  if (price <= 0) return t("free");
  const formatted = price.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  return `¥${formatted}`;
}

const CATEGORY_LABEL_KEYS: Record<string, string> = {
  llm: "pipelineLlm",
  asr: "pipelineAsr",
  tts: "pipelineTts",
  vision: "pipelineVision",
  realtime: "pipelineRealtime",
  realtime_asr: "pipelineRealtimeAsr",
  realtime_tts: "pipelineRealtimeTts",
};

interface PendingModelSelection {
  from: string;
  category:
    | "llm"
    | "asr"
    | "tts"
    | "vision"
    | "realtime"
    | "realtime_asr"
    | "realtime_tts";
  modelId: string;
  displayName: string;
}

function pickerReducer(state: PickerState, action: PickerAction): PickerState {
  switch (action.type) {
    case "request":
      return { ...state, loading: true };
    case "success":
      return { loading: false, models: action.models };
    case "failure":
      return { loading: false, models: [] };
    default:
      return state;
  }
}

export function ModelPickerModal({
  open,
  onClose,
  category,
  currentModelId,
  onSelect,
}: ModelPickerModalProps) {
  const t = useTranslations("console-models-v2");
  const pathname = usePathname();
  const [{ loading, models }, dispatch] = useReducer(pickerReducer, {
    loading: false,
    models: [],
  });

  const marketplaceHref = useMemo(() => {
    const params = new URLSearchParams();
    params.set("picker", "1");
    params.set("category", category);
    if (currentModelId) {
      params.set("current_model_id", currentModelId);
    }
    const from =
      typeof window === "undefined"
        ? pathname
        : `${window.location.pathname}${window.location.search}`;
    params.set("from", from || pathname);
    return `/app/discover?${params.toString()}`;
  }, [category, currentModelId, pathname]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    dispatch({ type: "request" });
    apiGet<CatalogModel[]>(`/api/v1/models/catalog?category=${category}`)
      .then((data) => {
        if (!cancelled) {
          dispatch({
            type: "success",
            models: Array.isArray(data) ? data : [],
          });
        }
      })
      .catch(() => {
        if (!cancelled) {
          dispatch({ type: "failure" });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open, category]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const rawPending = window.sessionStorage.getItem(
      MODEL_PICKER_SELECTION_KEY,
    );
    if (!rawPending) return;

    let pending: PendingModelSelection | null = null;
    try {
      pending = JSON.parse(rawPending) as PendingModelSelection;
    } catch {
      window.sessionStorage.removeItem(MODEL_PICKER_SELECTION_KEY);
      return;
    }
    if (!pending) return;

    const currentPath = window.location.pathname;
    const expectedPath = (pending.from || "").split("?")[0];
    if (!expectedPath || expectedPath !== currentPath) return;
    if (pending.category !== category) return;

    window.sessionStorage.removeItem(MODEL_PICKER_SELECTION_KEY);
    onSelect(pending.modelId, pending.displayName);
    if (open) {
      onClose();
    }
  }, [category, onClose, onSelect, open]);

  if (!open) return null;

  const modalContent = (
    <div className="model-picker-overlay" onClick={onClose}>
      <div className="model-picker-card" onClick={(e) => e.stopPropagation()}>
        <div className="model-picker-header">
          <h2 className="model-picker-title">
            {t("pickerTitle")} &mdash;{" "}
            {t(CATEGORY_LABEL_KEYS[category] || category)}
          </h2>
          <button
            className="model-picker-close"
            onClick={onClose}
            aria-label="Close"
          >
            &times;
          </button>
        </div>

        <div className="model-picker-body">
          {loading ? (
            <div className="console-empty">...</div>
          ) : models.length === 0 ? (
            <div className="console-empty">{t("noModels")}</div>
          ) : (
            <div className="model-picker-list">
              {models.map((model) => {
                const isSelected = model.model_id === currentModelId;
                return (
                  <div
                    key={model.model_id}
                    className={`model-picker-item${isSelected ? " is-selected" : ""}`}
                  >
                    <div className="model-picker-item-head">
                      <div
                        className="marketplace-card-icon"
                        style={{
                          background: getProviderGradient(model.provider),
                        }}
                      >
                        {model.provider.charAt(0).toUpperCase()}
                      </div>
                      <div className="model-picker-item-info">
                        <div className="marketplace-card-name">
                          {model.display_name}
                        </div>
                        <div className="marketplace-card-provider">
                          {model.provider}
                        </div>
                      </div>
                    </div>
                    <div className="model-picker-item-desc">
                      {model.description || t("noDescription")}
                    </div>
                    <div className="model-picker-item-footer">
                      <span className="marketplace-card-price">
                        {model.input_price > 0 || model.output_price > 0
                          ? `${formatPrice(model.input_price, t)} / ${formatPrice(model.output_price, t)} ${t("priceUnit")}`
                          : t("free")}
                      </span>
                      <button
                        className="marketplace-card-btn"
                        onClick={() =>
                          onSelect(model.model_id, model.display_name)
                        }
                      >
                        {isSelected ? t("selected") : t("select")}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {DISCOVER_ENABLED ? (
          <div className="model-picker-footer">
            <Link
              href={marketplaceHref}
              className="model-picker-link"
              onClick={onClose}
            >
              {t("pickerViewAll")}
            </Link>
          </div>
        ) : null}
      </div>
    </div>
  );

  if (typeof document === "undefined") return modalContent;
  return createPortal(modalContent, document.body);
}
