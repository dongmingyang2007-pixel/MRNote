"use client";

import { useCallback, useMemo } from "react";
import { Rnd } from "react-rnd";
import {
  Minus,
  Square,
  Maximize2,
  X,
  FileText,
  MessageSquare,
  FileUp,
  Brain,
  BookOpen,
} from "lucide-react";
import { useWindowManager, useWindows } from "./WindowManager";
import type { WindowState, WindowType } from "./WindowManager";

// ---------------------------------------------------------------------------
// Icon map
// ---------------------------------------------------------------------------

const WINDOW_ICONS: Record<WindowType, typeof FileText> = {
  note: FileText,
  chat: MessageSquare,
  file: FileUp,
  memory: Brain,
  study: BookOpen,
};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface WindowProps {
  windowState: WindowState;
  children: React.ReactNode;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Window({ windowState, children }: WindowProps) {
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

  // Compute position and size for maximized vs normal
  const position = maximized ? { x: 0, y: 0 } : { x, y };
  const size = maximized
    ? { width: "100%", height: "100%" }
    : { width, height };

  const rndStyle = useMemo(
    () => ({ zIndex, display: "flex" }),
    [zIndex],
  );

  return (
    <Rnd
      style={rndStyle}
      size={size}
      position={position}
      dragHandleClassName="wm-titlebar"
      bounds="parent"
      minWidth={200}
      minHeight={150}
      disableDragging={maximized}
      enableResizing={!maximized}
      onDragStop={(_e, d) => {
        moveWindow(id, d.x, d.y);
      }}
      onResizeStop={(_e, _dir, ref, _delta, pos) => {
        resizeWindow(id, ref.offsetWidth, ref.offsetHeight);
        moveWindow(id, pos.x, pos.y);
      }}
      onMouseDown={handleFocus}
    >
      <div
        className={`wm-window${isFocused ? " wm-window--focused" : ""}`}
        style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column" }}
        onMouseDown={handleFocus}
      >
        {/* Title bar */}
        <div className="wm-titlebar">
          <div className="wm-titlebar-title">
            <Icon size={16} className="wm-titlebar-icon" />
            <span>{displayTitle}</span>
          </div>
          <div className="wm-titlebar-controls">
            <button
              type="button"
              className="wm-titlebar-btn"
              onClick={handleMinimize}
              title="Minimize"
            >
              <Minus size={14} />
            </button>
            <button
              type="button"
              className="wm-titlebar-btn"
              onClick={handleMaximizeToggle}
              title={maximized ? "Restore" : "Maximize"}
            >
              {maximized ? <Maximize2 size={14} /> : <Square size={14} />}
            </button>
            <button
              type="button"
              className="wm-titlebar-btn wm-titlebar-btn--close"
              onClick={handleClose}
              title="Close"
            >
              <X size={14} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="wm-body">{children}</div>
      </div>
    </Rnd>
  );
}
