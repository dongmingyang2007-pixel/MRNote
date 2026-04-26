"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Download,
  Loader2,
  Maximize2,
  RefreshCw,
  Search,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useTranslations } from "next-intl";
import PdfSelectionToolbar, {
  type SelectionContext,
} from "./pdf/PdfSelectionToolbar";
import QuoteToPageDialog from "./pdf/QuoteToPageDialog";
import DeckPickerDialog from "./pdf/DeckPickerDialog";
import HighlightEditDialog, {
  type HighlightDraft,
  type HighlightLink,
} from "./pdf/HighlightEditDialog";
import { apiGet, apiPost } from "@/lib/api";

interface PDFViewerProps {
  url: string;
  filename?: string;
  downloadUrl?: string;
  onPageChange?: (page: number) => void;
  /** Required to enable the AI selection toolbar. */
  notebookId?: string;
  /** Required to enable the AI selection toolbar (study/ask uses this). */
  studyAssetId?: string;
  /** Display title used in attributions / quotes. */
  documentTitle?: string;
  /** Stable id (data_item_id) so cross-window page-jump events know
   * whether they target this viewer. */
  dataItemId?: string;
}

interface PageRecord {
  pageNumber: number;
  width: number;
  height: number;
}

interface SearchHit {
  page: number;
  preview: string;
}

interface HighlightAnnotation {
  id: string;
  page: number;
  text: string;
  color: string;
  rects: Array<{ x: number; y: number; width: number; height: number }>;
  note?: string;
  links?: HighlightLink[];
}

const MIN_SCALE = 0.5;
const MAX_SCALE = 3.0;
const SCALE_STEP = 0.2;

// Lazy import so the heavy PDF.js bundle only ships in routes that use it.
type PdfApi = typeof import("pdfjs-dist");
type PdfDocument = Awaited<ReturnType<PdfApi["getDocument"]>["promise"]>;

let pdfApiPromise: Promise<PdfApi> | null = null;

async function loadPdfApi(): Promise<PdfApi> {
  if (pdfApiPromise) return pdfApiPromise;
  pdfApiPromise = (async () => {
    const mod = await import("pdfjs-dist");
    // Some bundlers (Next 16 webpack/turbopack) return the namespace under
    // `.default`; unwrap defensively so `pdfjs.GlobalWorkerOptions` is a
    // real object instead of an ES module namespace proxy.
    const pdfjs = (mod as unknown as { default?: PdfApi }).default ?? mod;
    // Serve the worker same-origin from /public/. Safari blocks cross-
    // origin Workers in many configurations (the dev server's CSP /
    // header set differs from Chrome's lax handling), and when pdf.js
    // can't spawn its real worker it falls back to a "fake worker" that
    // calls `Object.defineProperty` on undefined and crashes with
    // "Properties can only be defined on Objects". Same-origin worker
    // sidesteps the entire failure mode.
    pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
    return pdfjs;
  })();
  return pdfApiPromise;
}

