"use client";

import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import {
  RefreshCw,
  FileText,
  Expand,
  Languages,
  HelpCircle,
  CheckSquare,
  Pen,
  Code,
  Sigma,
  List,
} from "lucide-react";
import { apiStream } from "@/lib/api-stream";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AISelectionActionsProps {
  pageId: string;
  selectedText: string;
  onApply: (payload: { mode: "replace" | "insert_below"; text: string }) => void;
  onClose: () => void;
}

interface ActionItem {
  key: string;
  label: string;
  icon: React.ElementType;
}

const getActions = (t: (key: string) => string): ActionItem[] => [
  { key: "rewrite", label: t("ai.actions.rewrite"), icon: RefreshCw },
  { key: "summarize", label: t("ai.actions.summarize"), icon: FileText },
  { key: "expand", label: t("ai.actions.expand"), icon: Expand },
  { key: "translate_en", label: t("ai.actions.translateEn"), icon: Languages },
  { key: "translate_zh", label: t("ai.actions.translateZh"), icon: Languages },
  { key: "explain", label: t("ai.actions.explain"), icon: HelpCircle },
  { key: "fix_grammar", label: t("ai.actions.fixGrammar"), icon: CheckSquare },
  { key: "continue", label: t("ai.actions.continue"), icon: Pen },
  { key: "to_list", label: t("ai.actions.toList"), icon: List },
  { key: "explain_code", label: t("ai.actions.explainCode"), icon: Code },
  { key: "explain_formula", label: t("ai.actions.explainFormula"), icon: Sigma },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AISelectionActions({
  pageId,
  selectedText,
  onApply,
  onClose,
}: AISelectionActionsProps) {
  const t = useTranslations("console-notebooks");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState("");

  const runAction = useCallback(
    async (actionKey: string) => {
      setLoading(true);
      setResult("");

      let fullContent = "";
      try {
        for await (const { event, data } of apiStream(
          "/api/v1/ai/notebook/selection-action",
          {
            page_id: pageId,
            selected_text: selectedText,
            action_type: actionKey,
          },
        )) {
          if (event === "token" && data.content) {
            fullContent += data.content as string;
            setResult(fullContent);
          } else if (event === "message_done") {
            fullContent = (data.content as string) || fullContent;
            setResult(fullContent);
          } else if (event === "error") {
            fullContent = `Error: ${data.message || "Unknown error"}`;
            setResult(fullContent);
          }
        }
      } catch {
        if (!fullContent) setResult("Connection failed.");
      }

      setLoading(false);
    },
    [pageId, selectedText],
  );

  // Show result view
  if (result) {
    return (
      <div className="ai-selection-result">
        <div className="ai-selection-result-content">{result}</div>
        <div className="ai-selection-result-actions">
          <button
            type="button"
            className="mem-action-btn is-primary"
            onClick={() => {
              onApply({ mode: "replace", text: result });
              onClose();
            }}
          >
            {t("ai.actions.replace")}
          </button>
          <button
            type="button"
            className="mem-action-btn"
            onClick={() => {
              onApply({ mode: "insert_below", text: result });
              onClose();
            }}
          >
            {t("ai.actions.insertBelow")}
          </button>
          <button type="button" className="mem-action-btn" onClick={onClose}>
            {t("ai.actions.cancel")}
          </button>
        </div>
      </div>
    );
  }

  // Show action list
  return (
    <div className="ai-selection-menu">
      {getActions(t).map((action) => {
        const Icon = action.icon;
        return (
          <button
            key={action.key}
            type="button"
            className="ai-selection-item"
            onClick={() => void runAction(action.key)}
            disabled={loading}
          >
            <Icon size={16} />
            <span>{action.label}</span>
          </button>
        );
      })}
    </div>
  );
}
