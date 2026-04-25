"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { apiGet } from "@/lib/api";

interface AIActionItem {
  id: string;
  action_type: string;
  scope: string;
  status: string;
  model_id: string | null;
  duration_ms: number | null;
  output_summary: string;
  created_at: string;
  usage: { total_tokens: number };
}

interface Props {
  pageId: string;
}

export default function AIActionsList({ pageId }: Props) {
  const t = useTranslations("console-notebooks");
  const [items, setItems] = useState<AIActionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const actionTypeLabels = useMemo<Record<string, string>>(
    () => ({
      ask: t("aiActions.actionType.ask"),
      brainstorm: t("aiActions.actionType.brainstorm"),
      expand: t("ai.actions.expand"),
      explain: t("ai.actions.explain"),
      explain_code: t("ai.actions.explainCode"),
      explain_formula: t("ai.actions.explainFormula"),
      fix_grammar: t("ai.actions.fixGrammar"),
      rewrite: t("ai.actions.rewrite"),
      study_qa: t("aiActions.actionType.studyQa"),
      summarize: t("ai.actions.summarize"),
      to_list: t("ai.actions.toList"),
      translate_en: t("ai.actions.translateEn"),
      translate_zh: t("ai.actions.translateZh"),
      "study.ask": t("study.progress.actionType.study.ask"),
      "study.flashcards": t("study.progress.actionType.study.flashcards"),
      "study.quiz": t("study.progress.actionType.study.quiz"),
      "study.review_card": t("study.progress.actionType.study.review_card"),
    }),
    [t],
  );
  const statusLabels = useMemo<Record<string, string>>(
    () => ({
      completed: t("aiActions.status.completed"),
      done: t("aiActions.status.completed"),
      failed: t("aiActions.status.failed"),
      queued: t("aiActions.status.queued"),
      running: t("aiActions.status.running"),
      success: t("aiActions.status.completed"),
      succeeded: t("aiActions.status.completed"),
    }),
    [t],
  );

  const formatActionType = useCallback(
    (actionType: string) => {
      const normalized = actionType.trim();
      return (
        actionTypeLabels[normalized] ||
        normalized.replace(/[._-]+/g, " ") ||
        t("aiActions.actionType.unknown")
      );
    },
    [actionTypeLabels, t],
  );

  const formatStatus = useCallback(
    (status: string) => {
      const normalized = status.trim().toLowerCase();
      return (
        statusLabels[normalized] ||
        normalized.replace(/[._-]+/g, " ") ||
        t("aiActions.status.unknown")
      );
    },
    [statusLabels, t],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<{
        items: AIActionItem[];
        next_cursor: string | null;
      }>(`/api/v1/pages/${pageId}/ai-actions?limit=50`);
      setItems(data.items || []);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [pageId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div data-testid="ai-actions-list" style={{ padding: 12 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: 8,
        }}
      >
        <h3 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>
          {t("aiActions.title")}
        </h3>
        <button onClick={() => void load()} style={{ fontSize: 12 }}>
          {t("aiActions.refresh")}
        </button>
      </div>
      {loading && (
        <p style={{ fontSize: 12, color: "#888" }}>{t("aiActions.loading")}</p>
      )}
      {!loading && items.length === 0 && (
        <p style={{ fontSize: 12, color: "#888" }}>{t("aiActions.empty")}</p>
      )}
      {!loading && items.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {items.map((it) => (
            <li
              key={it.id}
              data-testid="ai-action-item"
              style={{
                padding: 8,
                borderBottom: "1px solid #eee",
                fontSize: 12,
              }}
            >
              <div style={{ fontWeight: 600 }}>
                {formatActionType(it.action_type)}
              </div>
              <div style={{ color: "#666" }}>
                {formatStatus(it.status)} ·{" "}
                {it.model_id ?? t("aiActions.model.unknown")} ·{" "}
                {t("aiActions.durationMs", { value: it.duration_ms ?? 0 })} ·{" "}
                {t("aiActions.tokens", { count: it.usage.total_tokens })}
              </div>
              <div style={{ color: "#444", marginTop: 2 }}>
                {it.output_summary || "—"}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
