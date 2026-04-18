"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { apiGet, apiPost } from "@/lib/api";

interface Deck {
  id: string;
  name: string;
  card_count: number;
}

interface Props {
  notebookId: string;
  onPick: (deck: Deck) => void;
  onCancel: () => void;
}

export default function DeckPickerDialog({ notebookId, onPick, onCancel }: Props) {
  const t = useTranslations("console-notebooks");
  const [decks, setDecks] = useState<Deck[]>([]);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");

  useEffect(() => {
    void apiGet<{ items: Deck[] }>(`/api/v1/notebooks/${notebookId}/decks`)
      .then((r) => setDecks(r.items || []))
      .catch(() => setDecks([]));
  }, [notebookId]);

  const handleCreate = useCallback(async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const created = await apiPost<Deck>(
        `/api/v1/notebooks/${notebookId}/decks`,
        { name: newName.trim(), description: "" },
      );
      onPick(created);
    } catch {
      setCreating(false);
    }
  }, [newName, notebookId, onPick]);

  return (
    <div className="deck-picker" role="dialog" data-testid="deck-picker">
      <div className="deck-picker__header">
        <strong>{t("study.deckPicker.title")}</strong>
        <button type="button" onClick={onCancel} className="deck-picker__close">×</button>
      </div>
      <ul className="deck-picker__list">
        {decks.map((d) => (
          <li key={d.id}>
            <button
              type="button"
              className="deck-picker__item"
              data-testid="deck-picker-item"
              onClick={() => onPick(d)}
            >
              {d.name} <span className="deck-picker__count">({d.card_count})</span>
            </button>
          </li>
        ))}
        {decks.length === 0 && <li className="deck-picker__empty">{t("study.deckPicker.empty")}</li>}
      </ul>
      <div className="deck-picker__create">
        <input
          type="text"
          placeholder={t("study.deckPicker.newDeckPlaceholder")}
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
        <button
          type="button"
          onClick={handleCreate}
          disabled={creating || !newName.trim()}
          data-testid="deck-picker-create"
        >
          {t("study.deckPicker.create")}
        </button>
      </div>
    </div>
  );
}
