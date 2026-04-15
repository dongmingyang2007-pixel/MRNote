import { Node, mergeAttributes } from "@tiptap/core";
import type { NodeViewProps } from "@tiptap/react";
import { NodeViewWrapper, ReactNodeViewRenderer } from "@tiptap/react";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Dynamic Excalidraw import (client-only)
// ---------------------------------------------------------------------------

const Excalidraw = dynamic(
  async () => (await import("@excalidraw/excalidraw")).Excalidraw,
  { ssr: false },
);

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ExcalidrawElement {
  [key: string]: unknown;
}

interface ExcalidrawAppState {
  [key: string]: unknown;
}

type WhiteboardNodeViewProps = NodeViewProps & {
  node: NodeViewProps["node"] & {
    attrs: {
      elements?: ExcalidrawElement[];
      appState?: ExcalidrawAppState;
      width?: number;
      height?: number;
    };
  };
};

// ---------------------------------------------------------------------------
// Node View Component
// ---------------------------------------------------------------------------

function WhiteboardBlockView(props: WhiteboardNodeViewProps) {
  const { node, updateAttributes, selected } = props;

  const rawElements = node.attrs.elements;
  const rawAppState = node.attrs.appState;
  const width: number = node.attrs.width || 600;
  const height: number = node.attrs.height || 400;

  // Stabilize elements reference to avoid re-render loops from TipTap attr updates
  const elementsKey = JSON.stringify(rawElements || []);
  const elements: ExcalidrawElement[] = useMemo(
    () => rawElements || [],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [elementsKey],
  );
  const appState: ExcalidrawAppState = rawAppState || {};

  const [editing, setEditing] = useState(false);
  const [svgPreview, setSvgPreview] = useState<string | null>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const previewContainerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ---- Generate SVG preview ------------------------------------------------

  const generatePreview = useCallback(async (els: ExcalidrawElement[]) => {
    if (typeof window === "undefined" || els.length === 0) {
      setSvgPreview(null);
      return;
    }
    try {
      const { exportToSvg } = await import("@excalidraw/excalidraw");
      const svg = await exportToSvg({
        elements: els as Parameters<typeof exportToSvg>[0]["elements"],
        appState: {
          exportBackground: true,
          viewBackgroundColor: "#ffffff",
        },
        files: null,
      });
      setSvgPreview(svg.outerHTML);
    } catch {
      setSvgPreview(null);
    }
  }, []);

  // Re-generate preview when elements change externally (e.g. load from DB)
  useEffect(() => {
    if (!editing) {
      void generatePreview(elements);
    }
  }, [elements, editing, generatePreview]);

  // ---- Safely inject SVG into DOM ------------------------------------------

  useEffect(() => {
    if (!previewContainerRef.current || editing) return;
    // Clear previous content
    previewContainerRef.current.textContent = "";

    if (svgPreview) {
      // Parse the SVG string and inject as a DOM node to avoid
      // dangerouslySetInnerHTML. Content is from exportToSvg, not user input.
      const parser = new DOMParser();
      const doc = parser.parseFromString(svgPreview, "image/svg+xml");
      const svgEl = doc.documentElement;
      if (svgEl && svgEl.tagName === "svg") {
        previewContainerRef.current.appendChild(
          document.importNode(svgEl, true),
        );
      }
    }
  }, [svgPreview, editing]);

  // ---- Click-outside to exit edit mode -------------------------------------

  useEffect(() => {
    if (!editing) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as globalThis.Node)) {
        setEditing(false);
      }
    };

    // Use a timeout so the click that enters edit mode doesn't immediately exit
    const timer = setTimeout(() => {
      document.addEventListener("mousedown", handleClickOutside);
    }, 100);

    return () => {
      clearTimeout(timer);
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [editing]);

  // ---- Debounced onChange handler -------------------------------------------

  const handleChange = useCallback(
    (newElements: readonly ExcalidrawElement[], newAppState: ExcalidrawAppState) => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
      debounceRef.current = setTimeout(() => {
        // Only persist relevant appState keys, not transient UI state
        const { viewBackgroundColor, currentItemFontFamily, zoom } =
          newAppState as Record<string, unknown>;
        updateAttributes({
          elements: [...newElements],
          appState: { viewBackgroundColor, currentItemFontFamily, zoom },
        });
      }, 500);
    },
    [updateAttributes],
  );

  // Cleanup debounce timer on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  // ---- Render --------------------------------------------------------------

  const isEmpty = elements.length === 0;

  return (
    <NodeViewWrapper
      className="whiteboard-wrapper"
      data-selected={selected || undefined}
    >
      <span className="whiteboard-label">白板</span>
      <div ref={wrapperRef}>
        {editing ? (
          <div
            className="whiteboard-editor"
            style={{ width, height: Math.max(height, 400) }}
          >
            {typeof window !== "undefined" && (
              <Excalidraw
                initialData={{
                  elements:
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    elements as any,
                  appState: {
                    viewBackgroundColor: "#ffffff",
                    ...appState,
                  },
                }}
                onChange={handleChange}
              />
            )}
          </div>
        ) : (
          <div
            className="whiteboard-preview"
            style={{ width, minHeight: 200 }}
            onClick={() => setEditing(true)}
            title="Click to edit"
          >
            {isEmpty ? (
              <span className="whiteboard-preview-empty">点击开始绘图</span>
            ) : svgPreview ? (
              <div
                className="whiteboard-preview-svg"
                ref={previewContainerRef}
              />
            ) : (
              <span className="whiteboard-preview-empty">Loading preview...</span>
            )}
          </div>
        )}
      </div>
    </NodeViewWrapper>
  );
}

// ---------------------------------------------------------------------------
// Extension
// ---------------------------------------------------------------------------

const WhiteboardBlock = Node.create({
  name: "whiteboard",
  group: "block",
  atom: true,
  selectable: true,
  draggable: true,

  addAttributes() {
    return {
      elements: { default: [] },
      appState: { default: {} },
      width: { default: 600 },
      height: { default: 400 },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="whiteboard"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes(HTMLAttributes, { "data-type": "whiteboard" }),
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(WhiteboardBlockView);
  },
});

export default WhiteboardBlock;
