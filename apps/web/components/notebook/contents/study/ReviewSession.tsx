"use client";

import { useCallback, useEffect, useState } from "react";
import { Eye, Flag } from "lucide-react";
import { useTranslations } from "next-intl";
import { apiPost } from "@/lib/api";

interface Card {
  id: string;
  front: string;
  back: string;
  review_count: number;
  days_since_last: number;
}

interface Props {
  deckId: string;
  onExit: () => void;
}

export default function ReviewSession({ deckId, onExit }: Props) {
  const t = useTranslations("console-notebooks");
  const [card, setCard] = useState<Card | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [empty, setEmpty] = useState(false);
  const [reviewed, setReviewed] = useState(0);

  const RATINGS: { label: string; value: 1 | 2 | 3 | 4 }[] = [
    { label: t("study.review.again"), value: 1 },
    { label: t("study.review.hard"), value: 2 },
    { label: t("study.review.good"), value: 3 },
    { label: t("study.review.easy"), value: 4 },
  ];

  const fetchNext = useCallback(async () => {
    setRevealed(false);
    try {
      const r = await apiPost<{ card: Card | null; queue_empty?: boolean }>(
        `/api/v1/decks/${deckId}/review/next`,
        {},
      );
      if (r.card) {
        setCard(r.card);
        setEmpty(false);
      } else {
        setCard(null);
        setEmpty(true);
      }
    } catch {
      setCard(null);
      setEmpty(true);
    }
  }, [deckId]);

  useEffect(() => { void fetchNext(); }, [fetchNext]);

  const handleRate = useCallback(
    async (rating: 1 | 2 | 3 | 4) => {
      if (!card) return;
      await apiPost(`/api/v1/cards/${card.id}/review`, { rating });
      setReviewed((n) => n + 1);
      await fetchNext();
    },
    [card, fetchNext],
  );

  const handleMarkConfused = useCallback(async () => {
    if (!card) return;
    await apiPost(`/api/v1/cards/${card.id}/review`, {
      rating: 1,
      marked_confused: true,
    });
    setReviewed((n) => n + 1);
    await fetchNext();
  }, [card, fetchNext]);

  if (empty) {
    return (
      <div data-testid="review-empty" style={{ padding: 32, textAlign: "center" }}>
        <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>
          {t("study.review.queueEmpty")}
        </div>
        <div style={{ color: "#888", fontSize: 13, marginBottom: 16 }}>
          {t("study.review.reviewed", { count: reviewed })}
        </div>
        <button
          type="button"
          onClick={onExit}
          style={{ padding: "6px 16px", border: "1px solid #e5e7eb", borderRadius: 6, background: "#fff", cursor: "pointer" }}
        >
          {t("study.review.backToDecks")}
        </button>
      </div>
    );
  }

  if (!card) {
    return <div style={{ padding: 16, color: "#888" }}>{t("study.review.loading")}</div>;
  }

  return (
    <div className="review-session" data-testid="review-session" style={{ padding: 16 }}>
      <div
        style={{
          minHeight: 120,
          padding: 20,
          border: "1px solid #e5e7eb",
          borderRadius: 10,
          background: "#fafbfd",
          marginBottom: 16,
        }}
      >
        <div style={{ fontSize: 11, color: "#9ca3af", marginBottom: 6 }}>
          {t("study.review.questionLabel", { count: card.review_count })}
        </div>
        <div data-testid="review-front" style={{ fontSize: 15, lineHeight: 1.55 }}>
          {card.front}
        </div>
      </div>

      {revealed ? (
        <div
          style={{
            minHeight: 120,
            padding: 20,
            border: "1px solid #2563eb33",
            background: "rgba(37,99,235,0.04)",
            borderRadius: 10,
            marginBottom: 16,
          }}
        >
          <div style={{ fontSize: 11, color: "#9ca3af", marginBottom: 6 }}>{t("study.review.answerLabel")}</div>
          <div data-testid="review-back" style={{ fontSize: 15, lineHeight: 1.55 }}>
            {card.back}
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setRevealed(true)}
          data-testid="review-reveal"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "10px 16px",
            margin: "0 auto 16px",
            border: "1px solid #e5e7eb",
            borderRadius: 8,
            background: "#fff",
            cursor: "pointer",
          }}
        >
          <Eye size={14} /> {t("study.review.revealAnswer")}
        </button>
      )}

      {revealed && (
        <>
          <div style={{ display: "flex", gap: 6, justifyContent: "center", marginBottom: 12 }}>
            {RATINGS.map((r) => (
              <button
                key={r.value}
                type="button"
                data-testid={`review-rate-${r.value}`}
                onClick={() => void handleRate(r.value)}
                style={{
                  padding: "8px 14px",
                  border: "1px solid #e5e7eb",
                  borderRadius: 6,
                  background: r.value === 1 ? "#fee2e2" : r.value === 4 ? "#d1fae5" : "#fff",
                  cursor: "pointer",
                  fontSize: 12,
                  fontWeight: 600,
                }}
              >
                {r.label}
              </button>
            ))}
          </div>
          <div style={{ textAlign: "center" }}>
            <button
              type="button"
              onClick={() => void handleMarkConfused()}
              data-testid="review-mark-confused"
              style={{
                padding: "4px 10px",
                border: "none",
                background: "transparent",
                cursor: "pointer",
                color: "#b91c1c",
                fontSize: 11,
              }}
            >
              <Flag size={12} /> {t("study.review.markConfused")}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
