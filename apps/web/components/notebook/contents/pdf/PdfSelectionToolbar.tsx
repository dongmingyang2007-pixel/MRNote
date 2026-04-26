"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  Brain,
  Copy,
  FileText,
  Highlighter,
  Loader2,
  MessagesSquare,
  Sparkles,
  Wand2,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { apiPost } from "@/lib/api";
import { apiStream } from "@/lib/api-stream";
import { toast } from "@/hooks/use-toast";

type ToolbarAction = "explain" | "copy" | "memory" | "quote";

export interface SelectionContext {
  text: string;
  rect: { top: number; left: number; width: number; height: number };
  pageNumber: number | null;
  /** Bounding boxes of the actual selection range, in text-layer
   * coordinates (CSS pixels relative to the page wrapper). Used by the
   * highlight action to persist colored overlays. */
  rects?: Array<{ x: number; y: number; width: number; height: number }>;
}

export interface PdfSelectionToolbarProps {
  selection: SelectionContext | null;
  notebookId: string;
  studyAssetId: string;
  /** Called when the user clicks "quote to page" — host opens a page picker. */
  onRequestQuoteToPage?: (text: string, pageNumber: number | null) => void;
  /** Called when the user clicks "generate flashcards" — host opens a deck picker. */
  onRequestFlashcards?: (text: string, pageNumber: number | null) => void;
  /** Called when the user clicks "highlight" — host saves an annotation. */
  onRequestHighlight?: (
    text: string,
    pageNumber: number | null,
    rects: Array<{ x: number; y: number; width: number; height: number }>,
  ) => Promise<void> | void;
  onDismiss: () => void;
  /** Optional title/filename to show as context. */
  documentTitle?: string;
}

interface AssistantMessage {
  role: "user" | "assistant";
  content: string;
}

function showToast(title: string, description?: string) {
  try {
    toast({ title, description });
  } catch {
    if (typeof window !== "undefined") {
      console.info(`[toast] ${title}${description ? `: ${description}` : ""}`);
    }
  }
}

