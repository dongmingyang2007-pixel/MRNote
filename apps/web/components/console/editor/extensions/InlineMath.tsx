import { Node, mergeAttributes } from "@tiptap/core";
import { NodeViewWrapper, ReactNodeViewRenderer } from "@tiptap/react";
import katex from "katex";
import { useCallback, useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Node View Component
// ---------------------------------------------------------------------------

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function InlineMathView(props: any) {
  const { node, updateAttributes, selected } = props;
  const latex: string = node.attrs.latex || "";

  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(latex);
  const inputRef = useRef<HTMLInputElement>(null);
  const spanRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    setValue(node.attrs.latex || "");
  }, [node.attrs.latex]);

  useEffect(() => {
    if (spanRef.current && !editing) {
      try {
        katex.render(value || "?", spanRef.current, {
          displayMode: false,
          throwOnError: false,
        });
      } catch {
        spanRef.current.textContent = value || "?";
      }
    }
  }, [value, editing]);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
    }
  }, [editing]);

  const handleBlur = useCallback(() => {
    setEditing(false);
    updateAttributes({ latex: value });
  }, [value, updateAttributes]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape" || e.key === "Enter") {
        e.preventDefault();
        handleBlur();
      }
    },
    [handleBlur],
  );

  return (
    <NodeViewWrapper as="span" className="inline-math-wrapper" data-selected={selected || undefined}>
      {editing ? (
        <input
          ref={inputRef}
          className="inline-math-input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onBlur={handleBlur}
          onKeyDown={handleKeyDown}
          placeholder="LaTeX…"
          size={Math.max(value.length + 2, 6)}
        />
      ) : (
        <span
          ref={spanRef}
          className="inline-math-preview"
          onDoubleClick={() => setEditing(true)}
          title="Double-click to edit"
        />
      )}
    </NodeViewWrapper>
  );
}

// ---------------------------------------------------------------------------
// Extension
// ---------------------------------------------------------------------------

const InlineMath = Node.create({
  name: "inlineMath",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,

  addAttributes() {
    return {
      latex: { default: "" },
    };
  },

  parseHTML() {
    return [{ tag: 'span[data-type="inline-math"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["span", mergeAttributes(HTMLAttributes, { "data-type": "inline-math" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(InlineMathView);
  },
});

export default InlineMath;
