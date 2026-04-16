"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

interface AIActionItem {
  id: string;
  action_type: string;
  scope: string;
  status: string;
  model_id: string | null;
  duration_ms: number | null;
  output_summary: string;
  created_at: string;
  usage: { total_tokens: number };
}

interface Props {
  pageId: string;
}

export default function AIActionsList({ pageId }: Props) {
  const [items, setItems] = useState<AIActionItem[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<{ items: AIActionItem[]; next_cursor: string | null }>(
        `/api/v1/pages/${pageId}/ai-actions?limit=50`,
      );
      setItems(data.items || []);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [pageId]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div data-testid="ai-actions-list" style={{ padding: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
        <h3 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>AI Actions</h3>
        <button onClick={() => void load()} style={{ fontSize: 12 }}>Refresh</button>
      </div>
      {loading && <p style={{ fontSize: 12, color: "#888" }}>Loading…</p>}
      {!loading && items.length === 0 && (
        <p style={{ fontSize: 12, color: "#888" }}>No AI actions yet.</p>
      )}
      {!loading && items.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {items.map((it) => (
            <li
              key={it.id}
              data-testid="ai-action-item"
              style={{ padding: 8, borderBottom: "1px solid #eee", fontSize: 12 }}
            >
              <div style={{ fontWeight: 600 }}>{it.action_type}</div>
              <div style={{ color: "#666" }}>
                {it.status} · {it.model_id ?? "—"} · {it.duration_ms ?? 0}ms · {it.usage.total_tokens} tok
              </div>
              <div style={{ color: "#444", marginTop: 2 }}>
                {it.output_summary || "(no output)"}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
