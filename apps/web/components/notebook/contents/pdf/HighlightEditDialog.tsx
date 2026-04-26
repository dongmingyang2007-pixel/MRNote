"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Link2,
  Loader2,
  Trash2,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { apiDelete, apiGet, apiPatch } from "@/lib/api";

export type HighlightLink =
  | { kind: "page"; id: string; label?: string }
  | { kind: "memory"; id: string; label?: string };

export interface HighlightDraft {
  id: string;
  page: number;
  text: string;
  color: string;
  rects: Array<{ x: number; y: number; width: number; height: number }>;
  note?: string;
  links?: HighlightLink[];
}

interface HighlightEditDialogProps {
  open: boolean;
  notebookId: string;
  highlight: HighlightDraft | null;
  onClose: () => void;
  /** Called after a successful PATCH; parent should merge into local state. */
  onSaved?: (next: HighlightDraft) => void;
  /** Called after a successful DELETE; parent should drop from local state. */
  onDeleted?: (id: string) => void;
}

interface NotebookPageItem {
  id: string;
  title: string;
}

const HIGHLIGHT_COLORS: Array<{ id: string; value: string; label: string }> = [
  { id: "yellow", value: "rgba(252, 211, 77, 0.45)", label: "yellow" },
  { id: "green", value: "rgba(134, 239, 172, 0.5)", label: "green" },
  { id: "blue", value: "rgba(147, 197, 253, 0.5)", label: "blue" },
  { id: "pink", value: "rgba(249, 168, 212, 0.55)", label: "pink" },
  { id: "purple", value: "rgba(196, 181, 253, 0.55)", label: "purple" },
];

