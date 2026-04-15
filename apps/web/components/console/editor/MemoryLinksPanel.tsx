"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Brain, Check, X, RefreshCw, Loader2 } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MemoryLinksPanelProps {
  pageId: string;
  embedded?: boolean;
}

interface MemoryCandidate {
  id: string;
  fact: string;
  category: string;
  importance: string;
  decision: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MemoryLinksPanel({
  pageId,
  embedded = false,
}: MemoryLinksPanelProps) {
  const t = useTranslations("console-notebooks");
  const [candidates, setCandidates] = useState<MemoryCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);

  const loadCandidates = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<{ items: MemoryCandidate[] }>(
        `/api/v1/pages/${pageId}/memory/links`,
      );
      setCandidates(data.items || []);
    } catch {
      setCandidates([]);
    }
    setLoading(false);
  }, [pageId]);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const data = await apiGet<{ items: MemoryCandidate[] }>(`/api/v1/pages/${pageId}/memory/links`);
        if (!cancelled) {
          setCandidates(data.items || []);
        }
      } catch {
        if (!cancelled) {
          setCandidates([]);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [pageId]);

  const handleExtract = useCallback(async () => {
    setExtracting(true);
    try {
      await apiPost(`/api/v1/pages/${pageId}/memory/extract`, {});
      await loadCandidates();
    } catch {
      // ignore
    }
    setExtracting(false);
  }, [pageId, loadCandidates]);

  const handleConfirm = useCallback(
    async (itemId: string) => {
      try {
        await apiPost(`/api/v1/pages/${pageId}/memory/confirm`, { item_id: itemId });
        setCandidates((prev) =>
          prev.map((c) => (c.id === itemId ? { ...c, decision: "confirmed" } : c)),
        );
      } catch {
        // ignore
      }
    },
    [pageId],
  );

  const handleReject = useCallback(
    async (itemId: string) => {
      try {
        await apiPost(`/api/v1/pages/${pageId}/memory/reject`, { item_id: itemId });
        setCandidates((prev) =>
          prev.map((c) => (c.id === itemId ? { ...c, decision: "rejected" } : c)),
        );
      } catch {
        // ignore
      }
    },
    [pageId],
  );

  return (
    <div className={`memory-links-panel${embedded ? " memory-links-panel--embedded" : ""}`}>
      <div className="memory-links-header">
        <div className="memory-links-title">
          <Brain size={16} />
          <span>{t("memory.title")}</span>
        </div>
        <button
          type="button"
          className="memory-links-extract-btn"
          onClick={handleExtract}
          disabled={extracting}
          title="Extract memories from page"
        >
          {extracting ? <Loader2 size={14} className="ai-panel-spinner" /> : <RefreshCw size={14} />}
        </button>
      </div>

      <div className="memory-links-list">
        {loading && <div className="memory-links-empty"><Loader2 size={16} className="ai-panel-spinner" /></div>}

        {!loading && candidates.length === 0 && (
          <div className="memory-links-empty">
            <p>{t("memory.empty")}</p>
            <button type="button" className="mem-action-btn" onClick={handleExtract}>
              {t("memory.extractNow")}
            </button>
          </div>
        )}

        {candidates.map((c) => (
          <div key={c.id} className={`memory-links-item memory-links-item-${c.decision}`}>
            <div className="memory-links-item-content">
              <span className="memory-links-item-fact">{c.fact}</span>
              <span className="memory-links-item-meta">
                {c.category} · {c.importance}
              </span>
            </div>
            {!["confirmed", "rejected", "discard"].includes(c.decision) && (
              <div className="memory-links-item-actions">
                <button
                  type="button"
                  className="memory-links-action-btn is-confirm"
                  onClick={() => void handleConfirm(c.id)}
                  title="Confirm"
                >
                  <Check size={14} />
                </button>
                <button
                  type="button"
                  className="memory-links-action-btn is-reject"
                  onClick={() => void handleReject(c.id)}
                  title="Reject"
                >
                  <X size={14} />
                </button>
              </div>
            )}
            {c.decision === "confirmed" && (
              <Check size={14} className="memory-links-confirmed-icon" />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
