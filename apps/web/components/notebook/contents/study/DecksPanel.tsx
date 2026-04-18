"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Archive, Play } from "lucide-react";
import { useTranslations } from "next-intl";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import CardsPanel from "./CardsPanel";

interface Deck {
  id: string;
  name: string;
  description: string;
  card_count: number;
  archived_at: string | null;
  created_at: string;
}

interface Props {
  notebookId: string;
  onStartReview: (deckId: string) => void;
}

export default function DecksPanel({ notebookId, onStartReview }: Props) {
  const t = useTranslations("console-notebooks");
  const [decks, setDecks] = useState<Deck[]>([]);
  const [activeDeckId, setActiveDeckId] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<{ items: Deck[]; total: number }>(
        `/api/v1/notebooks/${notebookId}/decks`,
      );
      setDecks(data.items || []);
    } catch {
      setDecks([]);
    }
  }, [notebookId]);

  useEffect(() => { void load(); }, [load]);

  const handleCreate = useCallback(async () => {
    if (!newName.trim() || creating) return;
    setCreating(true);
    try {
      await apiPost<Deck>(`/api/v1/notebooks/${notebookId}/decks`, {
        name: newName.trim(),
        description: "",
      });
      setNewName("");
      await load();
    } finally {
      setCreating(false);
    }
  }, [newName, creating, notebookId, load]);

  const handleArchive = useCallback(
    async (deckId: string) => {
      await apiPatch(`/api/v1/decks/${deckId}`, { archived: true });
      await load();
    },
    [load],
  );

  if (activeDeckId) {
    return (
      <CardsPanel
        deckId={activeDeckId}
        notebookId={notebookId}
        onBack={() => setActiveDeckId(null)}
        onStartReview={onStartReview}
      />
    );
  }

  return (
    <div className="decks-panel" data-testid="decks-panel" style={{ padding: 12 }}>
      <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
        <input
          type="text"
          placeholder={t("study.decks.createPlaceholder")}
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          style={{ flex: 1, padding: "6px 10px", border: "1px solid #e5e7eb", borderRadius: 6 }}
        />
        <button
          type="button"
          onClick={handleCreate}
          disabled={creating || !newName.trim()}
          data-testid="decks-panel-create"
          style={{ padding: "6px 12px", borderRadius: 6, border: "1px solid #e5e7eb", background: "#fff", cursor: "pointer" }}
        >
          <Plus size={14} /> {t("study.decks.createBtn")}
        </button>
      </div>

      {decks.length === 0 ? (
        <p style={{ color: "#888", fontSize: 12 }}>{t("study.decks.empty")}</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {decks.map((d) => (
            <li
              key={d.id}
              data-testid="deck-row"
              style={{
                padding: 10,
                borderBottom: "1px solid #eee",
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              <button
                type="button"
                onClick={() => setActiveDeckId(d.id)}
                style={{ flex: 1, textAlign: "left", border: "none", background: "transparent", cursor: "pointer", fontSize: 13 }}
              >
                <div style={{ fontWeight: 600 }}>{d.name}</div>
                <div style={{ color: "#666", fontSize: 11 }}>{t("study.decks.cards", { count: d.card_count })}</div>
              </button>
              <button
                type="button"
                onClick={() => onStartReview(d.id)}
                title={t("study.decks.startReview")}
                data-testid="deck-start-review"
                style={{ padding: 4, border: "none", background: "transparent", cursor: "pointer", color: "#2563eb" }}
              >
                <Play size={16} />
              </button>
              <button
                type="button"
                onClick={() => void handleArchive(d.id)}
                title={t("study.decks.archive")}
                style={{ padding: 4, border: "none", background: "transparent", cursor: "pointer", color: "#9ca3af" }}
              >
                <Archive size={16} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
