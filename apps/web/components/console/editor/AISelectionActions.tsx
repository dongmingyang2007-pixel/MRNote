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
  ListChecks,
  Brain,
  Link2,
  Book,
  ExternalLink,
} from "lucide-react";
import { apiStream } from "@/lib/api-stream";
import { isApiRequestError } from "@/lib/api";
import {
  notebookSDK,
  type RelatedPagesItem,
  type GlobalSearchItem,
} from "@/lib/notebook-sdk";
import { searchMemory } from "@/lib/memory-sdk";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ApplyPayload {
  mode: "replace" | "insert_below";
  text: string;
}

export interface TaskInsertPayload {
  mode: "insert_task";
  title: string;
}

export type ActionApplyPayload = ApplyPayload | TaskInsertPayload;

interface AISelectionActionsProps {
  pageId: string;
  selectedText: string;
  /**
   * Callback invoked when the user accepts an action result that should be
   * inserted back into the editor (replace selection, insert below, or insert
   * a task block adjacent to the selection).
   */
  onApply: (payload: ActionApplyPayload) => void;
  onClose: () => void;
}

interface TextAction {
  kind: "text";
  key: string;
  label: string;
  icon: React.ElementType;
}

interface StructuralAction {
  kind: "structural";
  key: "to_task" | "extract_memory" | "find_related_pages" | "find_related_memories";
  label: string;
  icon: React.ElementType;
}

type ActionItem = TextAction | StructuralAction;

type SearchHitView =
  | ({ kind: "page" } & RelatedPagesItem)
  | ({ kind: "search" } & GlobalSearchItem)
  | {
      kind: "memory";
      id: string;
      title: string;
      snippet?: string;
    };

// ---------------------------------------------------------------------------
// Action registry
// ---------------------------------------------------------------------------

