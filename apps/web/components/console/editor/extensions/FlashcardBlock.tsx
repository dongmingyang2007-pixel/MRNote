"use client";

import { Node, mergeAttributes } from "@tiptap/core";
import type { NodeViewProps } from "@tiptap/react";
import { NodeViewWrapper, ReactNodeViewRenderer } from "@tiptap/react";
import { useCallback, useState } from "react";
import { Layers, Pencil, Eye } from "lucide-react";

interface FlashcardAttrs {
  front: string;
  back: string;
  flipped: boolean;
}

function FlashcardBlockView(props: NodeViewProps) {
  const attrs = props.node.attrs as FlashcardAttrs;
  const [mode, setMode] = useState<"edit" | "preview">(
    attrs.front || attrs.back ? "preview" : "edit",
  );

  const handleFlip = useCallback(() => {
    props.updateAttributes({ flipped: !attrs.flipped });
  }, [attrs.flipped, props]);

  const isBack = attrs.flipped;

  return (
    <NodeViewWrapper className="flashcard-block" data-testid="flashcard-block">
      <div className="flashcard-block__toolbar">
        <Layers size={14} />
        <button
          type="button"
          className={`flashcard-block__mode${mode === "edit" ? " is-active" : ""}`}
          onClick={() => setMode("edit")}
          data-testid="flashcard-mode-edit"
        >
          <Pencil size={12} /> Edit
        </button>
        <button
          type="button"
          className={`flashcard-block__mode${mode === "preview" ? " is-active" : ""}`}
          onClick={() => setMode("preview")}
          data-testid="flashcard-mode-preview"
        >
          <Eye size={12} /> Preview
        </button>
      </div>
      {mode === "edit" ? (
        <div className="flashcard-block__editor">
          <textarea
            placeholder="Front (question)"
            value={attrs.front}
            onChange={(e) => props.updateAttributes({ front: e.target.value })}
            data-testid="flashcard-front"
          />
          <textarea
            placeholder="Back (answer)"
            value={attrs.back}
            onChange={(e) => props.updateAttributes({ back: e.target.value })}
            data-testid="flashcard-back"
          />
        </div>
      ) : (
        <button
          type="button"
          onClick={handleFlip}
          className={`flashcard-block__card${isBack ? " is-flipped" : ""}`}
          aria-label={
            isBack ? "Flashcard, back side" : "Flashcard, front side"
          }
          data-testid="flashcard-card"
        >
          <span className="flashcard-block__hint">
            {isBack ? "Answer" : "Question"} · click to flip
          </span>
          <div className="flashcard-block__body">
            {isBack ? attrs.back || "(empty)" : attrs.front || "(empty)"}
          </div>
        </button>
      )}
    </NodeViewWrapper>
  );
}

const FlashcardBlock = Node.create({
  name: "flashcard",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      front: { default: "" },
      back: { default: "" },
      flipped: { default: false },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="flashcard"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-type": "flashcard" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(FlashcardBlockView);
  },
});

export default FlashcardBlock;
