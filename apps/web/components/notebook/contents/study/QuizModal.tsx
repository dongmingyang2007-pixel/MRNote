"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";

interface Props {
  notebookId: string;
  onClose: () => void;
}

type SourceType = "page" | "chunk";

interface Page { id: string; title: string; }
interface Asset { id: string; title: string; }
interface Chunk { id: string; heading: string; }

interface QuizQuestion {
  question: string;
  options: string[];
  correct_index: number;
  explanation: string;
}

export default function QuizModal({ notebookId, onClose }: Props) {
  const [sourceType, setSourceType] = useState<SourceType>("page");
  const [pages, setPages] = useState<Page[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [selectedPage, setSelectedPage] = useState("");
  const [selectedAsset, setSelectedAsset] = useState("");
  const [selectedChunk, setSelectedChunk] = useState("");
  const [questions, setQuestions] = useState<QuizQuestion[] | null>(null);
  const [index, setIndex] = useState(0);
  const [answered, setAnswered] = useState<number[]>([]); // picked option per question
  const [submitted, setSubmitted] = useState(false);
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
    if (!selectedAsset) { setChunks([]); return; }
    void apiGet<{ items: Chunk[] }>(`/api/v1/study-assets/${selectedAsset}/chunks`)
      .then((r) => setChunks(r.items || []))
      .catch(() => setChunks([]));
  }, [selectedAsset]);

  const handleGenerate = useCallback(async () => {
    const sourceId = sourceType === "page" ? selectedPage : selectedChunk;
    if (!sourceId) { setError("Pick a source"); return; }
    setGenerating(true); setError(null);
    try {
      const r = await apiPost<{ questions: QuizQuestion[] }>(
        "/api/v1/ai/study/quiz",
        { source_type: sourceType, source_id: sourceId, count: 5 },
      );
      setQuestions(r.questions || []);
      setIndex(0); setAnswered([]); setSubmitted(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
    } finally {
      setGenerating(false);
    }
  }, [sourceType, selectedPage, selectedChunk]);

  const handlePick = useCallback((optIdx: number) => {
    setAnswered((prev) => {
      const next = [...prev];
      next[index] = optIdx;
      return next;
    });
  }, [index]);

  const handleNext = useCallback(() => {
    if (questions && index < questions.length - 1) {
      setIndex((i) => i + 1);
    } else {
      setSubmitted(true);
    }
  }, [questions, index]);

  if (submitted && questions) {
    const correct = answered.reduce(
      (n, pick, i) => n + (pick === questions[i].correct_index ? 1 : 0),
      0,
    );
    return (
      <div role="dialog" data-testid="quiz-modal" style={modalOverlay} onClick={onClose}>
        <div onClick={(e) => e.stopPropagation()} style={modalBody}>
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>
            Score: {correct} / {questions.length}
          </div>
          <ul style={{ listStyle: "none", padding: 0, margin: 0, maxHeight: 300, overflow: "auto" }}>
            {questions.map((q, i) => {
              const pick = answered[i];
              const correctPick = pick === q.correct_index;
              return (
                <li
                  key={i}
                  data-testid="quiz-result-row"
                  style={{
                    padding: 8,
                    borderBottom: "1px solid #eee",
                    fontSize: 12,
                    background: correctPick ? "rgba(16,185,129,0.06)" : "rgba(239,68,68,0.06)",
                  }}
                >
                  <div style={{ fontWeight: 600 }}>{q.question}</div>
                  <div style={{ color: "#555" }}>
                    Your answer: {q.options[pick] ?? "(none)"} {correctPick ? "✓" : `✗ (correct: ${q.options[q.correct_index]})`}
                  </div>
                  <div style={{ color: "#6b7280", marginTop: 2 }}>{q.explanation}</div>
                </li>
              );
            })}
          </ul>
          <button
            type="button"
            onClick={onClose}
            style={{ marginTop: 10, padding: "6px 16px", border: "1px solid #e5e7eb", borderRadius: 6, background: "#fff", cursor: "pointer" }}
          >
            Close
          </button>
        </div>
      </div>
    );
  }

  if (!questions) {
    return (
      <div role="dialog" data-testid="quiz-modal" style={modalOverlay} onClick={onClose}>
        <div onClick={(e) => e.stopPropagation()} style={modalBody}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
            <strong>Quiz</strong>
            <button type="button" onClick={onClose} style={{ border: "none", background: "none", fontSize: 18, cursor: "pointer" }}>×</button>
          </div>
          <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
            <button
              type="button"
              onClick={() => setSourceType("page")}
              data-testid="quiz-source-page"
              style={sourceBtn(sourceType === "page")}
            >
              From page
            </button>
            <button
              type="button"
              onClick={() => setSourceType("chunk")}
              data-testid="quiz-source-chunk"
              style={sourceBtn(sourceType === "chunk")}
            >
              From chapter
            </button>
          </div>
          {sourceType === "page" ? (
            <select
              value={selectedPage}
              onChange={(e) => setSelectedPage(e.target.value)}
              data-testid="quiz-select-page"
              style={{ width: "100%", padding: 6, marginBottom: 10 }}
            >
              <option value="">Pick a page</option>
              {pages.map((p) => (
                <option key={p.id} value={p.id}>{p.title || "(untitled)"}</option>
              ))}
            </select>
          ) : (
            <>
              <select
                value={selectedAsset}
                onChange={(e) => { setSelectedAsset(e.target.value); setSelectedChunk(""); }}
                data-testid="quiz-select-asset"
                style={{ width: "100%", padding: 6, marginBottom: 6 }}
              >
                <option value="">Pick a study asset</option>
                {assets.map((a) => (
                  <option key={a.id} value={a.id}>{a.title}</option>
                ))}
              </select>
              <select
                value={selectedChunk}
                onChange={(e) => setSelectedChunk(e.target.value)}
                data-testid="quiz-select-chunk"
                style={{ width: "100%", padding: 6, marginBottom: 10 }}
                disabled={!selectedAsset}
              >
                <option value="">Pick a chapter / chunk</option>
                {chunks.map((c) => (
                  <option key={c.id} value={c.id}>{c.heading || "(chunk)"}</option>
                ))}
              </select>
            </>
          )}
          {error && <p style={{ color: "#b91c1c", fontSize: 12 }}>{error}</p>}
          <button
            type="button"
            onClick={handleGenerate}
            disabled={generating}
            data-testid="quiz-start"
            style={{ padding: "8px 14px", border: "1px solid #e5e7eb", borderRadius: 6, background: "#2563eb", color: "#fff", cursor: "pointer" }}
          >
            {generating ? "Generating…" : "Start"}
          </button>
        </div>
      </div>
    );
  }

  const q = questions[index];
  const pick = answered[index];
  return (
    <div role="dialog" data-testid="quiz-modal" style={modalOverlay} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} style={modalBody}>
        <div style={{ fontSize: 11, color: "#9ca3af", marginBottom: 4 }}>
          Question {index + 1} / {questions.length}
        </div>
        <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 10 }}>{q.question}</div>
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {q.options.map((opt, i) => (
            <li key={i} style={{ marginBottom: 4 }}>
              <button
                type="button"
                data-testid={`quiz-opt-${i}`}
                onClick={() => handlePick(i)}
                disabled={pick !== undefined}
                style={{
                  width: "100%",
                  textAlign: "left",
                  padding: "8px 10px",
                  border: "1px solid",
                  borderColor: pick === undefined
                    ? "#e5e7eb"
                    : i === q.correct_index
                      ? "#10b981"
                      : i === pick
                        ? "#ef4444"
                        : "#e5e7eb",
                  borderRadius: 6,
                  background: pick === undefined
                    ? "#fff"
                    : i === q.correct_index
                      ? "rgba(16,185,129,0.08)"
                      : i === pick
                        ? "rgba(239,68,68,0.08)"
                        : "#fff",
                  cursor: pick === undefined ? "pointer" : "default",
                }}
              >
                {opt}
              </button>
            </li>
          ))}
        </ul>
        {pick !== undefined && (
          <>
            <p style={{ color: "#555", fontSize: 12, marginTop: 8 }}>{q.explanation}</p>
            <button
              type="button"
              onClick={handleNext}
              data-testid="quiz-next"
              style={{ marginTop: 8, padding: "6px 14px", border: "1px solid #e5e7eb", borderRadius: 6, background: "#fff", cursor: "pointer" }}
            >
              {index === questions.length - 1 ? "See results" : "Next →"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

const modalOverlay: React.CSSProperties = {
  position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
  background: "rgba(17,24,39,0.35)",
  display: "flex", alignItems: "center", justifyContent: "center",
  zIndex: 1000,
};
const modalBody: React.CSSProperties = {
  background: "#fff",
  borderRadius: 10,
  padding: 18,
  minWidth: 420,
  maxWidth: 560,
  maxHeight: "80vh",
  overflow: "auto",
};
function sourceBtn(active: boolean): React.CSSProperties {
  return {
    padding: "4px 10px",
    borderRadius: 4,
    border: `1px solid ${active ? "#2563eb" : "#e5e7eb"}`,
    background: active ? "rgba(37,99,235,0.06)" : "#fff",
    cursor: "pointer",
    fontSize: 12,
  };
}