const getActions = (t: (key: string) => string): ActionItem[] => [
  // 11 existing text actions
  { kind: "text", key: "rewrite", label: t("ai.actions.rewrite"), icon: RefreshCw },
  { kind: "text", key: "summarize", label: t("ai.actions.summarize"), icon: FileText },
  { kind: "text", key: "expand", label: t("ai.actions.expand"), icon: Expand },
  { kind: "text", key: "translate_en", label: t("ai.actions.translateEn"), icon: Languages },
  { kind: "text", key: "translate_zh", label: t("ai.actions.translateZh"), icon: Languages },
  { kind: "text", key: "explain", label: t("ai.actions.explain"), icon: HelpCircle },
  { kind: "text", key: "fix_grammar", label: t("ai.actions.fixGrammar"), icon: CheckSquare },
  { kind: "text", key: "continue", label: t("ai.actions.continue"), icon: Pen },
  { kind: "text", key: "to_list", label: t("ai.actions.toList"), icon: List },
  { kind: "text", key: "explain_code", label: t("ai.actions.explainCode"), icon: Code },
  { kind: "text", key: "explain_formula", label: t("ai.actions.explainFormula"), icon: Sigma },
  // Spec §19.2 / §7.3: the four MRAI-core selection actions (U-11)
  { kind: "structural", key: "to_task", label: t("selection.to_task"), icon: ListChecks },
  { kind: "structural", key: "extract_memory", label: t("selection.extract_memory"), icon: Brain },
  { kind: "structural", key: "find_related_pages", label: t("selection.find_related_pages"), icon: Link2 },
  { kind: "structural", key: "find_related_memories", label: t("selection.find_related_memories"), icon: Book },
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
  const [structuralView, setStructuralView] = useState<
    | { kind: "memory_confirm"; message: string }
    | { kind: "related"; title: string; items: SearchHitView[] }
    | { kind: "error"; message: string }
    | null
  >(null);

  const runTextAction = useCallback(
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

  const runToTask = useCallback(() => {
    // Insert a new task block immediately below the selection using the
    // editor's existing `TaskBlock` extension. The actual insertion happens
    // in the editor via `onApply` — we just hand the title across.
    const title = selectedText.trim().split(/\r?\n/)[0]?.slice(0, 160) || selectedText.slice(0, 160);
    if (!title) {
      setStructuralView({ kind: "error", message: t("selection.to_task_empty") });
      return;
    }
    onApply({ mode: "insert_task", title });
    onClose();
  }, [selectedText, onApply, onClose, t]);

  const runExtractMemory = useCallback(async () => {
    setLoading(true);
    setStructuralView(null);
    try {
      await notebookSDK.extractPageMemory(pageId, { selected_text: selectedText });
      setStructuralView({
        kind: "memory_confirm",
        message: t("selection.extract_memory_success"),
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : t("selection.extract_memory_failed");
      setStructuralView({ kind: "error", message });
    } finally {
      setLoading(false);
    }
  }, [pageId, selectedText, t]);

  const runFindRelatedPages = useCallback(async () => {
    setLoading(true);
    setStructuralView(null);
    try {
      let items: SearchHitView[] = [];
      try {
        const related = await notebookSDK.getRelatedPages(pageId, {
          text: selectedText,
          limit: 5,
        });
        items = (related.items || []).map((item) => ({
          kind: "page" as const,
          ...item,
        }));
      } catch (error) {
        // Fall back to /search/global if /pages/:id/related doesn't accept
        // text or returns 404 (backend spec-coverage gap).
        if (isApiRequestError(error) && (error.status === 404 || error.status === 400)) {
          try {
            const global = await notebookSDK.searchGlobal(selectedText, {
              scope: "pages",
              limit: 5,
            });
            items = (global.items || []).map((item) => ({
              kind: "search" as const,
              ...item,
            }));
          } catch {
            items = [];
          }
        } else {
          throw error;
        }
      }
      setStructuralView({
        kind: "related",
        title: t("selection.find_related_pages_title"),
        items,
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : t("selection.find_related_failed");
      setStructuralView({ kind: "error", message });
    } finally {
      setLoading(false);
    }
  }, [pageId, selectedText, t]);

  const runFindRelatedMemories = useCallback(async () => {
    setLoading(true);
    setStructuralView(null);
    try {
      // The memory search SDK requires a project_id. We derive it on the
      // caller side: memory search endpoint path `/api/v1/memory/search`
      // with { project_id } in body. If the caller doesn't have access
      // to the project scope, this will 404 — show an empty result then.
      // For selection action we try a best-effort direct query:
      const { apiGet } = await import("@/lib/api");
      const url = new URLSearchParams();
      url.set("q", selectedText);
      let items: SearchHitView[] = [];
      try {
        const resp = await apiGet<{
          items?: Array<{ id: string; title?: string; snippet?: string }>;
        }>(`/api/v1/memory/search?${url.toString()}`);
        items = (resp.items || []).map((item) => ({
          kind: "memory" as const,
          id: item.id,
          title: item.title || item.id,
          snippet: item.snippet,
        }));
      } catch (error) {
        if (isApiRequestError(error) && (error.status === 404 || error.status === 400)) {
          // Endpoint may not accept GET shape; try POST via searchMemory with
          // a lookup through the current page's notebook project.
          try {
            const notebookResp = await apiGet<{ project_id: string | null }>(
              `/api/v1/pages/${pageId}?fields=project_id`,
            );
            if (notebookResp.project_id) {
              const hits = await searchMemory({
                project_id: notebookResp.project_id,
                query: selectedText,
                top_k: 5,
              });
              items = hits.map((hit, index) => ({
                kind: "memory" as const,
                id: hit.supporting_memory_id || `hit-${index}`,
                title: hit.snippet?.slice(0, 80) || `Hit ${index + 1}`,
                snippet: hit.snippet,
              }));
            }
          } catch {
            items = [];
          }
        } else {
          throw error;
        }
      }
      setStructuralView({
        kind: "related",
        title: t("selection.find_related_memories_title"),
        items,
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : t("selection.find_related_failed");
      setStructuralView({ kind: "error", message });
    } finally {
      setLoading(false);
    }
  }, [pageId, selectedText, t]);

  const handleRun = useCallback(
    (action: ActionItem) => {
      if (action.kind === "text") {
        void runTextAction(action.key);
        return;
      }
      switch (action.key) {
        case "to_task":
          runToTask();
          return;
        case "extract_memory":
          void runExtractMemory();
          return;
        case "find_related_pages":
          void runFindRelatedPages();
          return;
        case "find_related_memories":
          void runFindRelatedMemories();
          return;
      }
    },
    [runTextAction, runToTask, runExtractMemory, runFindRelatedPages, runFindRelatedMemories],
  );

  // -- Render: text action result ------------------------------------------
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

  // -- Render: structural result -------------------------------------------
  if (structuralView) {
    return (
      <div className="ai-selection-result" data-testid="ai-selection-structural">
        {structuralView.kind === "memory_confirm" ? (
          <div className="ai-selection-result-content">{structuralView.message}</div>
        ) : structuralView.kind === "error" ? (
          <div className="ai-selection-result-content" style={{ color: "#b91c1c" }}>
            {structuralView.message}
          </div>
        ) : (
          <div className="ai-selection-result-content">
            <div style={{ fontWeight: 600, marginBottom: 8 }}>
              {structuralView.title}
            </div>
            {structuralView.items.length === 0 ? (
              <div style={{ fontSize: 13, color: "var(--console-text-muted, #64748b)" }}>
                {t("selection.find_related_empty")}
              </div>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 6 }}>
                {structuralView.items.map((item) => (
                  <li
                    key={`${item.kind}-${item.id}`}
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 8,
                      padding: "6px 8px",
                      borderRadius: 6,
                      background: "rgba(15,23,42,0.04)",
                      fontSize: 13,
                    }}
                  >
                    <ExternalLink size={14} style={{ marginTop: 2 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {item.title || item.id}
                      </div>
                      {"preview" in item && item.preview ? (
                        <div style={{ fontSize: 12, color: "var(--console-text-muted, #64748b)", marginTop: 2 }}>
                          {item.preview}
                        </div>
                      ) : null}
                      {"snippet" in item && item.snippet ? (
                        <div style={{ fontSize: 12, color: "var(--console-text-muted, #64748b)", marginTop: 2 }}>
                          {item.snippet}
                        </div>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div className="ai-selection-result-actions">
          <button type="button" className="mem-action-btn is-primary" onClick={onClose}>
            {t("ai.actions.cancel")}
          </button>
        </div>
      </div>
    );
  }

  // -- Render: action list -------------------------------------------------
  return (
    <div className="ai-selection-menu">
      {getActions(t).map((action) => {
        const Icon = action.icon;
        return (
          <button
            key={action.key}
            type="button"
            className="ai-selection-item"
            onClick={() => handleRun(action)}
            disabled={loading}
            data-testid={`ai-selection-action-${action.key}`}
          >
            <Icon size={16} />
            <span>{action.label}</span>
          </button>
        );
      })}
    </div>
  );
}
