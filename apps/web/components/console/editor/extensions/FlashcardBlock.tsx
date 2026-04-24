"use client";

import { Node, mergeAttributes } from "@tiptap/core";
import type { NodeViewProps } from "@tiptap/react";
import { NodeViewWrapper, ReactNodeViewRenderer } from "@tiptap/react";
import { useCallback, useEffect, useState } from "react";
import { Layers, Pencil, Eye } from "lucide-react";
import { useTranslations } from "next-intl";
import DeckPickerDialog from "@/components/notebook/contents/study/DeckPickerDialog";
import { apiGet, apiPost } from "@/lib/api";
import { useCurrentPageId } from "@/components/console/editor/PageIdContext";

interface FlashcardAttrs {
  front: string;
  back: string;
  flipped: boolean;
  card_id: string | null;
}

function FlashcardBlockView(props: NodeViewProps) {
  const t = useTranslations("console-notebooks");
  const attrs = props.node.attrs as FlashcardAttrs;
  const [mode, setMode] = useState<"edit" | "preview">(
    attrs.front || attrs.back ? "preview" : "edit",
  );
  const [picking, setPicking] = useState(false);
  const [adding, setAdding] = useState(false);
  // U-14 — derive notebookId from the current page's API metadata rather than
  // parsing window.location. Falls back to null if the editor is mounted
  // outside a notebook route (e.g. in a storybook / preview).
  const pageId = useCurrentPageId();
  const [notebookId, setNotebookId] = useState<string | null>(null);
  useEffect(() => {
    if (!pageId) {
      setNotebookId(null);
      return;
    }
    let cancelled = false;
    void apiGet<{ notebook_id?: string }>(`/api/v1/pages/${pageId}`)
      .then((data) => {
        if (!cancelled) setNotebookId(data.notebook_id ?? null);
      })
      .catch(() => {
        if (!cancelled) setNotebookId(null);
      });
    return () => {
      cancelled = true;
    };
  }, [pageId]);

  const handleFlip = useCallback(() => {
    props.updateAttributes({ flipped: !attrs.flipped });
  }, [attrs.flipped, props]);

  const handleAddToDeck = useCallback(
    async (deck: { id: string; name: string }) => {
      if (!attrs.front.trim() || !attrs.back.trim()) {
        setPicking(false);
        return;
      }
      setAdding(true);
      try {
        const card = await apiPost<{ id: string }>(
          `/api/v1/decks/${deck.id}/cards`,
          {
            front: attrs.front,
            back: attrs.back,
            source_type: "block",
          },
        );
        props.updateAttributes({ card_id: card.id });
      } finally {
        setAdding(false);
        setPicking(false);
      }
    },
    [attrs, props],
  );

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
          <Pencil size={12} /> {t("block.flashcard.edit")}
        </button>
        <button
          type="button"
          className={`flashcard-block__mode${mode === "preview" ? " is-active" : ""}`}
          onClick={() => setMode("preview")}
          data-testid="flashcard-mode-preview"
        >
          <Eye size={12} /> {t("block.flashcard.preview")}
        </button>
        {!attrs.card_id && (
          <button
            type="button"
            className="flashcard-block__mode"
            onClick={() => setPicking(true)}
            disabled={adding}
            data-testid="flashcard-add-to-deck"
          >
            {adding ? t("block.flashcard.adding") : t("block.flashcard.add")}
          </button>
        )}
        {attrs.card_id && (
          <span
            className="flashcard-block__in-deck"
            data-testid="flashcard-in-deck"
            style={{ fontSize: 10, color: "var(--console-accent, #0D9488)", marginLeft: 6 }}
          >
            {t("block.flashcard.inDeck")}
          </span>
        )}
      </div>
      {mode === "edit" ? (
        <div className="flashcard-block__editor">
          <textarea
            placeholder={t("block.flashcard.frontPlaceholder")}
            value={attrs.front}
            onChange={(e) => props.updateAttributes({ front: e.target.value })}
            data-testid="flashcard-front"
          />
          <textarea
            placeholder={t("block.flashcard.backPlaceholder")}
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
            isBack
              ? t("block.flashcard.ariaBack")
              : t("block.flashcard.ariaFront")
          }
          data-testid="flashcard-card"
        >
          <span className="flashcard-block__hint">
            {isBack ? t("block.flashcard.hintAnswer") : t("block.flashcard.hintQuestion")} · {t("block.flashcard.hintFlip")}
          </span>
          <div className="flashcard-block__body">
            {isBack ? attrs.back || "(empty)" : attrs.front || "(empty)"}
          </div>
        </button>
      )}
      {picking && notebookId && (
        <DeckPickerDialog
          notebookId={notebookId}
          onPick={(d) => void handleAddToDeck(d)}
          onCancel={() => setPicking(false)}
        />
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
      card_id: { default: null as string | null },
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
