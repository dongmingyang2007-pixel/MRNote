"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslations } from "next-intl";
import { Rnd } from "react-rnd";
import {
  Minus,
  Square,
  Maximize2,
  X,
  FileText,
  Sparkles,
  FileUp,
  Brain,
  Network,
  BookOpen,
  Bell,
  Search,
} from "lucide-react";
import { useWindowManager, useWindows } from "./WindowManager";
import type { WindowState, WindowType } from "./WindowManager";
import { clampWindowPosition } from "./window-bounds";

// ---------------------------------------------------------------------------
// Icon map
// ---------------------------------------------------------------------------

const WINDOW_ICONS: Record<WindowType, typeof FileText> = {
  note: FileText,
  guest_note: FileText,
  ai_panel: Sparkles,
  file: FileUp,
  memory: Brain,
  memory_graph: Network,
  study: BookOpen,
  digest: Bell,
  search: Search,
};

// Per-type minimum dimensions — prevents users from shrinking a window
// below a usable size. Fallback to the generic 200x150 for types that
// don't declare their own.
const MIN_SIZES: Partial<
  Record<WindowType, { width: number; height: number }>
> = {
  memory_graph: { width: 600, height: 440 },
};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface WindowProps {
  windowState: WindowState;
  children: React.ReactNode;
  titlebarExtras?: React.ReactNode;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Window({
  windowState,
  children,
  titlebarExtras,
}: WindowProps) {
  const t = useTranslations("console-notebooks");
  const shellRef = useRef<HTMLDivElement>(null);
  const {
    closeWindow,
    minimizeWindow,
    maximizeWindow,
    restoreWindow,
    focusWindow,
    moveWindow,
    resizeWindow,
  } = useWindowManager();

  const allWindows = useWindows();
  const { id, type, title, x, y, width, height, zIndex, maximized } =
    windowState;

  const maxZ = allWindows.reduce((max, w) => Math.max(max, w.zIndex), 0);
  const isFocused = zIndex >= maxZ && maxZ > 0;

  const Icon = WINDOW_ICONS[type];
  const displayTitle = title.length > 30 ? title.slice(0, 30) + "..." : title;

  const handleFocus = useCallback(() => {
    focusWindow(id);
  }, [focusWindow, id]);

  const handleClose = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      closeWindow(id);
    },
    [closeWindow, id],
  );

  const handleMinimize = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      minimizeWindow(id);
    },
    [minimizeWindow, id],
  );

  const handleMaximizeToggle = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      if (maximized) {
        restoreWindow(id);
      } else {
        maximizeWindow(id);
      }
    },
    [maximized, maximizeWindow, restoreWindow, id],
  );

  // U-18 — on very small viewports the default 780px note window overflows
  // the canvas; squeeze the rendered width down to leave a 20px gutter.
  // The stored width stays unchanged; this only affects the current render.
  const [viewportWidth, setViewportWidth] = useState<number>(() =>
    typeof window === "undefined" ? 1024 : window.innerWidth,
  );
  useEffect(() => {
    const onResize = () => setViewportWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const effectiveWidth =
    viewportWidth < 640 ? Math.min(width, viewportWidth - 40) : width;

  // Compute position and size for maximized vs normal
  const position = maximized ? { x: 0, y: 0 } : { x, y };
  const size = maximized
    ? { width: "100%", height: "100%" }
    : { width: effectiveWidth, height };

  const rndStyle = useMemo(() => ({ zIndex, display: "flex" }), [zIndex]);

  const getCanvasSize = useCallback((target?: EventTarget | null) => {
    const eventCanvas =
      target instanceof Element
        ? (target.closest(".wm-canvas") as HTMLElement | null)
        : null;
    const canvas =
      eventCanvas ??
      (shellRef.current?.closest(".wm-canvas") as HTMLElement | null);
    return {
      width: canvas?.clientWidth ?? window.innerWidth,
      height: canvas?.clientHeight ?? window.innerHeight,
      canvas,
    };
  }, []);

  const clampAndMove = useCallback(
    ({
      nextX,
      nextY,
      nextWidth = effectiveWidth,
      target,
    }: {
      nextX: number;
      nextY: number;
      nextWidth?: number;
      target?: EventTarget | null;
    }) => {
      if (maximized) return;
      const canvas = getCanvasSize(target);
      const next = clampWindowPosition({
        x: nextX,
        y: nextY,
        width: nextWidth,
        canvasWidth: canvas.width,
        canvasHeight: canvas.height,
      });
      if (next.x !== x || next.y !== y) {
        moveWindow(id, next.x, next.y);
      }
    },
    [effectiveWidth, getCanvasSize, id, maximized, moveWindow, x, y],
  );

  useLayoutEffect(() => {
    clampAndMove({ nextX: x, nextY: y });
  }, [clampAndMove, x, y]);

  useEffect(() => {
    const { canvas } = getCanvasSize();
    if (!canvas || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      clampAndMove({ nextX: x, nextY: y });
    });
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [clampAndMove, getCanvasSize, x, y]);

  return (
    <Rnd
      style={rndStyle}
      size={size}
      position={position}
      dragHandleClassName="wm-titlebar"
      minWidth={MIN_SIZES[windowState.type]?.width ?? 200}
      minHeight={MIN_SIZES[windowState.type]?.height ?? 150}
      disableDragging={maximized}
      enableResizing={!maximized}
      onDrag={(_e, d) => {
        clampAndMove({
          nextX: d.x,
          nextY: d.y,
          target: _e?.target,
        });
      }}
      onDragStop={(_e, d) => {
        clampAndMove({
          nextX: d.x,
          nextY: d.y,
          target: _e?.target,
        });
      }}
      onResizeStop={(_e, _dir, ref, _delta, pos) => {
        const next = clampWindowPosition({
          x: pos.x,
          y: pos.y,
          width: ref.offsetWidth,
          canvasWidth: getCanvasSize(_e?.target).width,
          canvasHeight: getCanvasSize(_e?.target).height,
        });
        resizeWindow(id, ref.offsetWidth, ref.offsetHeight);
        moveWindow(id, next.x, next.y);
      }}
      onMouseDown={handleFocus}
    >
      <div
        className={`wm-window${isFocused ? " wm-window--focused" : ""}`}
        ref={shellRef}
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
        }}
        onMouseDown={handleFocus}
        data-focused={isFocused ? "true" : "false"}
      >
        {/* Title bar */}
        <div className="wm-titlebar">
          <div className="wm-titlebar-title">
            <Icon size={14} className="wm-titlebar-icon" />
            <span>{displayTitle}</span>
          </div>
          <div className="wm-titlebar-controls">
            {titlebarExtras}
            <button
              type="button"
              className="wm-titlebar-btn"
              onClick={handleMinimize}
              title={t("window.minimize")}
              aria-label={t("window.minimize")}
            >
              <Minus size={12} />
            </button>
            <button
              type="button"
              className="wm-titlebar-btn"
              onClick={handleMaximizeToggle}
              title={maximized ? t("window.restore") : t("window.maximize")}
              aria-label={
                maximized ? t("window.restore") : t("window.maximize")
              }
            >
              {maximized ? <Maximize2 size={12} /> : <Square size={12} />}
            </button>
            <button
              type="button"
              className="wm-titlebar-btn wm-titlebar-btn--close"
              onClick={handleClose}
              title={t("window.close")}
              aria-label={t("window.close")}
            >
              <X size={12} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="wm-body">{children}</div>
      </div>
    </Rnd>
  );
}
