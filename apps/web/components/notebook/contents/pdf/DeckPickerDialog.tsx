"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Loader2,
  Plus,
  Sparkles,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { apiGet, apiPost } from "@/lib/api";

interface DeckPickerDialogProps {
  open: boolean;
  notebookId: string;
  text: string;
  pageNumber: number | null;
  documentTitle?: string;
  onClose: () => void;
  onGenerated?: (deckId: string, cardCount: number) => void;
}

interface Deck {
  id: string;
  name: string;
  card_count: number;
}

interface FlashcardResult {
  cards: Array<{ front: string; back: string }>;
  card_ids?: string[] | null;
}

export default function DeckPickerDialog({
  open,
  notebookId,
  text,
  pageNumber,
  documentTitle,
  onClose,
  onGenerated,
}: DeckPickerDialogProps) {
  const t = useTranslations("console-notebooks");
  const [decks, setDecks] = useState<Deck[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generatingDeckId, setGeneratingDeckId] = useState<string | null>(null);
  const [creatingNew, setCreatingNew] = useState(false);
  const [count, setCount] = useState(5);
  const [newDeckName, setNewDeckName] = useState("");
  const [success, setSuccess] = useState<{
    deckId: string;
    cardCount: number;
  } | null>(null);

  const loadDecks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiGet<{ items: Deck[] }>(
        `/api/v1/notebooks/${notebookId}/decks?limit=100`,
      );
      setDecks(data.items || []);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t("references.loadFailed"),
      );
    } finally {
      setLoading(false);
    }
  }, [notebookId, t]);

  useEffect(() => {
    if (!open) return;
    setSuccess(null);
    setError(null);
    setNewDeckName("");
    void loadDecks();
  }, [loadDecks, open]);

  const generate = useCallback(
    async (deckId: string) => {
      if (generatingDeckId) return;
      setGeneratingDeckId(deckId);
      setError(null);
      try {
        const result = await apiPost<FlashcardResult>(
          `/api/v1/ai/study/flashcards`,
          {
            source_type: "text",
            source_id: notebookId,
            text,
            count,
            deck_id: deckId,
          },
        );
        const cardCount = result.card_ids?.length || result.cards.length;
        setSuccess({ deckId, cardCount });
        onGenerated?.(deckId, cardCount);
        window.setTimeout(() => onClose(), 700);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : t("pdfSelection.generateFailed"),
        );
      } finally {
        setGeneratingDeckId(null);
      }
    },
    [count, generatingDeckId, notebookId, onClose, onGenerated, t, text],
  );

  const createAndGenerate = useCallback(async () => {
    const name =
      newDeckName.trim() ||
      (documentTitle
        ? `${documentTitle}${pageNumber ? ` · p.${pageNumber}` : ""}`
        : t("pdfSelection.newDeckName"));
    if (generatingDeckId || creatingNew) return;
    setCreatingNew(true);
    setError(null);
    try {
      const newDeck = await apiPost<Deck>(
        `/api/v1/notebooks/${notebookId}/decks`,
        { name },
      );
      await generate(newDeck.id);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t("pdfSelection.generateFailed"),
      );
    } finally {
      setCreatingNew(false);
    }
  }, [
    creatingNew,
    documentTitle,
    generate,
    generatingDeckId,
    newDeckName,
    notebookId,
    pageNumber,
    t,
  ]);

  if (!open) return null;

  return (
    <div
      className="quote-to-page-dialog deck-picker-dialog"
      role="dialog"
      aria-modal="true"
      data-testid="deck-picker-dialog"
    >
      <div className="quote-to-page-dialog__scrim" onClick={onClose} />
      <div className="quote-to-page-dialog__panel">
        <header>
          <strong>
            <Sparkles size={14} /> {t("pdfSelection.flashcardsDialogTitle")}
          </strong>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("pdfSelection.dismiss")}
          >
            <X size={14} />
          </button>
        </header>
        <p className="quote-to-page-dialog__hint">
          {t("pdfSelection.flashcardsDialogHint")}
        </p>

        {error ? (
          <div className="quote-to-page-dialog__error">
            <AlertCircle size={14} />
            {error}
          </div>
        ) : null}

        <label className="deck-picker-dialog__count">
          <span>{t("pdfSelection.flashcardCount")}</span>
          <input
            type="number"
            min={1}
            max={20}
            value={count}
            onChange={(e) =>
              setCount(
                Math.max(1, Math.min(20, Number(e.target.value) || 5)),
              )
            }
          />
        </label>

        <div className="deck-picker-dialog__new">
          <input
            type="text"
            value={newDeckName}
            onChange={(e) => setNewDeckName(e.target.value)}
            placeholder={t("pdfSelection.newDeckPlaceholder")}
          />
          <button
            type="button"
            onClick={() => void createAndGenerate()}
            disabled={!!generatingDeckId || creatingNew}
          >
            {creatingNew ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Plus size={14} />
            )}
            {t("pdfSelection.createDeckAndGenerate")}
          </button>
        </div>

        <div className="quote-to-page-dialog__list">
          {loading ? (
            <div className="quote-to-page-dialog__empty">
              <Loader2 size={20} className="animate-spin" />
            </div>
          ) : decks.length === 0 ? (
            <div className="quote-to-page-dialog__empty">
              <span>{t("pdfSelection.noDecksYet")}</span>
            </div>
          ) : (
            <ul>
              {decks.map((deck) => {
                const generating = generatingDeckId === deck.id;
                const ok = success?.deckId === deck.id;
                return (
                  <li key={deck.id}>
                    <button
                      type="button"
                      onClick={() => void generate(deck.id)}
                      disabled={!!generatingDeckId || creatingNew}
                      data-testid="deck-picker-item"
                    >
                      <Sparkles size={14} />
                      <span>{deck.name}</span>
                      <small>
                        {t("study.decks.cards", { count: deck.card_count })}
                      </small>
                      {generating ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : ok ? (
                        <CheckCircle2 size={14} />
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
