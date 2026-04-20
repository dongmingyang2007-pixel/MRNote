"use client";

import { Node, mergeAttributes } from "@tiptap/core";
import { NodeViewWrapper, ReactNodeViewRenderer } from "@tiptap/react";
import katex from "katex";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Node View Component
// ---------------------------------------------------------------------------

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function MathBlockView(props: any) {
  const t = useTranslations("console-notebooks");
  const { node, updateAttributes, selected } = props;
  const latex: string = node.attrs.latex || "";

  // Enter edit mode immediately if the node was just inserted with empty
  // latex (e.g. via slash menu). Otherwise show the rendered formula.
  const [editing, setEditing] = useState(latex.trim() === "");
  const [draft, setDraft] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const previewRef = useRef<HTMLDivElement>(null);
  const value = draft ?? latex;

  useEffect(() => {
    if (previewRef.current && !editing) {
      if (value.trim() === "") {
        previewRef.current.textContent = "";
        previewRef.current.setAttribute("data-empty", "true");
      } else {
        previewRef.current.removeAttribute("data-empty");
        try {
          katex.render(value, previewRef.current, {
            displayMode: true,
            throwOnError: false,
          });
        } catch {
          previewRef.current.textContent = value;
        }
      }
    }
  }, [value, editing]);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.selectionStart = inputRef.current.value.length;
    }
  }, [editing]);

  const handleBlur = useCallback(() => {
    setEditing(false);
    updateAttributes({ latex: value });
    setDraft(null);
  }, [value, updateAttributes]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault();
        handleBlur();
      }
    },
    [handleBlur],
  );

  return (
    <NodeViewWrapper className="math-block-wrapper" data-selected={selected || undefined}>
      {editing ? (
        <div className="math-block-editor">
          <textarea
            ref={inputRef}
            className="math-block-input"
            value={value}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={handleBlur}
            onKeyDown={handleKeyDown}
            placeholder={t("block.math.placeholder")}
            rows={3}
          />
        </div>
      ) : (
        <div
          className="math-block-preview"
          ref={previewRef}
          onDoubleClick={() => {
            setDraft(latex);
            setEditing(true);
          }}
          title={t("block.math.doubleClickEdit")}
        />
      )}
    </NodeViewWrapper>
  );
}

// ---------------------------------------------------------------------------
// Extension
// ---------------------------------------------------------------------------

const MathBlock = Node.create({
  name: "mathBlock",
  group: "block",
  atom: true,
  selectable: true,
  draggable: true,

  addAttributes() {
    return {
      latex: { default: "" },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="math-block"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-type": "math-block" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(MathBlockView);
  },
});

export default MathBlock;
