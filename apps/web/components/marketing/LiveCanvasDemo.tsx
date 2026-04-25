"use client";

import { useState, useRef, useEffect } from "react";
import { Rnd } from "react-rnd";
import {
  FileText,
  GraduationCap,
  MemoryStick,
  MousePointer2,
  Network,
  Search,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import {
  AiPanelContent,
  MarketingProductWindow,
  SearchPanelContent,
  StudyPanelContent,
  WorkspaceEditorContent,
} from "./ProductPreviews";

interface WindowSpec {
  id: string;
  x: number;
  y: number;
  width: number;
  kind: "editor" | "ai" | "graph" | "search" | "study";
}

// Starting layout is tuned for a 1100x520 canvas. We scale down
// proportionally when the container is narrower (mobile).
const INITIAL_LAYOUT: readonly WindowSpec[] = [
  { id: "editor", x: 38, y: 56, width: 440, kind: "editor" },
  { id: "ai", x: 718, y: 52, width: 332, kind: "ai" },
  { id: "graph", x: 490, y: 248, width: 386, kind: "graph" },
  { id: "search", x: 142, y: 322, width: 326, kind: "search" },
] as const;

function label(locale: string, zh: string, en: string) {
  return locale === "en" ? en : zh;
}

/**
 * Below-the-fold interactive demo — the "it's really a canvas" proof.
 * Each mock is wrapped in react-rnd; drag-only (no resize). Position
 * lives in component state — intentionally not persisted, a fresh
 * visitor should see the same arrangement every load. Windows come
 * forward on click via a monotonic z-index counter.
 *
 * The mocks render as non-decorative (role="group" + aria-label) here
 * because the user is interacting with them — not just looking.
 */
export default function LiveCanvasDemo() {
  const t = useTranslations("marketing");
  const locale = useLocale();
  const [positions, setPositions] = useState<
    Record<string, { x: number; y: number }>
  >(Object.fromEntries(INITIAL_LAYOUT.map((w) => [w.id, { x: w.x, y: w.y }])));
  const [order, setOrder] = useState<string[]>(INITIAL_LAYOUT.map((w) => w.id));

  // Scale positions for narrow viewports. Measure the container
  // width once on mount + on window resize.
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [scale, setScale] = useState(1);
  useEffect(() => {
    function update() {
      const el = containerRef.current;
      if (!el) return;
      const w = el.offsetWidth;
      setScale(Math.min(1, w / 1100));
    }
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  function bringForward(id: string) {
    setOrder((prev) => [...prev.filter((x) => x !== id), id]);
  }

  function renderWindow(spec: WindowSpec) {
    if (spec.kind === "editor") {
      return (
        <MarketingProductWindow
          title={label(locale, "页面 · 新版编辑器", "Page · Editor redesign")}
          meta={label(locale, "auto-saved", "auto-saved")}
          icon={<FileText size={14} />}
        >
          <WorkspaceEditorContent />
        </MarketingProductWindow>
      );
    }
    if (spec.kind === "ai") {
      return (
        <MarketingProductWindow
          title={label(locale, "助手", "Assistant")}
          meta={label(locale, "4 条来源", "4 sources")}
          icon={<MemoryStick size={14} />}
        >
          <AiPanelContent />
        </MarketingProductWindow>
      );
    }
    if (spec.kind === "search") {
      return (
        <MarketingProductWindow
          title={label(locale, "统一搜索", "Unified search")}
          meta={label(locale, "pages · memory", "pages · memory")}
          icon={<Search size={14} />}
        >
          <SearchPanelContent />
        </MarketingProductWindow>
      );
    }
    if (spec.kind === "study") {
      return (
        <MarketingProductWindow
          title={label(locale, "学习素材", "Study material")}
          meta={label(locale, "42 段摘录", "42 excerpts")}
          icon={<GraduationCap size={14} />}
        >
          <StudyPanelContent />
        </MarketingProductWindow>
      );
    }
    return (
      <MarketingProductWindow
        title="Memory Graph"
        meta={label(locale, "32 条线索", "32 threads")}
        icon={<Network size={14} />}
      >
        <div className="marketing-product-window__graph-slot">
          <svg
            className="marketing-product-graph-svg"
            viewBox="0 0 100 78"
            role="img"
            aria-label={label(locale, "记忆图谱窗口", "Memory graph window")}
          >
            <line
              x1="50"
              y1="24"
              x2="30"
              y2="42"
              className="marketing-product-graph-edge is-evidence"
            />
            <line
              x1="50"
              y1="24"
              x2="68"
              y2="45"
              className="marketing-product-graph-edge is-summary"
            />
            <line
              x1="30"
              y1="42"
              x2="45"
              y2="62"
              className="marketing-product-graph-edge is-related"
            />
            <line
              x1="68"
              y1="45"
              x2="45"
              y2="62"
              className="marketing-product-graph-edge is-prerequisite"
            />
            {[
              [50, 24, "Workspace"],
              [30, 42, "Memory"],
              [68, 45, "Evidence"],
              [45, 62, "Study"],
            ].map(([x, y, name]) => (
              <g
                key={name}
                className={`marketing-product-graph-node${name === "Workspace" ? " is-selected" : " is-concept"}`}
                transform={`translate(${x} ${y})`}
              >
                <circle r={name === "Workspace" ? 6.4 : 4.8} />
                <text y={name === "Workspace" ? 15 : 12}>{name}</text>
              </g>
            ))}
          </svg>
        </div>
      </MarketingProductWindow>
    );
  }

  return (
    <>
      <div className="marketing-live-canvas" ref={containerRef}>
        <div className="marketing-live-canvas__hint">
          <MousePointer2 size={14} strokeWidth={2} />
          {t("screenshot.canvas.hint")}
        </div>
        {INITIAL_LAYOUT.map((w) => {
          const pos = positions[w.id];
          const z = order.indexOf(w.id) + 1;
          return (
            <Rnd
              key={w.id}
              size={{ width: w.width * scale, height: "auto" }}
              position={{ x: pos.x * scale, y: pos.y * scale }}
              onDragStart={() => bringForward(w.id)}
              onDragStop={(_, d) => {
                setPositions((p) => ({
                  ...p,
                  [w.id]: { x: d.x / scale, y: d.y / scale },
                }));
              }}
              bounds="parent"
              enableResizing={false}
              dragHandleClassName="marketing-product-window__bar"
              style={{ zIndex: z, cursor: "grab" }}
            >
              {renderWindow(w)}
            </Rnd>
          );
        })}
      </div>
      <div className="marketing-live-canvas__mobile-fallback">
        {INITIAL_LAYOUT.map((w) => (
          <div key={w.id}>{renderWindow(w)}</div>
        ))}
      </div>
    </>
  );
}
