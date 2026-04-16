"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import TaskList from "@tiptap/extension-task-list";
import TaskItem from "@tiptap/extension-task-item";
import Image from "@tiptap/extension-image";
import Link from "@tiptap/extension-link";
import HorizontalRule from "@tiptap/extension-horizontal-rule";
import CodeBlockLowlight from "@tiptap/extension-code-block-lowlight";
import { common, createLowlight } from "lowlight";
import { apiGet, apiPatch } from "@/lib/api";
import { MathBlock, InlineMath, CalloutBlock, WhiteboardBlock } from "./extensions";
import SlashCommand from "./SlashCommandMenu";
import FloatingToolbar from "./FloatingToolbar";

import "katex/dist/katex.min.css";
import "@/styles/note-editor.css";

const lowlight = createLowlight(common);

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NoteEditorProps {
  pageId: string;
  onPlainTextChange?: (text: string) => void;
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

export default function NoteEditor({ pageId, onPlainTextChange }: NoteEditorProps) {
  const t = useTranslations("console-notebooks");
  const [title, setTitle] = useState("");
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("saved");
  const [loading, setLoading] = useState(true);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestContentRef = useRef<Record<string, unknown> | null>(null);
  const debouncedSaveRef = useRef<(json: Record<string, unknown>) => void>(() => {});

  const editor = useEditor({
    immediatelyRender: false,
    extensions: [
      StarterKit.configure({
        codeBlock: false,
        horizontalRule: false,
      }),
      Placeholder.configure({
        placeholder: t("editor.placeholder"),
      }),
      TaskList,
      TaskItem.configure({ nested: true }),
      Image.configure({ inline: false }),
      Link.configure({ openOnClick: false, HTMLAttributes: { rel: "noopener noreferrer", target: "_blank" } }),
      HorizontalRule,
      CodeBlockLowlight.configure({ lowlight }),
      MathBlock,
      InlineMath,
      CalloutBlock,
      WhiteboardBlock,
      SlashCommand,
    ],
    editorProps: {
      attributes: {
        class: "note-editor-content",
      },
    },
    onUpdate: ({ editor: ed }) => {
      const json = ed.getJSON();
      latestContentRef.current = json;
      setSaveStatus("unsaved");
      debouncedSaveRef.current(json);
      onPlainTextChange?.(ed.getText());
    },
  });

  // ---- Load page data -----------------------------------------------------

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    void apiGet<PageData>(`/api/v1/pages/${pageId}`).then((data) => {
      if (cancelled) return;
      setTitle(data.title || "");
      if (
        editor &&
        data.content_json &&
        typeof data.content_json === "object" &&
        Object.keys(data.content_json).length > 0
      ) {
        editor.commands.setContent(data.content_json);
      }
      setLoading(false);
    }).catch(() => {
      if (!cancelled) setLoading(false);
    });

    return () => { cancelled = true; };
  }, [pageId, editor]);

  // ---- Auto-save ----------------------------------------------------------

  const saveContent = useCallback(
    async (contentJson: Record<string, unknown>) => {
      setSaveStatus("saving");
      try {
        await apiPatch(`/api/v1/pages/${pageId}`, {
          content_json: contentJson,
          title,
        });
        setSaveStatus("saved");
      } catch {
        setSaveStatus("unsaved");
      }
    },
    [pageId, title],
  );

  const debouncedSave = useCallback(
    (contentJson: Record<string, unknown>) => {
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
      }
      saveTimerRef.current = setTimeout(() => {
        void saveContent(contentJson);
      }, 1500);
    },
    [saveContent],
  );

  // Keep ref in sync so onUpdate closure always calls latest version
  debouncedSaveRef.current = debouncedSave;

  // ---- Title change -------------------------------------------------------

  const handleTitleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setTitle(e.target.value);
      setSaveStatus("unsaved");
      if (latestContentRef.current) {
        debouncedSave(latestContentRef.current);
      }
    },
    [debouncedSave],
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
      // Flush any unsaved content synchronously before unmount
      const pendingContent = latestContentRef.current;
      if (pendingContent && saveStatus !== "saved") {
        void saveContent(pendingContent);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageId]);

  // ---- Render -------------------------------------------------------------

  if (loading) {
    return <div className="note-editor-loading">{t("common.loading")}</div>;
  }

  return (
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
      </div>

      {/* Floating Toolbar (on text selection) */}
      {editor && <FloatingToolbar editor={editor} pageId={pageId} />}

      {/* Editor */}
      <EditorContent editor={editor} />
    </div>
  );
}
