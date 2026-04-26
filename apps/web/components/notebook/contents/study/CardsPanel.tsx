"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Plus, Play, Trash2, Sparkles, ClipboardList } from "lucide-react";
import { useTranslations } from "next-intl";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import GenerateFlashcardsModal from "./GenerateFlashcardsModal";
import QuizModal from "./QuizModal";

interface Card {
  id: string;
  front: string;
  back: string;
  source_type: string;
  review_count: number;
  next_review_at: string | null;
}

interface Props {
  deckId: string;
  notebookId: string;
  onBack: () => void;
  onStartReview: (deckId: string) => void;
}

export default function CardsPanel({ deckId, notebookId, onBack, onStartReview }: Props) {
  const t = useTranslations("console-notebooks");
  const [cards, setCards] = useState<Card[]>([]);
  const [newFront, setNewFront] = useState("");
  const [newBack, setNewBack] = useState("");
  const [showGen, setShowGen] = useState(false);
  const [showQuiz, setShowQuiz] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const fetchCards = useCallback(async () => {
    try {
      const r = await apiGet<{ items: Card[]; next_cursor: string | null }>(
        `/api/v1/decks/${deckId}/cards`,
      );
      return r.items || [];
    } catch {
      return [];
    }
  }, [deckId]);

  const load = useCallback(async () => {
    setCards(await fetchCards());
  }, [fetchCards]);

  useEffect(() => {
    let cancelled = false;
    void fetchCards().then((items) => {
      if (!cancelled) setCards(items);
    });
    return () => {
      cancelled = true;
    };
  }, [fetchCards]);

  const handleCreate = useCallback(async () => {
    if (!newFront.trim() || !newBack.trim()) return;
    setErrorMessage(null);
    try {
      await apiPost(`/api/v1/decks/${deckId}/cards`, {
        front: newFront.trim(),
        back: newBack.trim(),
      });
      setNewFront(""); setNewBack("");
      await load();
    } catch (err) {
      setErrorMessage(
        err instanceof Error ? err.message : t("study.cards.createFailed"),
      );
    }
  }, [newFront, newBack, deckId, load, t]);

  const handleDelete = useCallback(async (cardId: string) => {
    setErrorMessage(null);
    try {
      await apiDelete(`/api/v1/cards/${cardId}`);
      await load();
    } catch (err) {
      setErrorMessage(
        err instanceof Error ? err.message : t("study.cards.deleteFailed"),
      );
    }
  }, [load, t]);

  return (
    <div className="cards-panel" data-testid="cards-panel" style={{ padding: 12 }}>
      {errorMessage && (
        <div
          role="alert"
          style={{
            padding: "6px 10px",
            marginBottom: 10,
            borderRadius: 6,
            background: "rgba(220, 38, 38, 0.06)",
            border: "1px solid rgba(220, 38, 38, 0.2)",
            color: "#b91c1c",
            fontSize: 12,
          }}
        >
          {errorMessage}
        </div>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 12 }}>
        <button
          type="button"
          onClick={onBack}
          style={{ padding: 4, border: "none", background: "transparent", cursor: "pointer" }}
        >
          <ArrowLeft size={16} />
        </button>
        <strong style={{ flex: 1 }}>{t("study.cards.title", { count: cards.length })}</strong>
        <button
          type="button"
          onClick={() => onStartReview(deckId)}
          title={t("study.cards.review")}
          data-testid="cards-panel-review"
          style={{ padding: 6, border: "1px solid #e5e7eb", borderRadius: 6, background: "#fff", cursor: "pointer" }}
        >
          <Play size={14} /> {t("study.cards.review")}
        </button>
        <button
          type="button"
          onClick={() => setShowGen(true)}
          title={t("study.cards.generate")}
          data-testid="cards-panel-generate"
          style={{ padding: 6, border: "1px solid #e5e7eb", borderRadius: 6, background: "#fff", cursor: "pointer" }}
        >
          <Sparkles size={14} /> {t("study.cards.generate")}
        </button>
        <button
          type="button"
          onClick={() => setShowQuiz(true)}
          title={t("study.cards.quiz")}
          data-testid="cards-panel-quiz"
          style={{ padding: 6, border: "1px solid #e5e7eb", borderRadius: 6, background: "#fff", cursor: "pointer" }}
        >
          <ClipboardList size={14} /> {t("study.cards.quiz")}
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 6, marginBottom: 12 }}>
        <input
          type="text"
          placeholder={t("study.cards.frontPlaceholder")}
          value={newFront}
          onChange={(e) => setNewFront(e.target.value)}
          style={{ padding: "6px 10px", border: "1px solid #e5e7eb", borderRadius: 6 }}
        />
        <input
          type="text"
          placeholder={t("study.cards.backPlaceholder")}
          value={newBack}
          onChange={(e) => setNewBack(e.target.value)}
          style={{ padding: "6px 10px", border: "1px solid #e5e7eb", borderRadius: 6 }}
        />
        <button
          type="button"
          onClick={handleCreate}
          disabled={!newFront.trim() || !newBack.trim()}
          data-testid="cards-panel-create"
          style={{ padding: "6px 12px", borderRadius: 6, border: "1px solid #e5e7eb", background: "#fff", cursor: "pointer" }}
        >
          <Plus size={14} />
        </button>
      </div>

      {cards.length === 0 ? (
        <p style={{ color: "#888", fontSize: 12 }}>{t("study.cards.empty")}</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {cards.map((c) => (
            <li
              key={c.id}
              data-testid="card-row"
              style={{
                padding: 8,
                borderBottom: "1px solid #eee",
                display: "flex",
                alignItems: "flex-start",
                gap: 8,
              }}
            >
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 12 }}>{c.front}</div>
                <div style={{ color: "#666", fontSize: 12 }}>{c.back}</div>
                <div style={{ color: "#9ca3af", fontSize: 10, marginTop: 2 }}>
                  {c.source_type} · {t("study.cards.reviewCount", { count: c.review_count })}
                </div>
              </div>
              <button
                type="button"
                onClick={() => void handleDelete(c.id)}
                style={{ padding: 2, border: "none", background: "transparent", cursor: "pointer", color: "#9ca3af" }}
              >
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {showGen && (
        <GenerateFlashcardsModal
          notebookId={notebookId}
          deckId={deckId}
          onClose={() => { setShowGen(false); void load(); }}
        />
      )}
      {showQuiz && (
        <QuizModal
          notebookId={notebookId}
          onClose={() => setShowQuiz(false)}
        />
      )}
    </div>
  );
}
