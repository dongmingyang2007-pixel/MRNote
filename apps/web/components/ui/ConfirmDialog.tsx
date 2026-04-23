"use client";

import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";

/**
 * ConfirmDialog — controlled alert modal (U-16 / Spec §17)
 *
 * A focused, one-shot confirmation dialog for destructive or significant
 * actions. Use this when `useModal().confirm(...)` feels too ad-hoc or you
 * want a component that lives in JSX next to the related button.
 *
 * Callers own open/close state. The dialog does the keyboard handling and
 * outside-click dismiss; it does not call `onCancel` when the user presses
 * the primary action — only the primary callback fires.
 */

export type ConfirmVariant = "default" | "destructive";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  body?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmVariant?: ConfirmVariant;
  /** If true the confirm button will be focused on open so Enter confirms. */
  autoFocusConfirm?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  cancelLabel,
  confirmVariant = "default",
  autoFocusConfirm = true,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const t = useTranslations("common");
  const confirmBtnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    if (autoFocusConfirm) {
      // Defer so the dialog is in the DOM before we focus.
      const id = window.setTimeout(() => {
        confirmBtnRef.current?.focus();
      }, 0);
      return () => clearTimeout(id);
    }
  }, [open, autoFocusConfirm]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onCancel]);

  if (!open) return null;

  const destructive = confirmVariant === "destructive";

  return (
    <div
      className="app-modal-overlay"
      role="presentation"
      onClick={onCancel}
      data-testid="confirm-dialog-overlay"
    >
      <div
        className="app-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby={body ? "confirm-dialog-body" : undefined}
        data-testid="confirm-dialog"
      >
        <p
          id="confirm-dialog-title"
          className="app-modal-message"
          style={{ fontWeight: 700 }}
        >
          {title}
        </p>
        {body ? (
          <p
            id="confirm-dialog-body"
            className="app-modal-message"
            style={{ marginTop: 6, fontSize: "0.8125rem", opacity: 0.85 }}
          >
            {body}
          </p>
        ) : null}

        <div className="app-modal-actions">
          <button
            type="button"
            className="app-modal-btn app-modal-btn-cancel"
            onClick={onCancel}
            data-testid="confirm-dialog-cancel"
          >
            {cancelLabel ?? t("button.cancel")}
          </button>
          <button
            ref={confirmBtnRef}
            type="button"
            className="app-modal-btn app-modal-btn-confirm"
            data-testid="confirm-dialog-confirm"
            onClick={onConfirm}
            style={
              destructive
                ? {
                    background: "var(--error, #dc2626)",
                    color: "#fff",
                    borderColor: "transparent",
                  }
                : undefined
            }
          >
            {confirmLabel ?? t("button.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}