export default function PdfSelectionToolbar({
  selection,
  notebookId,
  studyAssetId,
  onRequestQuoteToPage,
  onRequestFlashcards,
  onRequestHighlight,
  onDismiss,
  documentTitle,
}: PdfSelectionToolbarProps) {
  const t = useTranslations("console-notebooks");
  const [activeAction, setActiveAction] = useState<ToolbarAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [explainMessages, setExplainMessages] = useState<AssistantMessage[]>([]);
  const [explainStreaming, setExplainStreaming] = useState(false);
  const [explainPartial, setExplainPartial] = useState("");
  const [explainError, setExplainError] = useState<string | null>(null);

  const selectedText = selection?.text || "";
  const pageNumber = selection?.pageNumber ?? null;

  // Reset explain panel whenever the selection changes.
  useEffect(() => {
    setActiveAction(null);
    setExplainMessages([]);
    setExplainStreaming(false);
    setExplainPartial("");
    setExplainError(null);
  }, [selection?.text]);

  const truncatedSnippet = useMemo(() => {
    if (!selectedText) return "";
    if (selectedText.length <= 140) return selectedText;
    return `${selectedText.slice(0, 140)}…`;
  }, [selectedText]);

  // ---- Action handlers ---------------------------------------------------

  const handleCopy = useCallback(async () => {
    if (!selectedText) return;
    try {
      await navigator.clipboard.writeText(selectedText);
      showToast(t("pdfSelection.copied"));
      onDismiss();
    } catch (err) {
      showToast(
        t("pdfSelection.copyFailed"),
        err instanceof Error ? err.message : undefined,
      );
    }
  }, [onDismiss, selectedText, t]);

  const handleAddToMemory = useCallback(async () => {
    if (!selectedText || busy) return;
    setBusy(true);
    setActiveAction("memory");
    try {
      const sourceLabel = documentTitle
        ? `${documentTitle}${pageNumber ? ` · p.${pageNumber}` : ""}`
        : `Reference selection${pageNumber ? ` · p.${pageNumber}` : ""}`;
      await apiPost<{ run_id: string | null; item_count: number }>(
        `/api/v1/notebooks/${notebookId}/memory/extract-from-text`,
        {
          text: selectedText,
          source_label: sourceLabel,
          source_ref: studyAssetId,
        },
      );
      showToast(
        t("pdfSelection.memoryStarted"),
        t("pdfSelection.memoryStartedHint"),
      );
      onDismiss();
    } catch (err) {
      showToast(
        t("pdfSelection.memoryFailed"),
        err instanceof Error ? err.message : undefined,
      );
    } finally {
      setBusy(false);
      setActiveAction(null);
    }
  }, [
    busy,
    documentTitle,
    notebookId,
    onDismiss,
    pageNumber,
    selectedText,
    studyAssetId,
    t,
  ]);

  const handleQuote = useCallback(() => {
    if (!selectedText) return;
    onRequestQuoteToPage?.(selectedText, pageNumber);
    onDismiss();
  }, [onDismiss, onRequestQuoteToPage, pageNumber, selectedText]);

  const handleFlashcards = useCallback(() => {
    if (!selectedText) return;
    onRequestFlashcards?.(selectedText, pageNumber);
    onDismiss();
  }, [onDismiss, onRequestFlashcards, pageNumber, selectedText]);

  const handleHighlight = useCallback(async () => {
    if (!selectedText || busy) return;
    if (!onRequestHighlight) {
      onDismiss();
      return;
    }
    setBusy(true);
    try {
      await onRequestHighlight(
        selectedText,
        pageNumber,
        selection?.rects || [],
      );
      showToast(t("pdfSelection.highlighted"));
      onDismiss();
    } catch (err) {
      showToast(
        t("pdfSelection.highlightFailed"),
        err instanceof Error ? err.message : undefined,
      );
    } finally {
      setBusy(false);
    }
  }, [busy, onDismiss, onRequestHighlight, pageNumber, selectedText, selection, t]);

  const handleExplain = useCallback(async () => {
    if (!selectedText || explainStreaming) return;
    setActiveAction("explain");
    setExplainStreaming(true);
    setExplainError(null);
    setExplainPartial("");
    setExplainMessages([{ role: "user", content: selectedText }]);

    try {
      const prompt = pageNumber
        ? `请解释下面这段（来自第 ${pageNumber} 页）：\n\n${selectedText}`
        : `请解释下面这段：\n\n${selectedText}`;

      let snapshot = "";
      for await (const event of apiStream(
        "/api/v1/ai/study/ask",
        {
          asset_id: studyAssetId,
          message: prompt,
          history: [],
        },
      )) {
        if (event.event === "token") {
          snapshot =
            typeof event.data.snapshot === "string"
              ? event.data.snapshot
              : snapshot + (event.data.content || "");
          setExplainPartial(snapshot);
        }
        if (event.event === "message_done") {
          const content =
            typeof event.data.content === "string"
              ? event.data.content
              : snapshot;
          setExplainMessages((prev) => [
            ...prev,
            { role: "assistant", content },
          ]);
          setExplainPartial("");
        }
        if (event.event === "error") {
          setExplainError(
            typeof event.data.message === "string"
              ? event.data.message
              : t("study.workspace.assistantError"),
          );
        }
      }
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setExplainError(
          err instanceof Error ? err.message : t("study.workspace.assistantError"),
        );
      }
    } finally {
      setExplainStreaming(false);
    }
  }, [explainStreaming, pageNumber, selectedText, studyAssetId, t]);

  if (!selection || !selectedText) {
    return null;
  }

  const positionStyle = {
    top: Math.max(8, selection.rect.top - 56),
    left: Math.max(
      8,
      selection.rect.left + selection.rect.width / 2,
    ),
  };

  return (
    <div
      className="pdf-selection-toolbar"
      style={positionStyle}
      data-testid="pdf-selection-toolbar"
    >
      <div className="pdf-selection-toolbar__bar">
        <button
          type="button"
          onClick={handleExplain}
          disabled={busy}
          title={t("pdfSelection.explain")}
        >
          {activeAction === "explain" && explainStreaming ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Sparkles size={14} />
          )}
          <span>{t("pdfSelection.explain")}</span>
        </button>
        <button
          type="button"
          onClick={handleQuote}
          disabled={busy}
          title={t("pdfSelection.quoteToPage")}
        >
          <FileText size={14} />
          <span>{t("pdfSelection.quoteToPage")}</span>
        </button>
        <button
          type="button"
          onClick={handleFlashcards}
          disabled={busy}
          title={t("pdfSelection.flashcards")}
        >
          <Wand2 size={14} />
          <span>{t("pdfSelection.flashcards")}</span>
        </button>
        <button
          type="button"
          onClick={() => void handleHighlight()}
          disabled={busy}
          title={t("pdfSelection.highlight")}
        >
          <Highlighter size={14} />
        </button>
        <button
          type="button"
          onClick={handleAddToMemory}
          disabled={busy}
          title={t("pdfSelection.addToMemory")}
        >
          {activeAction === "memory" ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Brain size={14} />
          )}
          <span>{t("pdfSelection.addToMemory")}</span>
        </button>
        <button
          type="button"
          onClick={handleCopy}
          disabled={busy}
          title={t("pdfSelection.copy")}
        >
          <Copy size={14} />
        </button>
        <button
          type="button"
          onClick={onDismiss}
          disabled={busy}
          title={t("pdfSelection.dismiss")}
          aria-label={t("pdfSelection.dismiss")}
          className="pdf-selection-toolbar__close"
        >
          <X size={14} />
        </button>
      </div>

      {activeAction === "explain" ? (
        <ExplainPanel
          snippet={truncatedSnippet}
          messages={explainMessages}
          streaming={explainStreaming}
          partial={explainPartial}
          error={explainError}
          onClose={() => setActiveAction(null)}
        >
          <MessagesSquare size={14} />
          {t("pdfSelection.explainTitle")}
        </ExplainPanel>
      ) : null}
    </div>
  );
}

interface ExplainPanelProps {
  snippet: string;
  messages: AssistantMessage[];
  streaming: boolean;
  partial: string;
  error: string | null;
  onClose: () => void;
  children?: ReactNode;
}

function ExplainPanel({
  snippet,
  messages,
  streaming,
  partial,
  error,
  onClose,
  children,
}: ExplainPanelProps) {
  const t = useTranslations("console-notebooks");
  const assistant = messages.find((m) => m.role === "assistant");
  return (
    <div className="pdf-selection-toolbar__panel">
      <header>
        <strong>{children}</strong>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("pdfSelection.dismiss")}
        >
          <X size={12} />
        </button>
      </header>
      <blockquote>{snippet}</blockquote>
      <div className="pdf-selection-toolbar__panel-body">
        {error ? (
          <div className="pdf-selection-toolbar__error">{error}</div>
        ) : assistant ? (
          <p>{assistant.content}</p>
        ) : streaming ? (
          <p className="pdf-selection-toolbar__streaming">
            {partial || t("study.workspace.streaming")}
          </p>
        ) : (
          <p className="pdf-selection-toolbar__empty">
            {t("pdfSelection.explainEmpty")}
          </p>
        )}
      </div>
    </div>
  );
}