export default function PDFViewer({
  url,
  filename,
  downloadUrl,
  onPageChange,
  notebookId,
  studyAssetId,
  documentTitle,
  dataItemId,
}: PDFViewerProps) {
  const t = useTranslations("console-notebooks");
  const [pdfDoc, setPdfDoc] = useState<PdfDocument | null>(null);
  const [pages, setPages] = useState<PageRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scale, setScale] = useState(1.0);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageInput, setPageInput] = useState("1");
  const [searchTerm, setSearchTerm] = useState("");
  const [searchHits, setSearchHits] = useState<SearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [selection, setSelection] = useState<SelectionContext | null>(null);
  const [quoteOpen, setQuoteOpen] = useState(false);
  const [quotePayload, setQuotePayload] = useState<{
    text: string;
    pageNumber: number | null;
  } | null>(null);
  const [deckPickerOpen, setDeckPickerOpen] = useState(false);
  const [deckPickerPayload, setDeckPickerPayload] = useState<{
    text: string;
    pageNumber: number | null;
  } | null>(null);
  const [highlights, setHighlights] = useState<HighlightAnnotation[]>([]);
  const [editingHighlight, setEditingHighlight] = useState<HighlightAnnotation | null>(null);

  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  // Track in-flight render tasks so we can cancel them on cleanup.
  const renderTasksRef = useRef<Map<number, { cancel: () => void }>>(new Map());
  // Mark of pages already rendered (so we don't re-render on every scroll).
  const renderedPagesRef = useRef<Set<number>>(new Set());

  // ---- Load the document --------------------------------------------------

  useEffect(() => {
    let cancelled = false;
    let activeDoc: PdfDocument | null = null;
    setLoading(true);
    setError(null);
    setPages([]);
    setPdfDoc(null);
    renderedPagesRef.current = new Set();

    void (async () => {
      try {
        const pdfjs = await loadPdfApi();
        const loadingTask = pdfjs.getDocument({
          url,
          withCredentials: true,
          // Same-origin cmaps so non-Latin (CJK) PDFs render in Safari
          // without needing a cross-origin fetch.
          cMapUrl: "/pdfjs-cmaps/",
          cMapPacked: true,
        });
        const doc = await loadingTask.promise;
        if (cancelled) {
          await doc.destroy();
          return;
        }
        activeDoc = doc;
        const pageRecords: PageRecord[] = [];
        for (let i = 1; i <= doc.numPages; i += 1) {
          const page = await doc.getPage(i);
          const viewport = page.getViewport({ scale: 1.0 });
          pageRecords.push({
            pageNumber: i,
            width: viewport.width,
            height: viewport.height,
          });
        }
        if (cancelled) {
          await doc.destroy();
          return;
        }
        setPdfDoc(doc);
        setPages(pageRecords);
        setCurrentPage(1);
        setPageInput("1");
        setLoading(false);
      } catch (err) {
        if (cancelled) return;
        setLoading(false);
        setError(
          err instanceof Error ? err.message : t("pdfViewer.loadFailed"),
        );
      }
    })();

    return () => {
      cancelled = true;
      renderTasksRef.current.forEach((task) => {
        try {
          task.cancel();
        } catch {
          /* ignore */
        }
      });
      renderTasksRef.current.clear();
      void activeDoc?.destroy();
    };
  }, [t, url]);

  // ---- Render pages on demand --------------------------------------------

  const renderPage = useCallback(
    async (pageNumber: number) => {
      if (!pdfDoc) return;
      if (renderedPagesRef.current.has(pageNumber)) return;
      const wrapper = pageRefs.current.get(pageNumber);
      if (!wrapper) return;
      const canvas = wrapper.querySelector<HTMLCanvasElement>(
        "canvas[data-pdf-page]",
      );
      const textLayer = wrapper.querySelector<HTMLDivElement>(
        "div[data-pdf-text-layer]",
      );
      if (!canvas) return;

      const page = await pdfDoc.getPage(pageNumber);
      const dpr = Math.min(typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1, 2);
      const viewport = page.getViewport({ scale: scale * dpr });
      const cssViewport = page.getViewport({ scale });
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.style.width = `${cssViewport.width}px`;
      canvas.style.height = `${cssViewport.height}px`;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const renderTask = page.render({
        canvas,
        canvasContext: ctx,
        viewport,
      });
      renderTasksRef.current.set(pageNumber, renderTask);
      try {
        await renderTask.promise;
        renderedPagesRef.current.add(pageNumber);

        // Render the text layer for selection / search. Clear via
        // replaceChildren() rather than innerHTML to avoid XSS lint flags
        // (PDF.js writes safe DOM nodes — replaceChildren is equivalent).
        if (textLayer) {
          textLayer.replaceChildren();
          textLayer.style.width = `${cssViewport.width}px`;
          textLayer.style.height = `${cssViewport.height}px`;
          const textContent = await page.getTextContent();
          const pdfjs = await loadPdfApi();
          // pdfjs-dist v5 replaced `renderTextLayer()` with the
          // `TextLayer` class. Construct then render.
          const textLayerInstance = new pdfjs.TextLayer({
            textContentSource: textContent,
            container: textLayer,
            viewport: cssViewport,
          });
          await textLayerInstance.render();
        }
      } catch (err) {
        // Cancelled or failed render — ignore "Rendering cancelled" noise.
        const message = err instanceof Error ? err.message : "";
        if (!/cancel/i.test(message)) {
          console.warn("[pdf] render error", err);
        }
      } finally {
        renderTasksRef.current.delete(pageNumber);
      }
    },
    [pdfDoc, scale],
  );

  // Lazy render: observe each page wrapper and render when it enters view.
  useEffect(() => {
    if (!pdfDoc || pages.length === 0) return;
    const root = scrollContainerRef.current;
    if (!root) return;

    // Re-render all visible pages when scale changes by busting cache.
    renderedPagesRef.current = new Set();
    pageRefs.current.forEach((wrapper) => {
      const canvas = wrapper.querySelector<HTMLCanvasElement>(
        "canvas[data-pdf-page]",
      );
      if (canvas) {
        canvas.width = 0;
        canvas.height = 0;
      }
    });

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const pageAttr = entry.target.getAttribute("data-page-number");
          if (!pageAttr) return;
          const pageNumber = Number(pageAttr);
          if (entry.isIntersecting) {
            void renderPage(pageNumber);
            // Update current page based on which page is most visible.
            if (entry.intersectionRatio > 0.5) {
              setCurrentPage(pageNumber);
              setPageInput(String(pageNumber));
              onPageChange?.(pageNumber);
            }
          }
        });
      },
      { root, threshold: [0, 0.25, 0.5, 0.75] },
    );

    pageRefs.current.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [onPageChange, pages, pdfDoc, renderPage, scale]);

  // ---- Navigation --------------------------------------------------------

  const goToPage = useCallback(
    (pageNumber: number) => {
      const clamped = Math.max(1, Math.min(pages.length, pageNumber));
      const target = pageRefs.current.get(clamped);
      if (target && scrollContainerRef.current) {
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    },
    [pages.length],
  );

  const handlePageInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    setPageInput(event.target.value);
  };

  const handlePageInputCommit = () => {
    const parsed = Number(pageInput);
    if (Number.isFinite(parsed) && parsed >= 1) {
      goToPage(parsed);
    } else {
      setPageInput(String(currentPage));
    }
  };

  // ---- Cross-window page-jump --------------------------------------------
  // Other windows (study assistant, AI panel) can dispatch a custom event
  // with `{dataItemId, pageNumber}` to scroll this viewer to a citation.
  // If the event arrives before pages have loaded (common when the user
  // clicks a citation while the document tab is mounting), the request is
  // queued and replayed once `pages` is populated.

  const pendingJumpRef = useRef<number | null>(null);

  useEffect(() => {
    if (!dataItemId) return;
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{
        dataItemId?: string;
        pageNumber?: number;
      }>).detail;
      if (!detail) return;
      if (detail.dataItemId && detail.dataItemId !== dataItemId) return;
      if (typeof detail.pageNumber !== "number" || detail.pageNumber <= 0) return;
      if (pages.length === 0) {
        pendingJumpRef.current = detail.pageNumber;
      } else {
        goToPage(detail.pageNumber);
      }
    };
    window.addEventListener("mrnote:open-pdf-page", handler);
    return () => window.removeEventListener("mrnote:open-pdf-page", handler);
  }, [dataItemId, goToPage, pages.length]);

  useEffect(() => {
    if (pages.length > 0 && pendingJumpRef.current !== null) {
      const target = pendingJumpRef.current;
      pendingJumpRef.current = null;
      goToPage(target);
    }
  }, [goToPage, pages.length]);

  // ---- Selection toolbar -------------------------------------------------
  // Listen for text selections inside the PDF text-layer and surface the
  // floating toolbar. Only enabled when host provides AI context.

  const selectionEnabled = !!notebookId && !!studyAssetId;

  useEffect(() => {
    if (!selectionEnabled) return;
    const handle = () => {
      const sel = typeof window !== "undefined" ? window.getSelection() : null;
      if (!sel || sel.isCollapsed) {
        setSelection(null);
        return;
      }
      const range = sel.rangeCount > 0 ? sel.getRangeAt(0) : null;
      if (!range) {
        setSelection(null);
        return;
      }
      // Only show toolbar if the selection lives inside our text layer.
      const node = range.commonAncestorContainer;
      const el =
        node.nodeType === Node.ELEMENT_NODE
          ? (node as Element)
          : node.parentElement;
      const layer = el?.closest("[data-pdf-text-layer]");
      const pageWrapper = layer?.closest(".pdf-viewer__page");
      if (!layer || !pageWrapper) {
        setSelection(null);
        return;
      }
      const text = sel.toString().trim();
      if (!text) {
        setSelection(null);
        return;
      }
      const rect = range.getBoundingClientRect();
      const pageAttr = pageWrapper.getAttribute("data-page-number");
      // Convert each client rect into page-wrapper coordinates so highlight
      // overlays can be re-anchored across zooms by storing them as %.
      const wrapperRect = pageWrapper.getBoundingClientRect();
      const wrapperWidth = wrapperRect.width || 1;
      const wrapperHeight = wrapperRect.height || 1;
      const clientRects = Array.from(range.getClientRects());
      const rects = clientRects
        .filter((r) => r.width > 0 && r.height > 0)
        .map((r) => ({
          x: ((r.left - wrapperRect.left) / wrapperWidth) * 100,
          y: ((r.top - wrapperRect.top) / wrapperHeight) * 100,
          width: (r.width / wrapperWidth) * 100,
          height: (r.height / wrapperHeight) * 100,
        }));
      setSelection({
        text,
        rect: {
          top: rect.top,
          left: rect.left,
          width: rect.width,
          height: rect.height,
        },
        pageNumber: pageAttr ? Number(pageAttr) : null,
        rects,
      });
    };
    document.addEventListener("selectionchange", handle);
    return () => document.removeEventListener("selectionchange", handle);
  }, [selectionEnabled]);

  const dismissSelection = useCallback(() => {
    setSelection(null);
    if (typeof window !== "undefined") {
      window.getSelection()?.removeAllRanges();
    }
  }, []);

  const handleQuoteRequest = useCallback(
    (text: string, pageNumber: number | null) => {
      setQuotePayload({ text, pageNumber });
      setQuoteOpen(true);
    },
    [],
  );

  const handleFlashcardsRequest = useCallback(
    (text: string, pageNumber: number | null) => {
      setDeckPickerPayload({ text, pageNumber });
      setDeckPickerOpen(true);
    },
    [],
  );

  // ---- Highlights -------------------------------------------------------

  const loadHighlights = useCallback(async () => {
    if (!dataItemId) return;
    try {
      const data = await apiGet<{
        items: Array<{
          id: string;
          type: string;
          payload_json: Record<string, unknown>;
        }>;
      }>(
        `/api/v1/data-items/${dataItemId}/annotations?type=pdf_highlight`,
      );
      const items: HighlightAnnotation[] = (data.items || [])
        .map((item) => {
          const payload = item.payload_json || {};
          const page = Number(payload.page) || 0;
          const rects = Array.isArray(payload.rects)
            ? (payload.rects as Array<{
                x: number;
                y: number;
                width: number;
                height: number;
              }>)
            : [];
          return {
            id: item.id,
            page,
            text: typeof payload.text === "string" ? payload.text : "",
            color:
              typeof payload.color === "string"
                ? payload.color
                : "rgba(252, 211, 77, 0.45)",
            rects,
            note: typeof payload.note === "string" ? payload.note : undefined,
            links: Array.isArray(payload.links)
              ? (payload.links as HighlightLink[]).filter(
                  (l) =>
                    l &&
                    typeof l === "object" &&
                    typeof l.id === "string" &&
                    (l.kind === "page" || l.kind === "memory"),
                )
              : [],
          };
        })
        .filter((h) => h.page > 0 && h.rects.length > 0);
      setHighlights(items);
    } catch {
      /* ignore — highlights are optional */
    }
  }, [dataItemId]);

  useEffect(() => {
    void loadHighlights();
  }, [loadHighlights]);

  const handleHighlightRequest = useCallback(
    async (
      text: string,
      pageNumber: number | null,
      rects: Array<{ x: number; y: number; width: number; height: number }>,
    ) => {
      if (!dataItemId || pageNumber == null || rects.length === 0) return;
      const color = "rgba(252, 211, 77, 0.45)";
      const result = await apiPost<{
        annotation: { id: string };
      }>(`/api/v1/data-items/${dataItemId}/annotations`, {
        type: "pdf_highlight",
        payload_json: {
          page: pageNumber,
          text,
          color,
          rects,
        },
      });
      setHighlights((prev) => [
        ...prev,
        {
          id: result.annotation.id,
          page: pageNumber,
          text,
          color,
          rects,
        },
      ]);
    },
    [dataItemId],
  );

  const handleHighlightSaved = useCallback(
    (next: HighlightDraft) => {
      setHighlights((prev) =>
        prev.map((h) =>
          h.id === next.id
            ? {
                ...h,
                color: next.color,
                note: next.note,
                links: next.links || [],
              }
            : h,
        ),
      );
      setEditingHighlight(null);
    },
    [],
  );

  const handleHighlightDeleted = useCallback((annotationId: string) => {
    setHighlights((prev) => prev.filter((h) => h.id !== annotationId));
    setEditingHighlight(null);
  }, []);

  // ---- Zoom --------------------------------------------------------------

  const zoomIn = () => setScale((s) => Math.min(MAX_SCALE, +(s + SCALE_STEP).toFixed(2)));
  const zoomOut = () => setScale((s) => Math.max(MIN_SCALE, +(s - SCALE_STEP).toFixed(2)));
  const fitWidth = useCallback(() => {
    const root = scrollContainerRef.current;
    if (!root || pages.length === 0) return;
    // Use the first page as the width benchmark; assumes uniform width PDFs.
    const firstPage = pages[0];
    const padding = 40; // matches CSS padding inside the page list
    const target = (root.clientWidth - padding) / firstPage.width;
    setScale(Math.max(MIN_SCALE, Math.min(MAX_SCALE, +target.toFixed(2))));
  }, [pages]);

  // ---- Search ------------------------------------------------------------

  const runSearch = useCallback(async () => {
    if (!pdfDoc || !searchTerm.trim()) {
      setSearchHits([]);
      return;
    }
    setSearching(true);
    const term = searchTerm.toLowerCase();
    const hits: SearchHit[] = [];
    try {
      for (let i = 1; i <= pdfDoc.numPages; i += 1) {
        const page = await pdfDoc.getPage(i);
        const content = await page.getTextContent();
        const fullText = content.items
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          .map((item: any) => ("str" in item ? item.str : ""))
          .join(" ");
        const lower = fullText.toLowerCase();
        const idx = lower.indexOf(term);
        if (idx !== -1) {
          const start = Math.max(0, idx - 30);
          const end = Math.min(fullText.length, idx + term.length + 60);
          hits.push({ page: i, preview: fullText.slice(start, end) });
        }
      }
      setSearchHits(hits);
    } finally {
      setSearching(false);
    }
  }, [pdfDoc, searchTerm]);

  const totalPagesLabel = useMemo(
    () => t("pdfViewer.pageOf", { current: currentPage, total: pages.length || 1 }),
    [currentPage, pages.length, t],
  );

  // ---- Render ------------------------------------------------------------

  if (error) {
    return (
      <div className="pdf-viewer pdf-viewer--center">
        <AlertCircle size={28} />
        <strong>{t("pdfViewer.loadFailed")}</strong>
        <span>{error}</span>
        <button type="button" onClick={() => window.location.reload()}>
          <RefreshCw size={14} />
          {t("pdfViewer.retry")}
        </button>
      </div>
    );
  }

  return (
    <div className="pdf-viewer">
      <header className="pdf-viewer__toolbar">
        <div className="pdf-viewer__nav">
          <button
            type="button"
            onClick={() => goToPage(currentPage - 1)}
            disabled={currentPage <= 1 || loading}
            title={t("pdfViewer.prev")}
            aria-label={t("pdfViewer.prev")}
          >
            <ChevronLeft size={14} />
          </button>
          <input
            type="number"
            min={1}
            max={pages.length}
            value={pageInput}
            onChange={handlePageInputChange}
            onBlur={handlePageInputCommit}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handlePageInputCommit();
              }
            }}
            disabled={loading}
            aria-label={t("pdfViewer.pageOf", {
              current: currentPage,
              total: pages.length,
            })}
          />
          <span>{totalPagesLabel}</span>
          <button
            type="button"
            onClick={() => goToPage(currentPage + 1)}
            disabled={currentPage >= pages.length || loading}
            title={t("pdfViewer.next")}
            aria-label={t("pdfViewer.next")}
          >
            <ChevronRight size={14} />
          </button>
        </div>

        <div className="pdf-viewer__zoom">
          <button
            type="button"
            onClick={zoomOut}
            disabled={loading || scale <= MIN_SCALE}
            title={t("pdfViewer.zoomOut")}
            aria-label={t("pdfViewer.zoomOut")}
          >
            <ZoomOut size={14} />
          </button>
          <span>{Math.round(scale * 100)}%</span>
          <button
            type="button"
            onClick={zoomIn}
            disabled={loading || scale >= MAX_SCALE}
            title={t("pdfViewer.zoomIn")}
            aria-label={t("pdfViewer.zoomIn")}
          >
            <ZoomIn size={14} />
          </button>
          <button
            type="button"
            onClick={fitWidth}
            disabled={loading}
            title={t("pdfViewer.fitWidth")}
            aria-label={t("pdfViewer.fitWidth")}
          >
            <Maximize2 size={14} />
          </button>
        </div>

        <div className="pdf-viewer__search">
          <Search size={14} />
          <input
            type="search"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void runSearch();
              }
            }}
            placeholder={t("pdfViewer.searchPlaceholder")}
            disabled={loading}
          />
        </div>

        {downloadUrl ? (
          <a
            className="pdf-viewer__download"
            href={downloadUrl}
            download={filename}
            title={t("references.download")}
          >
            <Download size={14} />
          </a>
        ) : null}
      </header>

      <div className="pdf-viewer__body">
        {searchHits.length > 0 || searching ? (
          <aside className="pdf-viewer__rail">
            <strong>{t("pdfViewer.searchResults")}</strong>
            {searching ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <ul>
                {searchHits.map((hit) => (
                  <li key={`${hit.page}-${hit.preview.slice(0, 24)}`}>
                    <button type="button" onClick={() => goToPage(hit.page)}>
                      <em>p.{hit.page}</em>
                      <span>{hit.preview}</span>
                    </button>
                  </li>
                ))}
                {searchHits.length === 0 ? (
                  <li className="pdf-viewer__empty">
                    {t("pdfViewer.searchEmpty")}
                  </li>
                ) : null}
              </ul>
            )}
          </aside>
        ) : null}

        <div className="pdf-viewer__pages" ref={scrollContainerRef}>
          {loading ? (
            <div className="pdf-viewer__loading">
              <Loader2 size={26} className="animate-spin" />
              <span>{t("pdfViewer.loading")}</span>
            </div>
          ) : (
            pages.map((page) => {
              const pageHighlights = highlights.filter(
                (h) => h.page === page.pageNumber,
              );
              return (
                <div
                  key={page.pageNumber}
                  ref={(el) => {
                    if (el) pageRefs.current.set(page.pageNumber, el);
                    else pageRefs.current.delete(page.pageNumber);
                  }}
                  data-page-number={page.pageNumber}
                  className="pdf-viewer__page"
                  style={{
                    width: page.width * scale,
                    height: page.height * scale,
                  }}
                >
                  <canvas data-pdf-page />
                  <div
                    data-pdf-highlight-layer
                    className="pdf-viewer__highlight-layer"
                  >
                    {pageHighlights.map((h) =>
                      h.rects.map((r, idx) => (
                        <button
                          key={`${h.id}-${idx}`}
                          type="button"
                          className="pdf-viewer__highlight-rect"
                          style={{
                            left: `${r.x}%`,
                            top: `${r.y}%`,
                            width: `${r.width}%`,
                            height: `${r.height}%`,
                            background: h.color,
                          }}
                          title={
                            h.note ||
                            (h.text.length > 80
                              ? `${h.text.slice(0, 80)}…`
                              : h.text)
                          }
                          onClick={(e) => {
                            e.stopPropagation();
                            setEditingHighlight(h);
                          }}
                        />
                      )),
                    )}
                  </div>
                  <div
                    data-pdf-text-layer
                    className="pdf-viewer__text-layer"
                  />
                </div>
              );
            })
          )}
        </div>
      </div>

      {selectionEnabled && notebookId && studyAssetId ? (
        <>
          <PdfSelectionToolbar
            selection={selection}
            notebookId={notebookId}
            studyAssetId={studyAssetId}
            documentTitle={documentTitle || filename}
            onRequestQuoteToPage={handleQuoteRequest}
            onRequestFlashcards={handleFlashcardsRequest}
            onRequestHighlight={handleHighlightRequest}
            onDismiss={dismissSelection}
          />
          <QuoteToPageDialog
            open={quoteOpen}
            notebookId={notebookId}
            text={quotePayload?.text || ""}
            pageNumber={quotePayload?.pageNumber ?? null}
            documentTitle={documentTitle || filename}
            onClose={() => setQuoteOpen(false)}
          />
          <DeckPickerDialog
            open={deckPickerOpen}
            notebookId={notebookId}
            text={deckPickerPayload?.text || ""}
            pageNumber={deckPickerPayload?.pageNumber ?? null}
            documentTitle={documentTitle || filename}
            onClose={() => setDeckPickerOpen(false)}
          />
          <HighlightEditDialog
            open={!!editingHighlight}
            notebookId={notebookId}
            highlight={editingHighlight}
            onClose={() => setEditingHighlight(null)}
            onSaved={handleHighlightSaved}
            onDeleted={handleHighlightDeleted}
          />
        </>
      ) : null}
    </div>
  );
}