export default function HighlightEditDialog({
  open,
  notebookId,
  highlight,
  onClose,
  onSaved,
  onDeleted,
}: HighlightEditDialogProps) {
  const t = useTranslations("console-notebooks");
  const [note, setNote] = useState("");
  const [color, setColor] = useState(HIGHLIGHT_COLORS[0].value);
  const [links, setLinks] = useState<HighlightLink[]>([]);
  const [pages, setPages] = useState<NotebookPageItem[]>([]);
  const [loadingPages, setLoadingPages] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Hydrate when opening / switching highlight.
  useEffect(() => {
    if (!open || !highlight) return;
    setNote(highlight.note || "");
    setColor(highlight.color || HIGHLIGHT_COLORS[0].value);
    setLinks(highlight.links || []);
    setError(null);
  }, [highlight, open]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoadingPages(true);
    void (async () => {
      try {
        const data = await apiGet<{ items: NotebookPageItem[] }>(
          `/api/v1/notebooks/${notebookId}/pages?limit=200`,
        );
        if (!cancelled) setPages(data.items || []);
      } catch {
        if (!cancelled) setPages([]);
      } finally {
        if (!cancelled) setLoadingPages(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [notebookId, open]);

  const togglePageLink = useCallback((page: NotebookPageItem) => {
    setLinks((prev) => {
      const existing = prev.findIndex(
        (l) => l.kind === "page" && l.id === page.id,
      );
      if (existing >= 0) {
        return prev.filter((_, i) => i !== existing);
      }
      return [...prev, { kind: "page", id: page.id, label: page.title }];
    });
  }, []);

  const handleSave = useCallback(async () => {
    if (!highlight || saving) return;
    setSaving(true);
    setError(null);
    try {
      const nextPayload = {
        page: highlight.page,
        text: highlight.text,
        rects: highlight.rects,
        color,
        note: note.trim() || undefined,
        links,
      };
      await apiPatch(`/api/v1/annotations/${highlight.id}`, {
        payload_json: nextPayload,
      });
      onSaved?.({
        ...highlight,
        color,
        note: note.trim() || undefined,
        links,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("references.saveFailed"));
    } finally {
      setSaving(false);
    }
  }, [color, highlight, links, note, onClose, onSaved, saving, t]);

  const handleDelete = useCallback(async () => {
    if (!highlight || deleting) return;
    if (!window.confirm(t("highlightEdit.deleteConfirm"))) return;
    setDeleting(true);
    setError(null);
    try {
      await apiDelete(`/api/v1/annotations/${highlight.id}`);
      onDeleted?.(highlight.id);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("highlightEdit.deleteFailed"));
    } finally {
      setDeleting(false);
    }
  }, [deleting, highlight, onClose, onDeleted, t]);

  if (!open || !highlight) return null;

  const linkedPageIds = new Set(
    links.filter((l) => l.kind === "page").map((l) => l.id),
  );

  return (
    <div
      className="quote-to-page-dialog highlight-edit-dialog"
      role="dialog"
      aria-modal="true"
      data-testid="highlight-edit-dialog"
    >
      <div className="quote-to-page-dialog__scrim" onClick={onClose} />
      <div className="quote-to-page-dialog__panel">
        <header>
          <strong>{t("highlightEdit.title")}</strong>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("pdfSelection.dismiss")}
          >
            <X size={14} />
          </button>
        </header>

        <blockquote className="highlight-edit-dialog__snippet">
          {highlight.text || t("highlightEdit.emptyText")}
          <small>p.{highlight.page}</small>
        </blockquote>

        {error ? (
          <div className="quote-to-page-dialog__error">
            <AlertCircle size={14} />
            {error}
          </div>
        ) : null}

        <div className="highlight-edit-dialog__section">
          <label htmlFor="highlight-note">{t("highlightEdit.noteLabel")}</label>
          <textarea
            id="highlight-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t("highlightEdit.notePlaceholder")}
            rows={3}
          />
        </div>

        <div className="highlight-edit-dialog__section">
          <strong>{t("highlightEdit.colorLabel")}</strong>
          <div className="highlight-edit-dialog__color-row">
            {HIGHLIGHT_COLORS.map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => setColor(opt.value)}
                title={opt.label}
                aria-label={opt.label}
                className={
                  color === opt.value
                    ? "highlight-edit-dialog__swatch is-active"
                    : "highlight-edit-dialog__swatch"
                }
                style={{ background: opt.value }}
              >
                {color === opt.value ? <CheckCircle2 size={11} /> : null}
              </button>
            ))}
          </div>
        </div>

        <div className="highlight-edit-dialog__section">
          <strong>
            <Link2 size={12} /> {t("highlightEdit.linksLabel")}
          </strong>
          <div className="highlight-edit-dialog__pages">
            {loadingPages ? (
              <div className="quote-to-page-dialog__empty">
                <Loader2 size={16} className="animate-spin" />
              </div>
            ) : pages.length === 0 ? (
              <div className="quote-to-page-dialog__empty">
                <span>{t("pdfSelection.noPagesYet")}</span>
              </div>
            ) : (
              <ul>
                {pages.map((p) => {
                  const linked = linkedPageIds.has(p.id);
                  return (
                    <li key={p.id}>
                      <button
                        type="button"
                        onClick={() => togglePageLink(p)}
                        className={
                          linked ? "is-linked" : undefined
                        }
                        data-testid="highlight-edit-page"
                      >
                        <FileText size={12} />
                        <span>{p.title || t("common.untitled")}</span>
                        {linked ? <CheckCircle2 size={12} /> : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>

        <div className="highlight-edit-dialog__footer">
          <button
            type="button"
            onClick={() => void handleDelete()}
            disabled={saving || deleting}
            className="highlight-edit-dialog__delete"
          >
            {deleting ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <Trash2 size={12} />
            )}
            {t("highlightEdit.delete")}
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving || deleting}
            className="highlight-edit-dialog__save"
            data-testid="highlight-edit-save"
          >
            {saving ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <CheckCircle2 size={12} />
            )}
            {t("highlightEdit.save")}
          </button>
        </div>
      </div>
    </div>
  );
}
