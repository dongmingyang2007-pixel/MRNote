"use client";

import { Node, mergeAttributes } from "@tiptap/core";
import type { NodeViewProps } from "@tiptap/react";
import { NodeViewWrapper, ReactNodeViewRenderer } from "@tiptap/react";
import { Sparkles, Link2 } from "lucide-react";
import { useCallback, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import { useTranslations } from "next-intl";
import { useWindowManager } from "@/components/notebook/WindowManager";

interface AIOutputAttrs {
  content_markdown: string;
  action_type: string;
  action_log_id: string;
  model_id: string | null;
  sources: Array<{ type: string; id: string; title: string }>;
}

function extractNotebookId(): string | null {
  if (typeof window === "undefined") return null;
  const m = window.location.pathname.match(/\/notebooks\/([^/?#]+)/);
  return m ? m[1] : null;
}

function AIOutputBlockView(props: NodeViewProps) {
  const attrs = props.node.attrs as AIOutputAttrs;
  const t = useTranslations("console-notebooks");
  const { openWindow } = useWindowManager();
  const actionTypeLabels = useMemo<Record<string, string>>(
    () => ({
      ask: t("aiActions.actionType.ask"),
      brainstorm: t("aiActions.actionType.brainstorm"),
      expand: t("ai.actions.expand"),
      explain: t("ai.actions.explain"),
      explain_code: t("ai.actions.explainCode"),
      explain_formula: t("ai.actions.explainFormula"),
      fix_grammar: t("ai.actions.fixGrammar"),
      rewrite: t("ai.actions.rewrite"),
      study_qa: t("aiActions.actionType.studyQa"),
      summarize: t("ai.actions.summarize"),
      to_list: t("ai.actions.toList"),
      translate_en: t("ai.actions.translateEn"),
      translate_zh: t("ai.actions.translateZh"),
      "study.ask": t("study.progress.actionType.study.ask"),
      "study.flashcards": t("study.progress.actionType.study.flashcards"),
      "study.quiz": t("study.progress.actionType.study.quiz"),
      "study.review_card": t("study.progress.actionType.study.review_card"),
    }),
    [t],
  );
  const sourceTypeLabels = useMemo<Record<string, string>>(
    () => ({
      document_chunk: t("aiOutput.source.document"),
      memory: t("aiOutput.source.memory"),
      page: t("aiOutput.source.page"),
      related_page: t("aiOutput.source.page"),
      study_chunk: t("aiOutput.source.study"),
    }),
    [t],
  );

  const formatActionType = useCallback(
    (actionType: string) => {
      const normalized = actionType.trim();
      return (
        actionTypeLabels[normalized] ||
        normalized.replace(/[._-]+/g, " ") ||
        t("aiActions.actionType.unknown")
      );
    },
    [actionTypeLabels, t],
  );

  const formatSourceType = useCallback(
    (sourceType: string) => {
      const normalized = sourceType.trim();
      return (
        sourceTypeLabels[normalized] ||
        normalized.replace(/[._-]+/g, " ") ||
        t("aiOutput.source.unknown")
      );
    },
    [sourceTypeLabels, t],
  );

  const handleViewTrace = useCallback(() => {
    if (!attrs.action_log_id) return;
    // Dispatch a custom event so the AI Panel (Trace tab) can subscribe.
    window.dispatchEvent(
      new CustomEvent("mrai:open-trace", {
        detail: { action_log_id: attrs.action_log_id },
      }),
    );
  }, [attrs.action_log_id]);

  const handleSourceClick = useCallback(
    (source: { type: string; id: string; title: string }) => {
      const notebookId = extractNotebookId();
      if (!notebookId) return;
      if (source.type === "memory") {
        openWindow({
          type: "memory",
          title: source.title || "Memory",
          meta: { notebookId, pageId: source.id },
        });
      } else if (source.type === "page" || source.type === "related_page") {
        openWindow({
          type: "note",
          title: source.title || "Page",
          meta: { notebookId, pageId: source.id },
        });
      } else if (
        source.type === "document_chunk" ||
        source.type === "study_chunk"
      ) {
        openWindow({
          type: "study",
          title: source.title || "Study",
          meta: { notebookId, chunkId: source.id },
        });
      }
    },
    [openWindow],
  );

  return (
    <NodeViewWrapper className="ai-output-block" data-testid="ai-output-block">
      <div className="ai-output-block__header">
        <Sparkles size={14} />
        <span className="ai-output-block__badge">
          {t("aiOutput.badge")}
          {attrs.action_type ? ` · ${formatActionType(attrs.action_type)}` : ""}
          {attrs.model_id ? ` · ${attrs.model_id}` : ""}
        </span>
        {attrs.action_log_id && (
          <button
            type="button"
            className="ai-output-block__trace-btn"
            onClick={handleViewTrace}
            data-testid="ai-output-view-trace"
          >
            {t("aiOutput.viewTrace")}
          </button>
        )}
      </div>
      <div className="ai-output-block__body">
        {attrs.content_markdown ? (
          <ReactMarkdown>{attrs.content_markdown}</ReactMarkdown>
        ) : (
          <p className="ai-output-block__empty">{t("aiOutput.empty")}</p>
        )}
      </div>
      {Array.isArray(attrs.sources) && attrs.sources.length > 0 && (
        <div className="ai-output-block__sources">
          {attrs.sources.map((s, idx) => (
            <button
              key={`${s.type}-${s.id}-${idx}`}
              type="button"
              className="ai-output-block__source"
              onClick={() => handleSourceClick(s)}
              data-testid="ai-output-source"
            >
              <Link2 size={12} /> {formatSourceType(s.type)} · {s.title}
            </button>
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
      sources: {
        default: [] as Array<{ type: string; id: string; title: string }>,
      },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="ai_output"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes(HTMLAttributes, { "data-type": "ai_output" }),
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(AIOutputBlockView);
  },
});

export default AIOutputBlock;
