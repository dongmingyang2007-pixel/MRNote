"use client";

import { useCallback, useEffect, useState, type CSSProperties } from "react";
import {
  Activity,
  ArrowRight,
  BookOpen,
  Brain,
  Loader2,
  MessagesSquare,
  Network,
  RefreshCcw,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { apiGet } from "@/lib/api";

interface StudyInsightsTotals {
  assets: number;
  indexed_assets: number;
  generated_pages: number;
  chunks: number;
  decks: number;
  cards: number;
  new_cards: number;
  due_cards: number;
  weak_cards: number;
  reviewed_this_week: number;
  ai_actions_this_week: number;
  confusions_logged: number;
}

interface StudyInsightsActionCount {
  action_type: string;
  count: number;
}

interface StudyInsightsDay {
  date: string;
  review_count: number;
  ai_action_count: number;
}

interface StudyInsightsDeckPressure {
  deck_id: string;
  deck_name: string;
  total_cards: number;
  due_cards: number;
  last_review_at: string | null;
  next_due_at: string | null;
}

interface StudyInsightsWeakCard {
  card_id: string;
  deck_id: string;
  deck_name: string;
  front: string;
  review_count: number;
  lapse_count: number;
  consecutive_failures: number;
  next_review_at: string | null;
}

interface StudyInsightsRecentAction {
  id: string;
  action_type: string;
  summary: string;
  created_at: string;
}

interface StudyInsights {
  period_start: string;
  period_end: string;
  active_days: number;
  totals: StudyInsightsTotals;
  action_counts: StudyInsightsActionCount[];
  daily_activity: StudyInsightsDay[];
  deck_pressure: StudyInsightsDeckPressure[];
  weak_cards: StudyInsightsWeakCard[];
  recent_actions: StudyInsightsRecentAction[];
}

interface GeneratedPageSummary {
  id: string;
  label: string;
  kind: "overview" | "notes" | "chapter" | "page";
}

interface StudyProgressPanelProps {
  notebookId: string;
  generatedPages: GeneratedPageSummary[];
  onGoToOverview: () => void;
  onGoToAssistant: () => void;
  onGoToDecks: () => void;
  onStartReview: (deckId: string) => void;
  onOpenPage: (pageId: string, title: string) => void;
  onOpenMemoryGraph: () => void;
}

const surfaceStyle: CSSProperties = {
  border: "1px solid rgba(15, 23, 42, 0.08)",
  borderRadius: 18,
  background: "rgba(255,255,255,0.86)",
};

const METRIC_KEYS: Array<keyof StudyInsightsTotals> = [
  "indexed_assets",
  "generated_pages",
  "cards",
  "due_cards",
  "reviewed_this_week",
  "ai_actions_this_week",
];

export default function StudyProgressPanel({
  notebookId,
  generatedPages,
  onGoToOverview,
  onGoToAssistant,
  onGoToDecks,
  onStartReview,
  onOpenPage,
  onOpenMemoryGraph,
}: StudyProgressPanelProps) {
  const locale = useLocale();
  const t = useTranslations("console-notebooks");
  const [insights, setInsights] = useState<StudyInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiGet<StudyInsights>(
        `/api/v1/notebooks/${notebookId}/study/insights`,
      );
      setInsights(data);
    } catch (err) {
      setInsights(null);
      setError(
        err instanceof Error ? err.message : t("study.progress.loadFailed"),
      );
    } finally {
      setLoading(false);
    }
  }, [notebookId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div
        data-testid="study-progress-panel"
        style={{
          ...surfaceStyle,
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 10,
          color: "var(--console-text-muted, #64748b)",
        }}
      >
        <Loader2 size={18} className="animate-spin" />
        {t("study.progress.loading")}
      </div>
    );
  }

  if (error || !insights) {
    return (
      <div
        data-testid="study-progress-panel"
        style={{
          ...surfaceStyle,
          height: "100%",
          padding: 24,
          display: "grid",
          placeItems: "center",
          textAlign: "center",
          gap: 10,
        }}
      >
        <TriangleAlert size={20} style={{ color: "#b45309" }} />
        <div style={{ fontSize: "0.875rem", fontWeight: 700 }}>
          {t("study.progress.loadFailed")}
        </div>
        <button
          type="button"
          onClick={() => {
            void load();
          }}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "8px 12px",
            borderRadius: 999,
            border: "1px solid rgba(15, 23, 42, 0.08)",
            background: "#fff",
            cursor: "pointer",
          }}
        >
          <RefreshCcw size={14} />
          {t("study.progress.refresh")}
        </button>
      </div>
    );
  }

  const totals = insights.totals;
  const maxDailyValue = Math.max(
    1,
    ...insights.daily_activity.map((item) => item.review_count + item.ai_action_count),
  );
  const actionCounts = new Map(
    insights.action_counts.map((item) => [item.action_type, item.count]),
  );
  const formatDayLabel = (value: string): string =>
    new Intl.DateTimeFormat(locale, {
      month: "numeric",
      day: "numeric",
    }).format(new Date(`${value}T00:00:00Z`));
  const formatDateTime = (value: string | null): string => {
    if (!value) return "";
    return new Intl.DateTimeFormat(locale, {
      month: "numeric",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date(value));
  };
  const preferredReviewDeck =
    insights.deck_pressure.find((item) => item.due_cards > 0) ||
    insights.deck_pressure[0] ||
    null;
  const notesPage = generatedPages.find((page) => page.kind === "notes") || null;
  const overviewPage = generatedPages.find((page) => page.kind === "overview") || null;

  const status: "building" | "atRisk" | "active" | "ready" =
    totals.indexed_assets === 0
      ? "building"
      : totals.due_cards >= Math.max(6, Math.ceil(Math.max(1, totals.cards) * 0.25))
        ? "atRisk"
        : totals.reviewed_this_week > 0 || insights.active_days >= 3
          ? "active"
          : "ready";

  const headlineKey =
    totals.indexed_assets === 0
      ? "study.progress.headline.building"
      : totals.cards === 0
        ? "study.progress.headline.indexed"
        : status === "atRisk"
          ? "study.progress.headline.atRisk"
          : status === "active"
            ? "study.progress.headline.active"
            : "study.progress.headline.ready";

  const primaryAction = (() => {
    if (totals.indexed_assets === 0) {
      return {
        label: t("study.progress.actions.goToOverview"),
        onClick: onGoToOverview,
        icon: BookOpen,
      };
    }
    if (preferredReviewDeck && preferredReviewDeck.due_cards > 0) {
      return {
        label: t("study.progress.actions.reviewDue", { count: preferredReviewDeck.due_cards }),
        onClick: () => onStartReview(preferredReviewDeck.deck_id),
        icon: Brain,
      };
    }
    if (totals.cards === 0) {
      return {
        label: t("study.progress.actions.openDecks"),
        onClick: onGoToDecks,
        icon: Sparkles,
      };
    }
    return {
      label: t("study.progress.actions.openAssistant"),
      onClick: onGoToAssistant,
      icon: MessagesSquare,
    };
  })();

  return (
    <div
      data-testid="study-progress-panel"
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 1.2fr) minmax(320px, 0.95fr)",
        gap: 18,
        height: "100%",
        minHeight: 0,
      }}
    >
      <div style={{ display: "grid", gap: 18, minHeight: 0, overflowY: "auto" }}>
        <section style={{ ...surfaceStyle, padding: 20 }}>
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              justifyContent: "space-between",
              gap: 16,
              flexWrap: "wrap",
            }}
          >
            <div style={{ maxWidth: 780 }}>
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "6px 10px",
                  borderRadius: 999,
                  background:
                    status === "active"
                      ? "rgba(16, 185, 129, 0.1)"
                      : status === "atRisk"
                        ? "rgba(217, 119, 6, 0.12)"
                        : "var(--console-accent-soft, rgba(13, 148, 136, 0.1))",
                  color:
                    status === "active"
                      ? "#047857"
                      : status === "atRisk"
                        ? "#b45309"
                        : "var(--console-accent, #0D9488)",
                  fontSize: "0.75rem",
                  fontWeight: 700,
                }}
              >
                <Activity size={14} />
                {t(`study.progress.status.${status}`)}
              </div>
              <h2
                style={{
                  margin: "12px 0 0",
                  fontSize: "1.35rem",
                  color: "var(--console-text-primary, #0f172a)",
                }}
              >
                {t(headlineKey, {
                  reviewed: totals.reviewed_this_week,
                  activeDays: insights.active_days,
                  due: totals.due_cards,
                })}
              </h2>
              <div
                style={{
                  marginTop: 12,
                  display: "grid",
                  gap: 8,
                  color: "var(--console-text-secondary, #475569)",
                  fontSize: "0.8125rem",
                  lineHeight: 1.7,
                }}
              >
                <div>
                  {t("study.progress.summary.materials", {
                    indexed: totals.indexed_assets,
                    assets: totals.assets,
                    chunks: totals.chunks,
                    pages: totals.generated_pages,
                  })}
                </div>
                <div>
                  {t("study.progress.summary.recall", {
                    cards: totals.cards,
                    due: totals.due_cards,
                    weak: totals.weak_cards,
                    new: totals.new_cards,
                  })}
                </div>
                <div>
                  {t("study.progress.summary.ai", {
                    asks: actionCounts.get("study.ask") ?? 0,
                    flashcards: actionCounts.get("study.flashcards") ?? 0,
                    quizzes: actionCounts.get("study.quiz") ?? 0,
                    confusions: totals.confusions_logged,
                  })}
                </div>
              </div>
            </div>

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
              <button
                type="button"
                onClick={primaryAction.onClick}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "8px 12px",
                  borderRadius: 999,
                  border: "none",
                  background: "var(--console-cta-gradient, linear-gradient(135deg, #F97316, #EA6A0F))",
                  color: "#fff",
                  cursor: "pointer",
                }}
              >
                <primaryAction.icon size={14} />
                {primaryAction.label}
              </button>
              <button
                type="button"
                onClick={() => {
                  void load();
                }}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "8px 12px",
                  borderRadius: 999,
                  border: "1px solid rgba(15, 23, 42, 0.08)",
                  background: "#fff",
                  cursor: "pointer",
                }}
              >
                <RefreshCcw size={14} />
                {t("study.progress.refresh")}
              </button>
            </div>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(6, minmax(0, 1fr))",
              gap: 12,
              marginTop: 18,
            }}
          >
            {METRIC_KEYS.map((key) => (
              <div
                key={key}
                style={{
                  borderRadius: 16,
                  padding: "14px 16px",
                  background: "rgba(248, 250, 252, 0.88)",
                  border: "1px solid rgba(15, 23, 42, 0.08)",
                }}
              >
                <div
                  style={{
                    fontSize: "0.6875rem",
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                    color: "var(--console-text-muted, #64748b)",
                  }}
                >
                  {t(`study.progress.metrics.${key}`)}
                </div>
                <div
                  style={{
                    marginTop: 8,
                    fontSize: "1.05rem",
                    fontWeight: 700,
                    color: "var(--console-text-primary, #0f172a)",
                  }}
                >
                  {totals[key]}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section style={{ ...surfaceStyle, padding: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
            <Activity size={16} />
            <strong>{t("study.progress.activityTitle")}</strong>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(7, minmax(0, 1fr))", gap: 10 }}>
            {insights.daily_activity.map((item) => {
              const total = item.review_count + item.ai_action_count;
              const height = total === 0 ? 8 : Math.max(18, Math.round((total / maxDailyValue) * 84));
              return (
                <div
                  key={item.date}
                  style={{
                    display: "grid",
                    justifyItems: "center",
                    gap: 8,
                    padding: "12px 8px",
                    borderRadius: 14,
                    background: "rgba(248, 250, 252, 0.88)",
                    border: "1px solid rgba(15, 23, 42, 0.08)",
                  }}
                >
                  <div
                    style={{
                      height: 90,
                      width: "100%",
                      display: "flex",
                      alignItems: "flex-end",
                      justifyContent: "center",
                    }}
                  >
                    <div
                      style={{
                        width: 18,
                        height,
                        borderRadius: 999,
                        background:
                          total === 0
                            ? "rgba(148, 163, 184, 0.2)"
                            : "linear-gradient(180deg, rgba(13, 148, 136, 0.95), rgba(249, 115, 22, 0.85))",
                      }}
                    />
                  </div>
                  <div style={{ fontSize: "0.6875rem", color: "var(--console-text-muted, #64748b)" }}>
                    {formatDayLabel(item.date)}
                  </div>
                  <div style={{ fontSize: "0.6875rem", textAlign: "center", color: "var(--console-text-secondary, #475569)" }}>
                    {t("study.progress.activityReviews", { count: item.review_count })}
                    <br />
                    {t("study.progress.activityAi", { count: item.ai_action_count })}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>

      <div style={{ display: "grid", gap: 18, minHeight: 0, overflowY: "auto" }}>
        <section style={{ ...surfaceStyle, padding: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
            <Brain size={16} />
            <strong>{t("study.progress.deckPressureTitle")}</strong>
          </div>
          {insights.deck_pressure.length === 0 ? (
            <div style={{ fontSize: "0.8125rem", color: "var(--console-text-muted, #64748b)", lineHeight: 1.6 }}>
              {t("study.progress.deckPressureEmpty")}
            </div>
          ) : (
            <div style={{ display: "grid", gap: 10 }}>
              {insights.deck_pressure.map((deck) => (
                <div
                  key={deck.deck_id}
                  style={{
                    padding: "12px 14px",
                    borderRadius: 14,
                    border: "1px solid rgba(15, 23, 42, 0.08)",
                    background: "rgba(248, 250, 252, 0.88)",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                    <div>
                      <div style={{ fontSize: "0.875rem", fontWeight: 700, color: "var(--console-text-primary, #0f172a)" }}>
                        {deck.deck_name}
                      </div>
                      <div style={{ marginTop: 4, fontSize: "0.75rem", color: "var(--console-text-muted, #64748b)" }}>
                        {t("study.progress.deckPressureMeta", {
                          due: deck.due_cards,
                          cards: deck.total_cards,
                        })}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => onStartReview(deck.deck_id)}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 6,
                        padding: "7px 10px",
                        borderRadius: 999,
                        border: "1px solid rgba(15, 23, 42, 0.08)",
                        background: "#fff",
                        cursor: "pointer",
                      }}
                    >
                      {t("study.progress.actions.reviewDeck")}
                      <ArrowRight size={13} />
                    </button>
                  </div>
                  <div style={{ marginTop: 10, fontSize: "0.6875rem", color: "var(--console-text-muted, #64748b)" }}>
                    {deck.last_review_at
                      ? t("study.progress.deckPressureLastReview", {
                          date: formatDateTime(deck.last_review_at),
                        })
                      : t("study.progress.deckPressureNeverReviewed")}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section style={{ ...surfaceStyle, padding: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
            <TriangleAlert size={16} />
            <strong>{t("study.progress.weakCardsTitle")}</strong>
          </div>
          {insights.weak_cards.length === 0 ? (
            <div style={{ fontSize: "0.8125rem", color: "var(--console-text-muted, #64748b)", lineHeight: 1.6 }}>
              {t("study.progress.weakCardsEmpty")}
            </div>
          ) : (
            <div style={{ display: "grid", gap: 10 }}>
              {insights.weak_cards.map((card) => (
                <div
                  key={card.card_id}
                  style={{
                    padding: "12px 14px",
                    borderRadius: 14,
                    border: "1px solid rgba(15, 23, 42, 0.08)",
                    background: "rgba(255,255,255,0.92)",
                  }}
                >
                  <div style={{ fontSize: "0.75rem", color: "var(--console-text-muted, #64748b)" }}>
                    {card.deck_name}
                  </div>
                  <div style={{ marginTop: 6, fontSize: "0.8125rem", fontWeight: 700, color: "var(--console-text-primary, #0f172a)", lineHeight: 1.6 }}>
                    {card.front}
                  </div>
                  <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <span style={{ fontSize: "0.6875rem", color: "var(--console-text-muted, #64748b)" }}>
                      {t("study.progress.weakCardLapses", { count: card.lapse_count })}
                    </span>
                    <span style={{ fontSize: "0.6875rem", color: "var(--console-text-muted, #64748b)" }}>
                      {t("study.progress.weakCardFailures", { count: card.consecutive_failures })}
                    </span>
                    <span style={{ fontSize: "0.6875rem", color: "var(--console-text-muted, #64748b)" }}>
                      {t("study.progress.weakCardReviews", { count: card.review_count })}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section style={{ ...surfaceStyle, padding: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
            <Sparkles size={16} />
            <strong>{t("study.progress.nextMovesTitle")}</strong>
          </div>
          <div style={{ display: "grid", gap: 8 }}>
            {notesPage ? (
              <button
                type="button"
                onClick={() => onOpenPage(notesPage.id, notesPage.label)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 12,
                  padding: "10px 12px",
                  borderRadius: 14,
                  border: "1px solid rgba(15, 23, 42, 0.08)",
                  background: "#fff",
                  cursor: "pointer",
                }}
              >
                <span>{t("study.progress.actions.openNotes")}</span>
                <ArrowRight size={14} />
              </button>
            ) : null}
            {overviewPage ? (
              <button
                type="button"
                onClick={() => onOpenPage(overviewPage.id, overviewPage.label)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 12,
                  padding: "10px 12px",
                  borderRadius: 14,
                  border: "1px solid rgba(15, 23, 42, 0.08)",
                  background: "#fff",
                  cursor: "pointer",
                }}
              >
                <span>{t("study.progress.actions.openOverviewPage")}</span>
                <ArrowRight size={14} />
              </button>
            ) : null}
            <button
              type="button"
              onClick={onGoToAssistant}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
                padding: "10px 12px",
                borderRadius: 14,
                border: "1px solid rgba(15, 23, 42, 0.08)",
                background: "#fff",
                cursor: "pointer",
              }}
            >
              <span>{t("study.progress.actions.openAssistant")}</span>
              <ArrowRight size={14} />
            </button>
            <button
              type="button"
              onClick={onOpenMemoryGraph}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
                padding: "10px 12px",
                borderRadius: 14,
                border: "1px solid rgba(15, 23, 42, 0.08)",
                background: "#fff",
                cursor: "pointer",
              }}
            >
              <span>{t("study.progress.actions.openMemory")}</span>
              <Network size={14} />
            </button>
          </div>
        </section>

        <section style={{ ...surfaceStyle, padding: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
            <MessagesSquare size={16} />
            <strong>{t("study.progress.recentActionsTitle")}</strong>
          </div>
          {insights.recent_actions.length === 0 ? (
            <div style={{ fontSize: "0.8125rem", color: "var(--console-text-muted, #64748b)", lineHeight: 1.6 }}>
              {t("study.progress.recentActionsEmpty")}
            </div>
          ) : (
            <div style={{ display: "grid", gap: 10 }}>
              {insights.recent_actions.map((item) => (
                <div
                  key={item.id}
                  style={{
                    padding: "12px 14px",
                    borderRadius: 14,
                    border: "1px solid rgba(15, 23, 42, 0.08)",
                    background: "rgba(248, 250, 252, 0.88)",
                  }}
                >
                  <div style={{ fontSize: "0.6875rem", color: "var(--console-text-muted, #64748b)" }}>
                    {t(`study.progress.actionType.${item.action_type}`)} · {formatDateTime(item.created_at)}
                  </div>
                  <div style={{ marginTop: 6, fontSize: "0.8125rem", color: "var(--console-text-primary, #0f172a)", lineHeight: 1.6 }}>
                    {item.summary}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
