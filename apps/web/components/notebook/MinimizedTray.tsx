"use client";

import {
  FileText,
  Sparkles,
  FileUp,
  Brain,
  BookOpen,
  Bell,
} from "lucide-react";
import { useWindowManager, useWindows } from "./WindowManager";
import type { WindowType } from "./WindowManager";

// ---------------------------------------------------------------------------
// Icon map
// ---------------------------------------------------------------------------

const TRAY_ICONS: Record<WindowType, typeof FileText> = {
  note: FileText,
  ai_panel: Sparkles,
  file: FileUp,
  memory: Brain,
  study: BookOpen,
  digest: Bell,
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MinimizedTray() {
  const windows = useWindows();
  const { restoreWindow } = useWindowManager();

  const minimized = windows.filter((w) => w.minimized);

  if (minimized.length === 0) return null;

  return (
    <div className="wm-minimized-tray">
      {minimized.map((w) => {
        const Icon = TRAY_ICONS[w.type];
        const shortTitle =
          w.title.length > 10 ? w.title.slice(0, 10) + "..." : w.title;

        return (
          <button
            key={w.id}
            type="button"
            className="wm-tray-pill"
            onClick={() => restoreWindow(w.id)}
            title={w.title}
          >
            <Icon size={12} className="wm-tray-pill-icon" />
            <span>{shortTitle}</span>
          </button>
        );
      })}
    </div>
  );
}
