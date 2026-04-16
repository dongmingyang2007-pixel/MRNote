"use client";

import { Node, mergeAttributes } from "@tiptap/core";
import type { NodeViewProps } from "@tiptap/react";
import { NodeViewWrapper, ReactNodeViewRenderer } from "@tiptap/react";
import { Sparkles, Link2 } from "lucide-react";
import ReactMarkdown from "react-markdown";

interface AIOutputAttrs {
  content_markdown: string;
  action_type: string;
  action_log_id: string;
  model_id: string | null;
  sources: Array<{ type: string; id: string; title: string }>;
}

function AIOutputBlockView(props: NodeViewProps) {
  const attrs = props.node.attrs as AIOutputAttrs;

  const handleViewTrace = () => {
    if (!attrs.action_log_id) return;
    // Dispatch a custom event so the AI Panel (Trace tab) can subscribe.
    window.dispatchEvent(
      new CustomEvent("mrai:open-trace", {
        detail: { action_log_id: attrs.action_log_id },
      }),
    );
  };

  return (
    <NodeViewWrapper className="ai-output-block" data-testid="ai-output-block">
      <div className="ai-output-block__header">
        <Sparkles size={14} />
        <span className="ai-output-block__badge">
          AI
          {attrs.action_type ? ` · ${attrs.action_type}` : ""}
          {attrs.model_id ? ` · ${attrs.model_id}` : ""}
        </span>
        {attrs.action_log_id && (
          <button
            type="button"
            className="ai-output-block__trace-btn"
            onClick={handleViewTrace}
            data-testid="ai-output-view-trace"
          >
            View trace
          </button>
        )}
      </div>
      <div className="ai-output-block__body">
        {attrs.content_markdown ? (
          <ReactMarkdown>{attrs.content_markdown}</ReactMarkdown>
        ) : (
          <p className="ai-output-block__empty">(empty AI block — use AI Panel to fill)</p>
        )}
      </div>
      {Array.isArray(attrs.sources) && attrs.sources.length > 0 && (
        <div className="ai-output-block__sources">
          {attrs.sources.map((s, idx) => (
            <span key={`${s.type}-${s.id}-${idx}`} className="ai-output-block__source">
              <Link2 size={12} /> {s.type} · {s.title}
            </span>
          ))}
        </div>
      )}
    </NodeViewWrapper>
  );
}

const AIOutputBlock = Node.create({
  name: "ai_output",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      content_markdown: { default: "" },
      action_type: { default: "" },
      action_log_id: { default: "" },
      model_id: { default: null as string | null },
      sources: { default: [] as Array<{ type: string; id: string; title: string }> },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="ai_output"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-type": "ai_output" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(AIOutputBlockView);
  },
});

export default AIOutputBlock;
