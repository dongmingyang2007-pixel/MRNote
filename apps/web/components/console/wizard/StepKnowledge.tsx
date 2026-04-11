"use client";

import { useTranslations } from "next-intl";
import { useCallback, useRef, useState } from "react";

const ACCEPTED_EXTENSIONS = [".pdf", ".txt", ".docx", ".md"];
const ACCEPTED_MIME = [
  "application/pdf",
  "text/plain",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/markdown",
];

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface StepKnowledgeProps {
  files: File[];
  onFilesChange: (files: File[]) => void;
  onSubmit: () => void;
  isSubmitting: boolean;
}

export function StepKnowledge({ files, onFilesChange, onSubmit, isSubmitting }: StepKnowledgeProps) {
  const t = useTranslations("console-assistants");
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback(
    (incoming: FileList | File[]) => {
      const valid = Array.from(incoming).filter((f) => {
        const ext = f.name.substring(f.name.lastIndexOf(".")).toLowerCase();
        return ACCEPTED_EXTENSIONS.includes(ext) || ACCEPTED_MIME.includes(f.type);
      });
      if (valid.length > 0) {
        onFilesChange([...files, ...valid]);
      }
    },
    [files, onFilesChange],
  );

  const removeFile = useCallback(
    (index: number) => {
      onFilesChange(files.filter((_, i) => i !== index));
    },
    [files, onFilesChange],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      if (e.dataTransfer.files.length > 0) {
        addFiles(e.dataTransfer.files);
      }
    },
    [addFiles],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
  }, []);

  return (
    <div className="wizard-step-knowledge">
      <h2 className="wizard-step-title">{t("wizard.stepKnowledge")}</h2>
      <p className="wizard-step-desc">{t("wizard.stepKnowledgeDesc")}</p>

      <div className="wizard-knowledge-skip-banner">
        <span>{t("wizard.knowledge.skipNotice")}</span>
        <button
          type="button"
          className="wizard-knowledge-skip-link"
          onClick={onSubmit}
          disabled={isSubmitting}
        >
          {t("wizard.knowledge.skipLink")} &rarr;
        </button>
      </div>

      <div
        className={`wizard-upload-area ${isDragOver ? "wizard-upload-area--active" : ""}`}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
        }}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPTED_EXTENSIONS.join(",")}
          style={{ display: "none" }}
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <div className="wizard-upload-icon">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
        </div>
        <p className="wizard-upload-text">{t("wizard.uploadText")}</p>
        <p className="wizard-upload-hint">{t("wizard.uploadHint")}</p>
      </div>

      {files.length > 0 && (
        <ul className="wizard-file-list">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="wizard-file-item">
              <span className="wizard-file-name">{f.name}</span>
              <span className="wizard-file-size">{formatFileSize(f.size)}</span>
              <button
                type="button"
                className="wizard-file-remove"
                onClick={() => removeFile(i)}
                aria-label={`Remove ${f.name}`}
              >
                &times;
              </button>
            </li>
          ))}
        </ul>
      )}

    </div>
  );
}
