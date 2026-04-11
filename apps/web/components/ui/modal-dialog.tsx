"use client";

import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";

/* ── Types ─────────────────────────────────────── */

type ModalType = "prompt" | "confirm" | "alert";

interface ModalState {
  type: ModalType;
  message: string;
  defaultValue?: string;
  placeholder?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  resolve: (value: string | boolean | null) => void;
}

interface ModalContextValue {
  prompt: (
    message: string,
    opts?: { defaultValue?: string; placeholder?: string; confirmLabel?: string; cancelLabel?: string },
  ) => Promise<string | null>;
  confirm: (
    message: string,
    opts?: { confirmLabel?: string; cancelLabel?: string },
  ) => Promise<boolean>;
  alert: (message: string, opts?: { confirmLabel?: string }) => Promise<void>;
}

const ModalContext = createContext<ModalContextValue | null>(null);

/* ── Hook ──────────────────────────────────────── */

export function useModal(): ModalContextValue {
  const ctx = useContext(ModalContext);
  if (!ctx) {
    throw new Error("useModal must be used inside <ModalProvider>");
  }
  return ctx;
}

/* ── Provider ──────────────────────────────────── */

export function ModalProvider({ children }: { children: ReactNode }) {
  const [modal, setModal] = useState<ModalState | null>(null);
  const [inputValue, setInputValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const prompt = useCallback(
    (
      message: string,
      opts?: { defaultValue?: string; placeholder?: string; confirmLabel?: string; cancelLabel?: string },
    ): Promise<string | null> =>
      new Promise((resolve) => {
        setInputValue(opts?.defaultValue ?? "");
        setModal({
          type: "prompt",
          message,
          defaultValue: opts?.defaultValue,
          placeholder: opts?.placeholder,
          confirmLabel: opts?.confirmLabel,
          cancelLabel: opts?.cancelLabel,
          resolve: resolve as (v: string | boolean | null) => void,
        });
        setTimeout(() => inputRef.current?.focus(), 50);
      }),
    [],
  );

  const confirm = useCallback(
    (
      message: string,
      opts?: { confirmLabel?: string; cancelLabel?: string },
    ): Promise<boolean> =>
      new Promise((resolve) => {
        setModal({
          type: "confirm",
          message,
          confirmLabel: opts?.confirmLabel,
          cancelLabel: opts?.cancelLabel,
          resolve: resolve as (v: string | boolean | null) => void,
        });
      }),
    [],
  );

  const alert = useCallback(
    (message: string, opts?: { confirmLabel?: string }): Promise<void> =>
      new Promise((resolve) => {
        setModal({
          type: "alert",
          message,
          confirmLabel: opts?.confirmLabel,
          resolve: (() => resolve()) as (v: string | boolean | null) => void,
        });
      }),
    [],
  );

  const handleConfirm = useCallback(() => {
    if (!modal) return;
    if (modal.type === "prompt") {
      modal.resolve(inputValue);
    } else if (modal.type === "confirm") {
      modal.resolve(true);
    } else {
      modal.resolve(null);
    }
    setModal(null);
    setInputValue("");
  }, [modal, inputValue]);

  const handleCancel = useCallback(() => {
    if (!modal) return;
    if (modal.type === "prompt") {
      modal.resolve(null);
    } else if (modal.type === "confirm") {
      modal.resolve(false);
    } else {
      modal.resolve(null);
    }
    setModal(null);
    setInputValue("");
  }, [modal]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") {
        e.preventDefault();
        handleConfirm();
      } else if (e.key === "Escape") {
        e.preventDefault();
        handleCancel();
      }
    },
    [handleConfirm, handleCancel],
  );

  return (
    <ModalContext.Provider value={{ prompt, confirm, alert }}>
      {children}

      {modal && (
        <div className="app-modal-overlay" onClick={handleCancel} onKeyDown={handleKeyDown}>
          <div
            className="app-modal"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
          >
            <p className="app-modal-message">{modal.message}</p>

            {modal.type === "prompt" && (
              <input
                ref={inputRef}
                className="app-modal-input"
                type="text"
                value={inputValue}
                placeholder={modal.placeholder}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
              />
            )}

            <div className="app-modal-actions">
              {modal.type !== "alert" && (
                <button
                  className="app-modal-btn app-modal-btn-cancel"
                  onClick={handleCancel}
                  type="button"
                >
                  {modal.cancelLabel ?? "取消"}
                </button>
              )}
              <button
                className="app-modal-btn app-modal-btn-confirm"
                onClick={handleConfirm}
                type="button"
              >
                {modal.confirmLabel ?? "确定"}
              </button>
            </div>
          </div>
        </div>
      )}
    </ModalContext.Provider>
  );
}
