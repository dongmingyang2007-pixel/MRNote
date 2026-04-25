"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import TaskList from "@tiptap/extension-task-list";
import TaskItem from "@tiptap/extension-task-item";
import Image from "@tiptap/extension-image";
import HorizontalRule from "@tiptap/extension-horizontal-rule";
import CodeBlockLowlight from "@tiptap/extension-code-block-lowlight";
import Link from "@tiptap/extension-link";
import { common, createLowlight } from "lowlight";
import { apiGet, apiPatch } from "@/lib/api";
import {
  MathBlock,
  InlineMath,
  CalloutBlock,
  WhiteboardBlock,
  FileBlock,
  AIOutputBlock,
  ReferenceBlock,
  TaskBlock,
  FlashcardBlock,
} from "./extensions";
import SlashCommand, { createSuggestionConfig } from "./SlashCommandMenu";
import FloatingToolbar from "./FloatingToolbar";
import { PageIdProvider } from "./PageIdContext";

import "katex/dist/katex.min.css";
import "@/styles/note-editor.css";

const lowlight = createLowlight(common);

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NoteEditorProps {
  pageId: string;
  onPlainTextChange?: (text: string) => void;
  /** Called whenever the title text changes (every keystroke). Parent windows
   *  use this to keep the window titlebar / page list card in sync. */
  onTitleChange?: (title: string) => void;
  guestMode?: boolean;
  initialTitle?: string;
  initialContent?: Record<string, unknown>;
  onGuestSaveRequest?: () => void;
}

interface PageData {
  id: string;
  title: string;
  content_json: Record<string, unknown>;
  updated_at: string;
}

