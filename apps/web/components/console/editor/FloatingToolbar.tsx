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
import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface FloatingToolbarProps {
  editor: Editor;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function FloatingToolbar({ editor }: FloatingToolbarProps) {
  const t = useTranslations("console-notebooks");
  const [showLinkInput, setShowLinkInput] = useState(false);
  const [linkUrl, setLinkUrl] = useState("");

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

  return (
    <BubbleMenu
      editor={editor}
      className="floating-toolbar"
    >
      {showLinkInput ? (
        <div className="floating-toolbar-link-input">
          <input
            type="url"
            value={linkUrl}
            onChange={(e) => setLinkUrl(e.target.value)}
            onKeyDown={handleLinkKeyDown}
            onBlur={() => setShowLinkInput(false)}
            placeholder={t("toolbar.pasteLink")}
            autoFocus
            className="floating-toolbar-input"
          />
        </div>
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
            title={t("toolbar.aiActions")}
            disabled
          >
            <Sparkles size={16} />
          </button>
        </>
      )}
    </BubbleMenu>
  );
}
