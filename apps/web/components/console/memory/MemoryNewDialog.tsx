"use client";

import { useState, useRef, useEffect } from "react";
import { useTranslations } from "next-intl";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface MemoryNewDialogProps {
  open: boolean;
  onClose: () => void;
  onCreate: (content: string, category: string) => Promise<void>;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MemoryNewDialog({
  open,
  onClose,
  onCreate,
}: MemoryNewDialogProps) {
  const t = useTranslations();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const [content, setContent] = useState("");
  const [category, setCategory] = useState("");
  const [saving, setSaving] = useState(false);

  // Auto-focus textarea when dialog opens
  useEffect(() => {
    if (open) {
      // Small delay to ensure the DOM has rendered
      const timer = setTimeout(() => {
        textareaRef.current?.focus();
      }, 0);
      return () => clearTimeout(timer);
    }
  }, [open]);

  // ESC key closes dialog
  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  const handleSave = async () => {
    if (!content.trim() || saving) return;

    setSaving(true);
    try {
      await onCreate(content.trim(), category.trim());
      setContent("");
      setCategory("");
      onClose();
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  return (
    // Backdrop
    <div className="mem-dialog-backdrop" onClick={onClose}>
      {/* Dialog - stop propagation to prevent backdrop close */}
      <div
        className="mem-new-dialog"
        onClick={(e) => e.stopPropagation()}
      >
        <h3>{t("memory.newTitle")}</h3>

        <label>
          {t("memory.newContentLabel")}
          <textarea
            ref={textareaRef}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={4}
          />
        </label>

        <label>
          {t("memory.newCategoryLabel")}
          <input
            type="text"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          />
        </label>

        <div className="mem-new-dialog-actions">
          <button
            type="button"
            className="mem-action-btn"
            onClick={onClose}
          >
            {t("memory.cancel")}
          </button>
          <button
            type="button"
            className="mem-action-btn is-primary"
            disabled={!content.trim() || saving}
            onClick={handleSave}
          >
            {t("memory.save")}
          </button>
        </div>
      </div>
    </div>
  );
}
