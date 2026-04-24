"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { apiGet, apiPost } from "@/lib/api";

interface Props {
  notebookId: string;
  deckId: string;
  onClose: () => void;
}

type SourceType = "page" | "chunk";

interface Page { id: string; title: string; }
interface Asset { id: string; title: string; }
interface Chunk { id: string; heading: string; }

interface GeneratedCard { front: string; back: string; }

export default function GenerateFlashcardsModal({ notebookId, deckId, onClose }: Props) {
  const t = useTranslations("console-notebooks");
  const [sourceType, setSourceType] = useState<SourceType>("page");
  const [pages, setPages] = useState<Page[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [selectedPage, setSelectedPage] = useState("");
  const [selectedAsset, setSelectedAsset] = useState("");
  const [selectedChunk, setSelectedChunk] = useState("");
  const [count, setCount] = useState(10);
  const [generated, setGenerated] = useState<GeneratedCard[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void apiGet<{ items: Page[] }>(`/api/v1/notebooks/${notebookId}/pages`)
      .then((r) => setPages(r.items || []))
      .catch(() => setPages([]));
    void apiGet<{ items: Asset[] }>(`/api/v1/notebooks/${notebookId}/study-assets`)
      .then((r) => setAssets(r.items || []))
      .catch(() => setAssets([]));
  }, [notebookId]);

  useEffect(() => {
    if (!selectedAsset) {
      setChunks([]);
      return;
    }
    void apiGet<{ items: Chunk[] }>(`/api/v1/study-assets/${selectedAsset}/chunks`)
      .then((r) => setChunks(r.items || []))
      .catch(() => setChunks([]));
  }, [selectedAsset]);

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setError(null);
    try {
      const sourceId = sourceType === "page" ? selectedPage : selectedChunk;
      if (!sourceId) {
        setError(t("study.gen.pickSource"));
        return;
      }
      const r = await apiPost<{ cards: GeneratedCard[] }>(
        "/api/v1/ai/study/flashcards",
        { source_type: sourceType, source_id: sourceId, count },
      );
      setGenerated(r.cards || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("study.gen.generationFailed"));
    } finally {
      setGenerating(false);
    }
  }, [sourceType, selectedPage, selectedChunk, count, t]);

  const handleSave = useCallback(async () => {
    if (!generated) return;
    setSaving(true);
    try {
      await Promise.all(
        generated.map((c) =>
          apiPost(`/api/v1/decks/${deckId}/cards`, {
            front: c.front,
            back: c.back,
            source_type: sourceType === "page" ? "page_ai" : "chunk_ai",
            source_ref: sourceType === "page" ? selectedPage : selectedChunk,
          }),
        ),
      );
      onClose();
    } finally {
      setSaving(false);
    }
  }, [generated, deckId, sourceType, selectedPage, selectedChunk, onClose]);

  return (
    <div
      role="dialog"
      data-testid="generate-flashcards-modal"
      style={{
        position: "fixed",
        top: 0, left: 0, right: 0, bottom: 0,
        background: "rgba(17,24,39,0.35)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff",
          borderRadius: 10,
          padding: 18,
          minWidth: 420,
          maxWidth: 560,
          maxHeight: "80vh",
          overflow: "auto",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <strong>{t("study.gen.title")}</strong>
          <button type="button" onClick={onClose} style={{ border: "none", background: "none", fontSize: 18, cursor: "pointer" }}>×</button>
        </div>

        <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
          <button
            type="button"
            onClick={() => setSourceType("page")}
            data-testid="gen-source-page"
            style={{ padding: "4px 10px", borderRadius: 4, border: "1px solid", borderColor: sourceType === "page" ? "var(--console-accent, #0D9488)" : "#e5e7eb", background: sourceType === "page" ? "var(--console-accent-soft, rgba(13,148,136,0.1))" : "#fff", cursor: "pointer", fontSize: 12 }}
          >
            {t("study.gen.fromPage")}
          </button>
          <button
            type="button"
            onClick={() => setSourceType("chunk")}
            data-testid="gen-source-chunk"
            style={{ padding: "4px 10px", borderRadius: 4, border: "1px solid", borderColor: sourceType === "chunk" ? "var(--console-accent, #0D9488)" : "#e5e7eb", background: sourceType === "chunk" ? "var(--console-accent-soft, rgba(13,148,136,0.1))" : "#fff", cursor: "pointer", fontSize: 12 }}
          >
            {t("study.gen.fromChapter")}
          </button>
        </div>

        {sourceType === "page" ? (
          <select
            value={selectedPage}
            onChange={(e) => setSelectedPage(e.target.value)}
            data-testid="gen-select-page"
            style={{ width: "100%", padding: 6, marginBottom: 10 }}
          >
            <option value="">{t("study.gen.pickPage")}</option>
            {pages.map((p) => (
              <option key={p.id} value={p.id}>{p.title || t("study.gen.untitled")}</option>
            ))}
          </select>
        ) : (
          <>
            <select
              value={selectedAsset}
              onChange={(e) => { setSelectedAsset(e.target.value); setSelectedChunk(""); }}
              data-testid="gen-select-asset"
              style={{ width: "100%", padding: 6, marginBottom: 6 }}
            >
              <option value="">{t("study.gen.pickAsset")}</option>
              {assets.map((a) => (
                <option key={a.id} value={a.id}>{a.title}</option>
              ))}
            </select>
            <select
              value={selectedChunk}
              onChange={(e) => setSelectedChunk(e.target.value)}
              data-testid="gen-select-chunk"
              style={{ width: "100%", padding: 6, marginBottom: 10 }}
              disabled={!selectedAsset}
            >
              <option value="">{t("study.gen.pickChunk")}</option>
              {chunks.map((c) => (
                <option key={c.id} value={c.id}>{c.heading || t("study.gen.chunk")}</option>
              ))}
            </select>
          </>
        )}

        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <span style={{ fontSize: 12 }}>{t("study.gen.count")}</span>
          <input
            type="number"
            min={1}
            max={20}
            value={count}
            onChange={(e) => setCount(Math.max(1, Math.min(20, Number(e.target.value) || 10)))}
            style={{ width: 60, padding: 6 }}
          />
          <button
            type="button"
            onClick={handleGenerate}
            disabled={generating}
            data-testid="gen-submit"
            style={{ padding: "6px 12px", borderRadius: 6, border: "1px solid #e5e7eb", background: "#fff", cursor: "pointer" }}
          >
            {generating ? t("study.gen.generating") : t("study.gen.generate")}
          </button>
        </div>

        {error && <p style={{ color: "#b91c1c", fontSize: 12 }}>{error}</p>}

        {generated && (
          <>
            <ul style={{ listStyle: "none", padding: 0, margin: 0, maxHeight: 260, overflow: "auto" }}>
              {generated.map((c, i) => (
                <li
                  key={i}
                  data-testid="gen-preview-card"
                  style={{ padding: 8, borderBottom: "1px solid #eee", fontSize: 12 }}
                >
                  <div style={{ fontWeight: 600 }}>{c.front}</div>
                  <div style={{ color: "#555" }}>{c.back}</div>
                </li>
              ))}
            </ul>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || generated.length === 0}
              data-testid="gen-save"
              style={{
                marginTop: 10,
                padding: "8px 16px",
                borderRadius: 6,
                border: "1px solid #e5e7eb",
                background: "var(--console-accent, #0D9488)",
                color: "#fff",
                cursor: "pointer",
              }}
            >
              {saving ? t("study.gen.saving") : t("study.gen.saveToDeck", { count: generated.length })}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
