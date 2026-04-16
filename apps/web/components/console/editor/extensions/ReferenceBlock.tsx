"use client";

import { Node, mergeAttributes } from "@tiptap/core";
import type { NodeViewProps } from "@tiptap/react";
import { NodeViewWrapper, ReactNodeViewRenderer } from "@tiptap/react";
import { useCallback, useEffect, useState } from "react";
import { FileText, Brain, BookOpen, Link2 } from "lucide-react";
import { apiGet } from "@/lib/api";
import { useWindowManager } from "@/components/notebook/WindowManager";

type TargetType = "page" | "memory" | "study_chunk";

interface ReferenceAttrs {
  target_type: TargetType | "";
  target_id: string;
  title: string;
  snippet: string;
}

interface PageHit {
  id: string;
  title: string;
  plain_text?: string;
}

interface MemoryHit {
  id: string;
  title?: string;
  content?: string;
}

interface ChunkHit {
  id: string;
  heading?: string;
  content?: string;
}

function iconFor(target: TargetType | "") {
  if (target === "memory") return <Brain size={14} />;
  if (target === "study_chunk") return <BookOpen size={14} />;
  return <FileText size={14} />;
}

function extractNotebookId(): string | null {
  if (typeof window === "undefined") return null;
  const m = window.location.pathname.match(/\/notebooks\/([^/?#]+)/);
  return m ? m[1] : null;
}

function ReferencePickerDialog({
  notebookId,
  onPick,
  onClose,
}: {
  notebookId: string;
  onPick: (attrs: ReferenceAttrs) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<TargetType>("page");
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Array<{ id: string; title: string; snippet: string }>>([]);
  const [projectId, setProjectId] = useState<string | null>(null);

  useEffect(() => {
    void apiGet<{ project_id: string | null }>(`/api/v1/notebooks/${notebookId}`)
      .then((nb) => setProjectId(nb.project_id))
      .catch(() => setProjectId(null));
  }, [notebookId]);

  useEffect(() => {
    const handle = setTimeout(() => {
      if (tab === "page") {
        void apiGet<{ items: PageHit[] }>(
          `/api/v1/pages/search?q=${encodeURIComponent(q)}&notebook_id=${notebookId}`,
        )
          .then((r) =>
            setResults(
              r.items.map((p) => ({
                id: p.id,
                title: p.title || "(untitled)",
                snippet: (p.plain_text || "").slice(0, 240),
              })),
            ),
          )
          .catch(() => setResults([]));
      } else if (tab === "memory" && projectId) {
        void apiGet<{ items: MemoryHit[] }>(
          `/api/v1/memory/search?q=${encodeURIComponent(q)}&project_id=${projectId}&limit=10`,
        )
          .then((r) =>
            setResults(
              r.items.map((m) => ({
                id: m.id,
                title: m.title || m.content?.slice(0, 80) || "(memory)",
                snippet: (m.content || "").slice(0, 240),
              })),
            ),
          )
          .catch(() => setResults([]));
      } else if (tab === "study_chunk") {
        void apiGet<{ items: Array<{ id: string; title: string }> }>(
          `/api/v1/notebooks/${notebookId}/study-assets`,
        )
          .then(async (r) => {
            const first = r.items[0];
            if (!first) {
              setResults([]);
              return;
            }
            const chunks = await apiGet<{ items: ChunkHit[] }>(
              `/api/v1/study-assets/${first.id}/chunks`,
            );
            setResults(
              chunks.items
                .filter((c) => !q || (c.heading || "").toLowerCase().includes(q.toLowerCase()))
                .map((c) => ({
                  id: c.id,
                  title: c.heading || "(chunk)",
                  snippet: (c.content || "").slice(0, 240),
                })),
            );
          })
          .catch(() => setResults([]));
      }
    }, 250);
    return () => clearTimeout(handle);
  }, [tab, q, notebookId, projectId]);

  return (
    <div className="reference-picker" role="dialog" data-testid="reference-picker">
      <div className="reference-picker__tabs">
        {(["page", "memory", "study_chunk"] as const).map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setTab(k)}
            className={tab === k ? "is-active" : ""}
            data-testid={`reference-picker-tab-${k}`}
          >
            {k === "page" ? "Pages" : k === "memory" ? "Memory" : "Chunks"}
          </button>
        ))}
        <button type="button" onClick={onClose} className="reference-picker__close">
          ×
        </button>
      </div>
      <input
        type="text"
        placeholder="Search…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        className="reference-picker__search"
        data-testid="reference-picker-search"
      />
      <ul className="reference-picker__results">
        {results.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              onClick={() =>
                onPick({
                  target_type: tab,
                  target_id: item.id,
                  title: item.title,
                  snippet: item.snippet,
                })
              }
              data-testid="reference-picker-item"
            >
              <div className="reference-picker__item-title">{item.title}</div>
              {item.snippet && (
                <div className="reference-picker__item-snippet">{item.snippet}</div>
              )}
            </button>
          </li>
        ))}
        {results.length === 0 && <li className="reference-picker__empty">No results</li>}
      </ul>
    </div>
  );
}

function ReferenceBlockView(props: NodeViewProps) {
  const attrs = props.node.attrs as ReferenceAttrs;
  const [picking, setPicking] = useState(!attrs.target_id);
  const { openWindow } = useWindowManager();
  const notebookId = extractNotebookId();

  const handlePick = useCallback(
    (next: ReferenceAttrs) => {
      props.updateAttributes(next);
      setPicking(false);
    },
    [props],
  );

  const handleOpen = useCallback(() => {
    if (!notebookId || !attrs.target_type || !attrs.target_id) return;
    if (attrs.target_type === "page") {
      openWindow({
        type: "note",
        title: attrs.title || "Page",
        meta: { notebookId, pageId: attrs.target_id },
      });
    } else if (attrs.target_type === "memory") {
      openWindow({
        type: "memory",
        title: attrs.title || "Memory",
        meta: { notebookId, pageId: attrs.target_id },
      });
    } else if (attrs.target_type === "study_chunk") {
      openWindow({
        type: "study",
        title: attrs.title || "Study",
        meta: { notebookId, chunkId: attrs.target_id },
      });
    }
  }, [attrs, notebookId, openWindow]);

  return (
    <NodeViewWrapper
      className="reference-block"
      data-testid="reference-block"
      contentEditable={false}
    >
      {picking && notebookId ? (
        <ReferencePickerDialog
          notebookId={notebookId}
          onPick={handlePick}
          onClose={() => setPicking(false)}
        />
      ) : (
        <button
          type="button"
          onClick={handleOpen}
          className="reference-block__card"
          data-testid="reference-block-open"
        >
          {iconFor(attrs.target_type)}
          <div className="reference-block__content">
            <div className="reference-block__title">{attrs.title || "(unnamed)"}</div>
            {attrs.snippet && (
              <div className="reference-block__snippet">{attrs.snippet}</div>
            )}
          </div>
          <Link2 size={12} />
        </button>
      )}
    </NodeViewWrapper>
  );
}

const ReferenceBlock = Node.create({
  name: "reference",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      target_type: { default: "" },
      target_id: { default: "" },
      title: { default: "" },
      snippet: { default: "" },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="reference"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-type": "reference" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(ReferenceBlockView);
  },
});

export default ReferenceBlock;