type SaveStatus = "saved" | "saving" | "unsaved";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function NoteEditor({
  pageId,
  onPlainTextChange,
  onTitleChange,
  guestMode = false,
  initialTitle = "",
  initialContent,
  onGuestSaveRequest,
}: NoteEditorProps) {
  const t = useTranslations("console-notebooks");
  const [title, setTitle] = useState(() => (guestMode ? initialTitle : ""));
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("saved");
  const [loading, setLoading] = useState(true);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestContentRef = useRef<Record<string, unknown> | null>(null);
  const guestInitializedRef = useRef(false);
  const titleRef = useRef("");
  const saveStatusRef = useRef<SaveStatus>("saved");
  const debouncedSaveRef = useRef<(json: Record<string, unknown>) => void>(
    () => {},
  );

  const setTrackedTitle = useCallback((nextTitle: string) => {
    titleRef.current = nextTitle;
    setTitle(nextTitle);
  }, []);

  const setTrackedSaveStatus = useCallback((nextStatus: SaveStatus) => {
    saveStatusRef.current = nextStatus;
    setSaveStatus(nextStatus);
  }, []);

  const editor = useEditor({
    immediatelyRender: false,
    extensions: [
      StarterKit.configure({
        codeBlock: false,
        horizontalRule: false,
      }),
      // StarterKit (Tiptap 3.x) does not bundle Link; it must be registered
      // explicitly (see B-05 in notebook audit — the previous `link: {...}`
      // key on StarterKit.configure was silently ignored).
      Link.configure({
        openOnClick: false,
        HTMLAttributes: { rel: "noopener noreferrer", target: "_blank" },
      }),
      Placeholder.configure({
        placeholder: t("editor.placeholder"),
      }),
      TaskList,
      TaskItem.configure({ nested: true }),
      Image.configure({ inline: false }),
      HorizontalRule,
      // Add `language` and `filename` attrs so spec §5.1.3 / §20 code blocks
      // can round-trip the picked language and filename. The language picker
      // UI lives in FloatingToolbar when the code block is active.
      CodeBlockLowlight.extend({
        addAttributes() {
          return {
            ...this.parent?.(),
            language: {
              default: null,
              parseHTML: (element) =>
                element.getAttribute("data-language") ||
                (() => {
                  const codeEl = element.querySelector("code");
                  if (!codeEl) return null;
                  const cls = codeEl.className || "";
                  const match = cls.match(/language-([\w+#-]+)/);
                  return match ? match[1] : null;
                })(),
              renderHTML: (attrs) => {
                const language = (attrs as { language?: string | null })
                  .language;
                return language ? { "data-language": language } : {};
              },
            },
            filename: {
              default: null,
              parseHTML: (element) =>
                element.getAttribute("data-filename") || null,
              renderHTML: (attrs) => {
                const filename = (attrs as { filename?: string | null })
                  .filename;
                return filename ? { "data-filename": filename } : {};
              },
            },
          };
        },
      }).configure({ lowlight }),
      MathBlock,
      InlineMath,
      CalloutBlock,
      WhiteboardBlock,
      FileBlock,
      AIOutputBlock,
      ReferenceBlock,
      TaskBlock,
      FlashcardBlock,
      SlashCommand.configure({
        suggestion: createSuggestionConfig((key: string) => t(key), {
          getPageId: () => pageId,
        }),
      }),
    ],
    editorProps: {
      attributes: {
        class: "note-editor-content",
      },
    },
    onUpdate: ({ editor: ed }) => {
      const json = ed.getJSON();
      latestContentRef.current = json;
      setTrackedSaveStatus("unsaved");
      if (!guestMode) {
        debouncedSaveRef.current(json);
      }
      onPlainTextChange?.(ed.getText());
    },
  });

  // ---- Load page data -----------------------------------------------------

  useEffect(() => {
    if (guestMode) return;
    let cancelled = false;
    setLoading(true);

    void apiGet<PageData>(`/api/v1/pages/${pageId}`)
      .then((data) => {
        if (cancelled) return;
        const t0 = data.title || "";
        setTrackedTitle(t0);
        // Echo loaded title up so parent window syncs its titlebar to the saved value
        onTitleChange?.(t0);
        if (
          editor &&
          data.content_json &&
          typeof data.content_json === "object" &&
          Object.keys(data.content_json).length > 0
        ) {
          latestContentRef.current = data.content_json;
          editor.commands.setContent(data.content_json);
        }
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [guestMode, pageId, editor, onTitleChange, setTrackedTitle]);

  useEffect(() => {
    if (!guestMode || !editor || guestInitializedRef.current) return;
    const content = initialContent ?? { type: "doc", content: [] };
    latestContentRef.current = content;
    setTrackedTitle(initialTitle);
    onTitleChange?.(initialTitle);
    editor.commands.setContent(content);
    setTrackedSaveStatus("unsaved");
    setLoading(false);
    guestInitializedRef.current = true;
  }, [
    editor,
    guestMode,
    initialContent,
    initialTitle,
    onTitleChange,
    setTrackedSaveStatus,
    setTrackedTitle,
  ]);

  // ---- Subscribe to AI Panel "Insert as AI block" events ----------------

  useEffect(() => {
    if (!editor) return;
    function handler(e: Event) {
      const payload = (e as CustomEvent).detail as {
        content_markdown: string;
        action_type: string;
        action_log_id: string;
        model_id: string | null;
        sources: Array<{ type: string; id: string; title: string }>;
      } | null;
      if (!payload || !editor) return;
      editor
        .chain()
        .focus()
        .insertContent({ type: "ai_output", attrs: payload })
        .run();
    }
    window.addEventListener("mrai:insert-ai-output", handler);
    return () => window.removeEventListener("mrai:insert-ai-output", handler);
  }, [editor]);

  // ---- Auto-save ----------------------------------------------------------

  const saveContent = useCallback(
    async (contentJson: Record<string, unknown>, nextTitle?: string) => {
      if (guestMode) {
        latestContentRef.current = contentJson;
        if (nextTitle !== undefined) {
          titleRef.current = nextTitle;
        }
        setTrackedSaveStatus("unsaved");
        onGuestSaveRequest?.();
        return;
      }
      setTrackedSaveStatus("saving");
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 20000);
      try {
        await apiPatch(
          `/api/v1/pages/${pageId}`,
          { content_json: contentJson, title: nextTitle ?? titleRef.current },
          { signal: controller.signal },
        );
        setTrackedSaveStatus("saved");
      } catch {
        setTrackedSaveStatus("unsaved");
      } finally {
        clearTimeout(timeoutId);
      }
    },
    [guestMode, onGuestSaveRequest, pageId, setTrackedSaveStatus],
  );

  const debouncedSave = useCallback(
    (contentJson: Record<string, unknown>, nextTitle?: string) => {
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
      }
      saveTimerRef.current = setTimeout(() => {
        void saveContent(contentJson, nextTitle);
      }, 1500);
    },
    [saveContent],
  );

  // Keep ref in sync so onUpdate closure always calls latest version
  debouncedSaveRef.current = debouncedSave;

  // Manual save — cancels any pending debounce and saves immediately.
  const saveNow = useCallback(() => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    const content = latestContentRef.current ??
      (editor?.getJSON() as Record<string, unknown> | undefined) ?? {
        type: "doc",
        content: [],
      };
    void saveContent(content);
  }, [saveContent, editor]);

  // Cmd+S / Ctrl+S keyboard shortcut anywhere in the editor wrapper
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        saveNow();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [saveNow]);

  // ---- Title change -------------------------------------------------------

  const handleTitleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const nextTitle = e.target.value;
      setTrackedTitle(nextTitle);
      setTrackedSaveStatus("unsaved");
      onTitleChange?.(nextTitle);
      if (guestMode) {
        return;
      }
      // Always debounce-save on title change — even when the body is still empty
      // (new page, user only typed a title). Fall back to the editor's current
      // doc, then to an empty Tiptap doc so the server gets a valid payload.
      const content = latestContentRef.current ??
        (editor?.getJSON() as Record<string, unknown> | undefined) ?? {
          type: "doc",
          content: [],
        };
      debouncedSave(content, nextTitle);
    },
    [
      debouncedSave,
      editor,
      guestMode,
      onTitleChange,
      setTrackedSaveStatus,
      setTrackedTitle,
    ],
  );

  // ---- Title Enter → focus editor ----------------------------------------

  const handleTitleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        e.preventDefault();
        editor?.commands.focus("start");
      }
    },
    [editor],
  );

  // ---- Flush pending save on unmount ---------------------------------------

  useEffect(() => {
    return () => {
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
      }
      if (guestMode) return;
      // Flush any unsaved content synchronously before unmount
      const pendingContent = latestContentRef.current;
      if (pendingContent && saveStatusRef.current !== "saved") {
        void saveContent(pendingContent, titleRef.current);
      }
    };
  }, [guestMode, pageId, saveContent]);

  // ---- Render -------------------------------------------------------------

  if (loading) {
    return <div className="note-editor-loading">{t("common.loading")}</div>;
  }

  return (
    <PageIdProvider pageId={pageId}>
      <div className="note-editor-wrapper">
        {/* Header */}
        <div className="note-editor-header">
          <input
            className="note-editor-title"
            type="text"
            value={title}
            onChange={handleTitleChange}
            onKeyDown={handleTitleKeyDown}
            placeholder={t("pages.untitled")}
          />
          <span className="note-editor-save-status" data-status={saveStatus}>
            {t(`pages.${saveStatus}` as "pages.saving")}
          </span>
          <button
            type="button"
            data-testid="note-editor-save"
            onClick={saveNow}
            disabled={saveStatus === "saving"}
            title={t("pages.saveNow") + " (⌘S)"}
            aria-label={t("pages.saveNow")}
            style={{
              marginLeft: 8,
              padding: "4px 10px",
              fontSize: 12,
              fontWeight: 500,
              borderRadius: 6,
              border: "1px solid var(--border, rgba(15,42,45,0.12))",
              background:
                saveStatus === "unsaved"
                  ? "var(--accent, #0d9488)"
                  : "transparent",
              color:
                saveStatus === "unsaved" ? "#fff" : "var(--text-secondary)",
              cursor: saveStatus === "saving" ? "wait" : "pointer",
              transition: "all 150ms ease",
            }}
          >
            {t("pages.save")}
          </button>
        </div>

        {/* Floating Toolbar (on text selection) */}
        {editor && <FloatingToolbar editor={editor} pageId={pageId} />}

        {/* Editor */}
        <EditorContent editor={editor} />
      </div>
    </PageIdProvider>
  );
}
