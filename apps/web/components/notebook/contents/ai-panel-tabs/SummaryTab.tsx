"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Sparkles, Loader2 } from "lucide-react";
import { apiStream } from "@/lib/api-stream";

interface SummaryTabProps {
  pageId: string;
}

export default function SummaryTab({ pageId }: SummaryTabProps) {
  const [summary, setSummary] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Abort any in-flight stream when the tab/window unmounts.
  useEffect(() => () => abortRef.current?.abort(), []);

  const handleGenerate = useCallback(async () => {
    if (streaming) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStreaming(true);
    setError(null);
    setSummary("");
    try {
      let acc = "";
      for await (const event of apiStream(
        "/api/v1/ai/notebook/page-action",
        { page_id: pageId, action_type: "summarize" },
        controller.signal,
      )) {
        if (event.event === "token") {
          const tok = (event.data as { content?: string }).content || "";
          acc += tok;
          setSummary(acc);
        } else if (event.event === "error") {
          setError(
            (event.data as { message?: string }).message || "Summary failed",
          );
        }
      }
    } catch (err) {
      // Aborted streams are not errors from the user's perspective.
      if (err instanceof Error && err.name === "AbortError") return;
      setError(err instanceof Error ? err.message : "Summary failed");
    } finally {
      if (abortRef.current === controller) {
        setStreaming(false);
      }
    }
  }, [pageId, streaming]);

  return (
    <div data-testid="ai-panel-summary" style={{ padding: 12 }}>
      <button
        type="button"
        onClick={handleGenerate}
        disabled={streaming}
        data-testid="ai-panel-summary-generate"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          padding: "6px 12px",
          borderRadius: 8,
          border: "1px solid #e5e7eb",
          background: streaming ? "#f3f4f6" : "#ffffff",
          cursor: streaming ? "wait" : "pointer",
          fontSize: 12,
          fontWeight: 600,
        }}
      >
        {streaming ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
        {streaming ? "Generating…" : "Generate summary"}
      </button>
      {error && (
        <p style={{ marginTop: 12, fontSize: 12, color: "#b91c1c" }}>{error}</p>
      )}
      {summary && (
        <div
          data-testid="ai-panel-summary-output"
          style={{
            marginTop: 12,
            padding: 12,
            borderRadius: 8,
            background: "#f9fafb",
            border: "1px solid #e5e7eb",
            fontSize: 13,
            lineHeight: 1.55,
            whiteSpace: "pre-wrap",
          }}
        >
          {summary}
        </div>
      )}
    </div>
  );
}
