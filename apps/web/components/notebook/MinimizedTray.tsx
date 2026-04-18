"use client";

import { useEffect, useState } from "react";
import {
  FileText,
  Sparkles,
  FileUp,
  Brain,
  BookOpen,
  Bell,
  Search,
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
  search: Search,
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MinimizedTray() {
  // Hydration gate: WindowManager hydrates from localStorage on mount, so
  // server-rendered windows[] is always empty while client may have
  // persisted minimized entries. Rendering nothing on both sides until
  // mount avoids the "<div> inside <a>"-style mismatch that surfaces
  // when the surrounding Sidebar re-orders sibling nodes.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const windows = useWindows();
  const { restoreWindow } = useWindowManager();

  if (!mounted) return null;

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
