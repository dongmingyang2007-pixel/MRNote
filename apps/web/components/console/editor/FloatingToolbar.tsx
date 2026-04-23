"use client";

import { BubbleMenu } from "@tiptap/react/menus";
import type { Editor } from "@tiptap/react";
import {
  Bold,
  Italic,
  Strikethrough,
  Code,
  Link,
  Heading1,
  Heading2,
  Sparkles,
} from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import AISelectionActions, { type ActionApplyPayload } from "./AISelectionActions";

// ---------------------------------------------------------------------------
// Code block language options (Spec §5.1.3 / §20)
// ---------------------------------------------------------------------------

const CODE_LANGUAGES: Array<{ value: string; label: string }> = [
  { value: "plain", label: "Plain" },
  { value: "python", label: "Python" },
  { value: "typescript", label: "TypeScript" },
  { value: "javascript", label: "JavaScript" },
  { value: "bash", label: "Bash" },
  { value: "sql", label: "SQL" },
  { value: "go", label: "Go" },
  { value: "rust", label: "Rust" },
  { value: "markdown", label: "Markdown" },
  { value: "json", label: "JSON" },
];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface FloatingToolbarProps {
  editor: Editor;
  pageId: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function FloatingToolbar({ editor, pageId }: FloatingToolbarProps) {
  const t = useTranslations("console-notebooks");
  const [showLinkInput, setShowLinkInput] = useState(false);
  const [linkUrl, setLinkUrl] = useState("");
  const [showAIActions, setShowAIActions] = useState(false);
  const [selectionRange, setSelectionRange] = useState<{ from: number; to: number } | null>(null);
  const [selectedText, setSelectedText] = useState("");
  // U-24 — delayed onBlur so clicking nearby elements (e.g. the same
  // container) doesn't collapse the link input prematurely.
  const linkWrapRef = useRef<HTMLDivElement>(null);

  const toggleLink = useCallback(() => {
    if (editor.isActive("link")) {
      editor.chain().focus().unsetLink().run();
      return;
    }
    setShowLinkInput(true);
    setLinkUrl("");
  }, [editor]);

  const submitLink = useCallback(() => {
    if (linkUrl.trim()) {
      const url = linkUrl.startsWith("http") ? linkUrl : `https://${linkUrl}`;
      editor.chain().focus().setLink({ href: url }).run();
    }
    setShowLinkInput(false);
    setLinkUrl("");
  }, [editor, linkUrl]);

  const openAIActions = useCallback(() => {
    const { from, to, empty } = editor.state.selection;
    if (empty) {
      return;
    }
    setShowLinkInput(false);
    setSelectionRange({ from, to });
    setSelectedText(editor.state.doc.textBetween(from, to, "\n"));
    setShowAIActions(true);
  }, [editor]);

  const handleApplyAI = useCallback(
    (payload: ActionApplyPayload) => {
      if (!selectionRange) {
        return;
      }

      if (payload.mode === "insert_task") {
        // Insert a TaskBlock node right after the selection. Uses the custom
        // `task` extension registered in NoteEditor. We generate a fresh
        // client-side block_id; the backend will replace it on next save if
        // needed (see TaskBlock attrs).
        const blockId =
          typeof crypto !== "undefined" && "randomUUID" in crypto
            ? crypto.randomUUID()
            : `task-${Date.now()}`;
        editor
          .chain()
          .focus()
          .insertContentAt(selectionRange.to, {
            type: "task",
            attrs: {
              block_id: blockId,
              title: payload.title,
              description: null,
              due_date: null,
              completed: false,
              completed_at: null,
            },
          })
          .run();
      } else if (payload.mode === "replace") {
        editor.chain().focus().insertContentAt(selectionRange, payload.text).run();
      } else {
        editor
          .chain()
          .focus()
          .insertContentAt(selectionRange.to, `\n\n${payload.text}`)
          .run();
      }

      setShowAIActions(false);
      setSelectionRange(null);
      setSelectedText("");
    },
    [editor, selectionRange],
  );

  const handleCloseAI = useCallback(() => {
    setShowAIActions(false);
    setSelectionRange(null);
    setSelectedText("");
  }, []);

  const handleLinkKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") {
        e.preventDefault();
        submitLink();
      }
      if (e.key === "Escape") {
        setShowLinkInput(false);
      }
    },
    [submitLink],
  );

  const codeBlockActive = editor.isActive("codeBlock");
  const codeBlockLanguage = (editor.getAttributes("codeBlock")?.language as string | null) ?? "";
  const codeBlockFilename = (editor.getAttributes("codeBlock")?.filename as string | null) ?? "";

  const handleSetLanguage = useCallback(
    (language: string) => {
      editor
        .chain()
        .focus()
        .updateAttributes("codeBlock", { language: language || null })
        .run();
    },
    [editor],
  );

  const handleSetFilename = useCallback(
    (filename: string) => {
      const trimmed = filename.trim();
      editor
        .chain()
        .focus()
        .updateAttributes("codeBlock", { filename: trimmed ? trimmed : null })
        .run();
    },
    [editor],
  );

  return (
    <BubbleMenu
      editor={editor}
      className="floating-toolbar"
      options={{ placement: "top" }}
      shouldShow={({ editor: currentEditor }) =>
        showLinkInput ||
        showAIActions ||
        currentEditor.isActive("codeBlock") ||
        !currentEditor.state.selection.empty
      }
    >
      {codeBlockActive && !showAIActions && !showLinkInput ? (
        <div
          className="floating-toolbar-code"
          data-testid="floating-toolbar-code"
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <label style={{ fontSize: 11, color: "var(--console-text-muted, #64748b)" }}>
            {t("editor.codeBlock")}
          </label>
          <select
            data-testid="floating-toolbar-code-language"
            value={codeBlockLanguage || ""}
            onChange={(e) => handleSetLanguage(e.target.value)}
            style={{
              padding: "4px 8px",
              fontSize: 12,
              borderRadius: 6,
              border: "1px solid rgba(15,23,42,0.12)",
              background: "#fff",
              cursor: "pointer",
            }}
            aria-label={t("toolbar.code_language")}
          >
            <option value="">{t("toolbar.code_language_auto")}</option>
            {CODE_LANGUAGES.map((lang) => (
              <option key={lang.value} value={lang.value}>
                {lang.label}
              </option>
            ))}
          </select>
          <input
            type="text"
            data-testid="floating-toolbar-code-filename"
            value={codeBlockFilename}
            onChange={(e) => handleSetFilename(e.target.value)}
            placeholder={t("toolbar.code_filename_placeholder")}
            style={{
              padding: "4px 8px",
              width: 140,
              fontSize: 12,
              borderRadius: 6,
              border: "1px solid rgba(15,23,42,0.12)",
            }}
            aria-label={t("toolbar.code_filename")}
          />
        </div>
      ) : showLinkInput ? (
        <div className="floating-toolbar-link-input" ref={linkWrapRef}>
          <input
            type="url"
            value={linkUrl}
            onChange={(e) => setLinkUrl(e.target.value)}
            onKeyDown={handleLinkKeyDown}
            onBlur={() => {
              // Delay so a click on a sibling element (e.g. a paste target
              // or a nearby toolbar button) doesn't immediately close the
              // input. If focus stayed inside the wrapper we abort.
              window.setTimeout(() => {
                if (
                  !linkWrapRef.current?.contains(document.activeElement)
                ) {
                  setShowLinkInput(false);
                }
              }, 120);
            }}
            placeholder={t("toolbar.pasteLink")}
            autoFocus
            className="floating-toolbar-input"
          />
        </div>
      ) : showAIActions ? (
        <AISelectionActions
          pageId={pageId}
          selectedText={selectedText}
          onApply={handleApplyAI}
          onClose={handleCloseAI}
        />
      ) : (
        <>
          <button
            type="button"
            className={`floating-toolbar-btn${editor.isActive("bold") ? " is-active" : ""}`}
            onClick={() => editor.chain().focus().toggleBold().run()}
            title={t("toolbar.bold")}
          >
            <Bold size={16} />
          </button>
          <button
            type="button"
            className={`floating-toolbar-btn${editor.isActive("italic") ? " is-active" : ""}`}
            onClick={() => editor.chain().focus().toggleItalic().run()}
            title={t("toolbar.italic")}
          >
            <Italic size={16} />
          </button>
          <button
            type="button"
            className={`floating-toolbar-btn${editor.isActive("strike") ? " is-active" : ""}`}
            onClick={() => editor.chain().focus().toggleStrike().run()}
            title={t("toolbar.strikethrough")}
          >
            <Strikethrough size={16} />
          </button>
          <button
            type="button"
            className={`floating-toolbar-btn${editor.isActive("code") ? " is-active" : ""}`}
            onClick={() => editor.chain().focus().toggleCode().run()}
            title={t("toolbar.code")}
          >
            <Code size={16} />
          </button>

          <span className="floating-toolbar-divider" />

          <button
            type="button"
            className={`floating-toolbar-btn${editor.isActive("link") ? " is-active" : ""}`}
            onClick={toggleLink}
            title={t("toolbar.link")}
          >
            <Link size={16} />
          </button>

          <span className="floating-toolbar-divider" />

          <button
            type="button"
            className={`floating-toolbar-btn${editor.isActive("heading", { level: 1 }) ? " is-active" : ""}`}
            onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
            title={t("toolbar.heading1")}
          >
            <Heading1 size={16} />
          </button>
          <button
            type="button"
            className={`floating-toolbar-btn${editor.isActive("heading", { level: 2 }) ? " is-active" : ""}`}
            onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
            title={t("toolbar.heading2")}
          >
            <Heading2 size={16} />
          </button>

          <span className="floating-toolbar-divider" />

          <button
            type="button"
            className="floating-toolbar-btn floating-toolbar-ai-btn"
            onClick={openAIActions}
            title={t("toolbar.aiActions")}
            disabled={editor.state.selection.empty}
          >
            <Sparkles size={16} />
          </button>
        </>
      )}
    </BubbleMenu>
  );
}
