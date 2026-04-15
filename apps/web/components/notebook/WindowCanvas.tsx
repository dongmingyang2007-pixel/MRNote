"use client";

import { useRef } from "react";
import { Layers } from "lucide-react";
import { useWindows } from "./WindowManager";
import Window from "./Window";
import NoteWindow from "./contents/NoteWindow";
import ChatWindow from "./contents/ChatWindow";
import FileWindow from "./contents/FileWindow";
import MemoryWindow from "./contents/MemoryWindow";
import StudyWindow from "./contents/StudyWindow";
import type { WindowState } from "./WindowManager";

// ---------------------------------------------------------------------------
// Window content router
// ---------------------------------------------------------------------------

function WindowContent({ windowState }: { windowState: WindowState }) {
  switch (windowState.type) {
    case "note":
      return (
        <NoteWindow
          pageId={windowState.meta.pageId || ""}
        />
      );

    case "chat":
      return (
        <ChatWindow
          notebookId={windowState.meta.notebookId || ""}
          pageId={windowState.meta.pageId}
        />
      );

    case "file":
      return (
        <FileWindow
          url={windowState.meta.url}
          mimeType={windowState.meta.mimeType}
          filename={windowState.meta.filename}
        />
      );

    case "memory":
      return (
        <MemoryWindow
          notebookId={windowState.meta.notebookId || ""}
          initialPageId={windowState.meta.pageId}
        />
      );

    case "study":
      return (
        <StudyWindow notebookId={windowState.meta.notebookId || ""} />
      );

    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState() {
  return (
    <div className="wm-empty-state">
      <Layers size={48} strokeWidth={1.2} className="wm-empty-state-icon" />
      <span className="wm-empty-state-text">
        打开侧栏中的页面开始工作
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Canvas
// ---------------------------------------------------------------------------

export default function WindowCanvas() {
  const canvasRef = useRef<HTMLDivElement>(null);
  const windows = useWindows();
  const visibleWindows = windows.filter((w) => !w.minimized);

  return (
    <div ref={canvasRef} className="wm-canvas">
      {visibleWindows.map((w) => (
        <Window key={w.id} windowState={w}>
          <WindowContent windowState={w} />
        </Window>
      ))}

      {visibleWindows.length === 0 && <EmptyState />}
    </div>
  );
}
