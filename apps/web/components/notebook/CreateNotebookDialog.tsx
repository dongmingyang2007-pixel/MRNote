"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type {
  CreateNotebookInput,
  NotebookInfo,
  NotebookType,
  NotebookVisibility,
} from "@/lib/notebook-sdk";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface CreateNotebookDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (input: CreateNotebookInput) => Promise<NotebookInfo | void>;
  submitting?: boolean;
}

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

const ICON_PRESETS = ["📓", "📘", "🧠", "🧪", "✍️", "🎯", "📚", "💡"];
const NOTEBOOK_TYPES: NotebookType[] = ["personal", "work", "study", "scratch"];
const MAX_TITLE = 80;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Outer wrapper mounts/unmounts the inner form based on `open`. This gives us
 * a pristine form each time the dialog opens without using a setState-in-effect
 * pattern (see react-hooks/set-state-in-effect lint rule).
 */
export default function CreateNotebookDialog(props: CreateNotebookDialogProps) {
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      {props.open ? <CreateNotebookDialogInner {...props} /> : null}
    </Dialog>
  );
}

function CreateNotebookDialogInner({
  onOpenChange,
  onSubmit,
  submitting,
}: CreateNotebookDialogProps) {
  const t = useTranslations("console-notebooks");

  const [title, setTitle] = useState("");
  const [notebookType, setNotebookType] = useState<NotebookType>("personal");
  const [icon, setIcon] = useState<string>(ICON_PRESETS[0]);
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<NotebookVisibility>("private");
  const [titleTouched, setTitleTouched] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const trimmedTitle = title.trim();
  const titleTooLong = trimmedTitle.length > MAX_TITLE;
  const titleEmpty = trimmedTitle.length === 0;
  const showTitleError = titleTouched && (titleEmpty || titleTooLong);

  const disableSubmit = submitting || titleEmpty || titleTooLong;

  const handleSubmit = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      setTitleTouched(true);
      if (disableSubmit) return;
      setSubmitError(null);
      try {
        await onSubmit({
          title: trimmedTitle,
          notebook_type: notebookType,
          icon,
          description: description.trim() || null,
          visibility,
        });
      } catch (error) {
        const message =
          error instanceof Error ? error.message : t("pages.error.create_failed");
        setSubmitError(message);
      }
    },
    [disableSubmit, onSubmit, trimmedTitle, notebookType, icon, description, visibility, t],
  );

  const titleLabel = t("pages.create_dialog.title");
  const typeHeading = t("pages.create_dialog.notebook_type.heading");
  const iconHeading = t("pages.create_dialog.icon");
  const descLabel = t("pages.create_dialog.description");
  const visibilityHeading = t("pages.create_dialog.visibility.heading");
  const visibilityPrivate = t("pages.create_dialog.visibility.private");
  const visibilityWorkspace = t("pages.create_dialog.visibility.workspace");
  const cancelLabel = t("pages.create_dialog.cancel");
  const submitLabel = t("pages.create_dialog.submit");
  const submittingLabel = t("pages.create_dialog.submitting");
  const iconCustomPlaceholder = t("pages.create_dialog.icon_custom_placeholder");

  const typeLabel = useCallback(
    (kind: NotebookType) => t(`pages.create_dialog.notebook_type.${kind}`),
    [t],
  );

  const typeDescription = useCallback(
    (kind: NotebookType) => t(`pages.create_dialog.notebook_type.${kind}_hint`),
    [t],
  );

  const iconInputValue = useMemo(() => icon, [icon]);

  return (
    <DialogContent
      aria-describedby={undefined}
      className="sm:max-w-[520px]"
    >
      <form onSubmit={handleSubmit} style={{ display: "grid", gap: 18 }}>
          <DialogHeader>
            <DialogTitle>{t("pages.create_dialog.heading")}</DialogTitle>
            <DialogDescription>
              {t("pages.create_dialog.subheading")}
            </DialogDescription>
          </DialogHeader>

          {/* Title */}
          <div style={{ display: "grid", gap: 6 }}>
            <label
              htmlFor="create-notebook-title"
              style={{ fontSize: 13, fontWeight: 600 }}
            >
              {titleLabel}
            </label>
            <input
              id="create-notebook-title"
              type="text"
              maxLength={MAX_TITLE + 20 /* let validation handle excess */}
              value={title}
              onChange={(e) => {
                setTitle(e.target.value);
                if (!titleTouched) setTitleTouched(true);
              }}
              onBlur={() => setTitleTouched(true)}
              placeholder={t("pages.create_dialog.title_placeholder")}
              autoFocus
              data-testid="create-notebook-title-input"
              style={{
                padding: "10px 12px",
                fontSize: 14,
                borderRadius: 8,
                border: `1px solid ${
                  showTitleError ? "#ef4444" : "rgba(15,23,42,0.15)"
                }`,
                background: "rgba(255,255,255,0.85)",
                outline: "none",
              }}
            />
            <div style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: 12,
              color: "var(--console-text-muted, #64748b)",
            }}>
              <span>
                {showTitleError
                  ? titleEmpty
                    ? t("pages.create_dialog.title_required")
                    : t("pages.create_dialog.title_too_long", { max: MAX_TITLE })
                  : t("pages.create_dialog.title_hint")}
              </span>
              <span>
                {trimmedTitle.length}/{MAX_TITLE}
              </span>
            </div>
          </div>

          {/* Notebook type */}
          <fieldset style={{ display: "grid", gap: 8, border: "none", padding: 0, margin: 0 }}>
            <legend style={{ fontSize: 13, fontWeight: 600, padding: 0 }}>
              {typeHeading}
            </legend>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                gap: 8,
              }}
            >
              {NOTEBOOK_TYPES.map((kind) => {
                const selected = notebookType === kind;
                return (
                  <label
                    key={kind}
                    data-testid={`create-notebook-type-${kind}`}
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 10,
                      padding: 10,
                      border: `1px solid ${
                        selected ? "#2563eb" : "rgba(15,23,42,0.12)"
                      }`,
                      borderRadius: 10,
                      background: selected
                        ? "rgba(37,99,235,0.08)"
                        : "rgba(255,255,255,0.85)",
                      cursor: "pointer",
                    }}
                  >
                    <input
                      type="radio"
                      name="notebook-type"
                      value={kind}
                      checked={selected}
                      onChange={() => setNotebookType(kind)}
                      style={{ marginTop: 2 }}
                    />
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>
                        {typeLabel(kind)}
                      </div>
                      <div
                        style={{
                          marginTop: 2,
                          fontSize: 12,
                          color: "var(--console-text-muted, #64748b)",
                          lineHeight: 1.4,
                        }}
                      >
                        {typeDescription(kind)}
                      </div>
                    </div>
                  </label>
                );
              })}
            </div>
          </fieldset>

          {/* Icon */}
          <div style={{ display: "grid", gap: 8 }}>
            <label style={{ fontSize: 13, fontWeight: 600 }}>
              {iconHeading}
            </label>
            <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
              {ICON_PRESETS.map((preset) => {
                const selected = preset === icon;
                return (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => setIcon(preset)}
                    aria-label={preset}
                    data-testid={`create-notebook-icon-${preset}`}
                    style={{
                      width: 36,
                      height: 36,
                      borderRadius: 8,
                      border: `1px solid ${
                        selected ? "#2563eb" : "rgba(15,23,42,0.1)"
                      }`,
                      background: selected ? "rgba(37,99,235,0.1)" : "#fff",
                      cursor: "pointer",
                      fontSize: 18,
                      lineHeight: "1",
                    }}
                  >
                    {preset}
                  </button>
                );
              })}
              <input
                type="text"
                maxLength={4}
                value={iconInputValue}
                onChange={(e) => {
                  const next = e.target.value.trim();
                  if (next.length === 0) {
                    setIcon(ICON_PRESETS[0]);
                  } else {
                    setIcon(next);
                  }
                }}
                placeholder={iconCustomPlaceholder}
                style={{
                  width: 96,
                  padding: "6px 10px",
                  fontSize: 14,
                  border: "1px solid rgba(15,23,42,0.1)",
                  borderRadius: 8,
                  textAlign: "center",
                }}
              />
            </div>
          </div>

          {/* Description */}
          <div style={{ display: "grid", gap: 6 }}>
            <label
              htmlFor="create-notebook-description"
              style={{ fontSize: 13, fontWeight: 600 }}
            >
              {descLabel}
            </label>
            <textarea
              id="create-notebook-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder={t("pages.create_dialog.description_placeholder")}
              style={{
                padding: "10px 12px",
                fontSize: 14,
                borderRadius: 8,
                border: "1px solid rgba(15,23,42,0.15)",
                background: "rgba(255,255,255,0.85)",
                resize: "vertical",
                minHeight: 80,
                outline: "none",
              }}
            />
          </div>

          {/* Visibility */}
          <fieldset style={{ display: "grid", gap: 8, border: "none", padding: 0, margin: 0 }}>
            <legend style={{ fontSize: 13, fontWeight: 600, padding: 0 }}>
              {visibilityHeading}
            </legend>
            <div
              style={{
                display: "flex",
                gap: 16,
                fontSize: 13,
                color: "var(--console-text-primary, #0f172a)",
              }}
            >
              <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <input
                  type="radio"
                  name="notebook-visibility"
                  value="private"
                  checked={visibility === "private"}
                  onChange={() => setVisibility("private")}
                />
                {visibilityPrivate}
              </label>
              <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <input
                  type="radio"
                  name="notebook-visibility"
                  value="workspace"
                  checked={visibility === "workspace"}
                  onChange={() => setVisibility("workspace")}
                />
                {visibilityWorkspace}
              </label>
            </div>
          </fieldset>

          {submitError ? (
            <div
              role="alert"
              style={{
                padding: "8px 12px",
                borderRadius: 8,
                background: "rgba(239,68,68,0.08)",
                color: "#b91c1c",
                fontSize: 13,
              }}
            >
              {submitError}
            </div>
          ) : null}

          <DialogFooter>
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
              style={{
                padding: "8px 14px",
                borderRadius: 8,
                border: "1px solid rgba(15,23,42,0.15)",
                background: "#fff",
                color: "var(--console-text-primary, #0f172a)",
                fontSize: 13,
                fontWeight: 600,
                cursor: submitting ? "wait" : "pointer",
              }}
            >
              {cancelLabel}
            </button>
            <button
              type="submit"
              disabled={disableSubmit}
              data-testid="create-notebook-submit"
              style={{
                padding: "8px 16px",
                borderRadius: 8,
                border: "none",
                background: disableSubmit
                  ? "rgba(37,99,235,0.5)"
                  : "linear-gradient(135deg, #2563eb, #0f4bd7)",
                color: "#fff",
                fontSize: 13,
                fontWeight: 700,
                cursor: disableSubmit ? "not-allowed" : "pointer",
              }}
            >
              {submitting ? submittingLabel : submitLabel}
            </button>
          </DialogFooter>
        </form>
    </DialogContent>
  );
}
