"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Loader2,
  Plus,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { apiGet, apiPost } from "@/lib/api";

interface QuoteToPageDialogProps {
  open: boolean;
  notebookId: string;
  text: string;
  pageNumber: number | null;
  documentTitle?: string;
  onClose: () => void;
  onQuoted?: (pageId: string) => void;
}

interface NotebookPageItem {
  id: string;
  title: string;
  page_type?: string;
}

export default function QuoteToPageDialog({
  open,
  notebookId,
  text,
  pageNumber,
  documentTitle,
  onClose,
  onQuoted,
}: QuoteToPageDialogProps) {
  const t = useTranslations("console-notebooks");
  const [pages, setPages] = useState<NotebookPageItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const loadPages = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiGet<{ items: NotebookPageItem[] }>(
        `/api/v1/notebooks/${notebookId}/pages?limit=100`,
      );
      setPages(data.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("references.loadFailed"));
      setPages([]);
    } finally {
      setLoading(false);
    }
  }, [notebookId, t]);

  useEffect(() => {
    if (!open) return;
    setSuccess(null);
    setSubmitting(null);
    void loadPages();
  }, [loadPages, open]);

  const buildQuoteBlock = useCallback(() => {
    const attribution = documentTitle
      ? pageNumber
        ? `${documentTitle} · p.${pageNumber}`
        : documentTitle
      : "";
    const blockquoteContent = [
      {
        type: "paragraph",
        content: [{ type: "text", text }],
      },
    ];
    if (attribution) {
      blockquoteContent.push({
        type: "paragraph",
        content: [
          {
            type: "text",
            text: `— ${attribution}`,
          },
        ],
      });
    }
    return {
      type: "blockquote",
      content: blockquoteContent,
    };
  }, [documentTitle, pageNumber, text]);

  const handlePick = useCallback(
    async (pageId: string) => {
      if (submitting) return;
      setSubmitting(pageId);
      setError(null);
      try {
        await apiPost(`/api/v1/pages/${pageId}/blocks`, {
          block_type: "quote",
          content_json: buildQuoteBlock(),
        });
        setSuccess(pageId);
        onQuoted?.(pageId);
        // small delay so the user sees the success state before close
        window.setTimeout(() => onClose(), 600);
      } catch (err) {
        setError(err instanceof Error ? err.message : t("references.saveFailed"));
      } finally {
        setSubmitting(null);
      }
    },
    [buildQuoteBlock, onClose, onQuoted, submitting, t],
  );

  const handleCreateAndQuote = useCallback(async () => {
    if (submitting) return;
    setSubmitting("__new");
    setError(null);
    try {
      const newPage = await apiPost<{ id: string; title: string }>(
        `/api/v1/notebooks/${notebookId}/pages`,
        {
          title: documentTitle
            ? `${documentTitle}${pageNumber ? ` · p.${pageNumber}` : ""}`
            : t("pdfSelection.newPageTitle"),
          page_type: "document",
        },
      );
      await apiPost(`/api/v1/pages/${newPage.id}/blocks`, {
        block_type: "quote",
        content_json: buildQuoteBlock(),
      });
      setSuccess(newPage.id);
      onQuoted?.(newPage.id);
      window.setTimeout(() => onClose(), 600);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("references.saveFailed"));
    } finally {
      setSubmitting(null);
    }
  }, [
    buildQuoteBlock,
    documentTitle,
    notebookId,
    onClose,
    onQuoted,
    pageNumber,
    submitting,
    t,
  ]);

  if (!open) return null;

  return (
    <div
      className="quote-to-page-dialog"
      role="dialog"
      aria-modal="true"
      data-testid="quote-to-page-dialog"
    >
      <div
        className="quote-to-page-dialog__scrim"
        onClick={onClose}
      />
      <div className="quote-to-page-dialog__panel">
        <header>
          <strong>{t("pdfSelection.quoteDialogTitle")}</strong>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("pdfSelection.dismiss")}
          >
            <X size={14} />
          </button>
        </header>
        <p className="quote-to-page-dialog__hint">
          {t("pdfSelection.quoteDialogHint")}
        </p>

        {error ? (
          <div className="quote-to-page-dialog__error">
            <AlertCircle size={14} />
            {error}
          </div>
        ) : null}

        <button
          type="button"
          className="quote-to-page-dialog__new"
          onClick={handleCreateAndQuote}
          disabled={!!submitting}
        >
          {submitting === "__new" ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Plus size={14} />
          )}
          {t("pdfSelection.createNewPageAndQuote")}
        </button>

        <div className="quote-to-page-dialog__list">
          {loading ? (
            <div className="quote-to-page-dialog__empty">
              <Loader2 size={20} className="animate-spin" />
            </div>
          ) : pages.length === 0 ? (
            <div className="quote-to-page-dialog__empty">
              <FileText size={20} strokeWidth={1.4} />
              <span>{t("pdfSelection.noPagesYet")}</span>
            </div>
          ) : (
            <ul>
              {pages.map((page) => {
                const pending = submitting === page.id;
                const ok = success === page.id;
                return (
                  <li key={page.id}>
                    <button
                      type="button"
                      onClick={() => void handlePick(page.id)}
                      disabled={!!submitting}
                      data-testid="quote-to-page-item"
                    >
                      <FileText size={14} />
                      <span>{page.title || t("common.untitled")}</span>
                      {pending ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : ok ? (
                        <CheckCircle2 size={14} />
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
