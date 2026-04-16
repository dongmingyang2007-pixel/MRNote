"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Plus, Play, Trash2, Sparkles, ClipboardList } from "lucide-react";
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
  const [cards, setCards] = useState<Card[]>([]);
  const [newFront, setNewFront] = useState("");
  const [newBack, setNewBack] = useState("");
  const [showGen, setShowGen] = useState(false);
  const [showQuiz, setShowQuiz] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await apiGet<{ items: Card[]; next_cursor: string | null }>(
        `/api/v1/decks/${deckId}/cards`,
      );
      setCards(r.items || []);
    } catch {
      setCards([]);
    }
  }, [deckId]);

  useEffect(() => { void load(); }, [load]);

  const handleCreate = useCallback(async () => {
    if (!newFront.trim() || !newBack.trim()) return;
    await apiPost(`/api/v1/decks/${deckId}/cards`, {
      front: newFront.trim(),
      back: newBack.trim(),
    });
    setNewFront(""); setNewBack("");
    await load();
  }, [newFront, newBack, deckId, load]);

  const handleDelete = useCallback(async (cardId: string) => {
    await apiDelete(`/api/v1/cards/${cardId}`);
    await load();
  }, [load]);

  return (
    <div className="cards-panel" data-testid="cards-panel" style={{ padding: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 12 }}>
        <button
          type="button"
          onClick={onBack}
          style={{ padding: 4, border: "none", background: "transparent", cursor: "pointer" }}
        >
          <ArrowLeft size={16} />
        </button>
        <strong style={{ flex: 1 }}>Cards ({cards.length})</strong>
        <button
          type="button"
          onClick={() => onStartReview(deckId)}
          title="Start Review"
          data-testid="cards-panel-review"
          style={{ padding: 6, border: "1px solid #e5e7eb", borderRadius: 6, background: "#fff", cursor: "pointer" }}
        >
          <Play size={14} /> Review
        </button>
        <button
          type="button"
          onClick={() => setShowGen(true)}
          title="Generate Flashcards"
          data-testid="cards-panel-generate"
          style={{ padding: 6, border: "1px solid #e5e7eb", borderRadius: 6, background: "#fff", cursor: "pointer" }}
        >
          <Sparkles size={14} /> Generate
        </button>
        <button
          type="button"
          onClick={() => setShowQuiz(true)}
          title="Quiz"
          data-testid="cards-panel-quiz"
          style={{ padding: 6, border: "1px solid #e5e7eb", borderRadius: 6, background: "#fff", cursor: "pointer" }}
        >
          <ClipboardList size={14} /> Quiz
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 6, marginBottom: 12 }}>
        <input
          type="text"
          placeholder="Front"
          value={newFront}
          onChange={(e) => setNewFront(e.target.value)}
          style={{ padding: "6px 10px", border: "1px solid #e5e7eb", borderRadius: 6 }}
        />
        <input
          type="text"
          placeholder="Back"
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
        <p style={{ color: "#888", fontSize: 12 }}>No cards yet.</p>
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
                  {c.source_type} · {c.review_count} reviews
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
