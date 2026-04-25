"use client";

import { useMemo } from "react";
import { BookOpen, Layers, Mouse, Plus, Settings } from "lucide-react";
import {
  MarketingWorkspacePreview,
  type WorkspaceFocus,
} from "./ProductPreviews";
import { useRoleContext } from "@/lib/marketing/RoleContext";
import {
  ROLE_CONTENT,
  type FocusWin as RoleFocusWin,
} from "@/lib/marketing/role-content";

/**
 * Hero canvas stage — macOS-styled viewport with three mock windows
 * floating in absolute slots. The `focusWin` prop (driven by the Hero
 * persona pill switch) brings one window forward with a dashed teal
 * glow. When the prop is omitted we fall back to RoleContext so the
 * canvas still reacts when a visitor picks a role further down the
 * page in ExclusiveSection.
 */

interface HeroCanvasStageProps {
  focusWin?: "memory" | "ai" | "study";
}

const ROLE_FOCUS_TO_SLOT: Record<RoleFocusWin, "a" | "b" | "c"> = {
  memory: "a",
  page: "a",
  ai: "b",
  study: "c",
};

const PERSONA_FOCUS_TO_SLOT: Record<
  NonNullable<HeroCanvasStageProps["focusWin"]>,
  "a" | "b" | "c"
> = {
  memory: "a",
  ai: "b",
  study: "c",
};

export default function HeroCanvasStage({
  focusWin,
}: HeroCanvasStageProps = {}) {
  const { role } = useRoleContext();

  const focusSlot = useMemo<"a" | "b" | "c" | null>(() => {
    if (focusWin) return PERSONA_FOCUS_TO_SLOT[focusWin];
    if (!role) return null;
    const win = ROLE_CONTENT[role].hero?.focusWin;
    return win ? ROLE_FOCUS_TO_SLOT[win] : null;
  }, [focusWin, role]);

  const workspaceFocus = useMemo<WorkspaceFocus | null>(() => {
    if (focusWin === "memory") return "graph";
    if (focusWin === "ai") return "ai";
    if (focusWin === "study") return "study";
    if (!role) return null;
    const win = ROLE_CONTENT[role].hero?.focusWin;
    if (win === "memory") return "graph";
    if (win === "page") return "editor";
    if (win === "ai") return "ai";
    if (win === "study") return "study";
    return focusSlot === "a"
      ? "graph"
      : focusSlot === "b"
        ? "ai"
        : focusSlot === "c"
          ? "study"
          : null;
  }, [focusSlot, focusWin, role]);

  return (
    <div
      className="marketing-canvas-stage"
      role="region"
      aria-label="Notebook canvas demo"
      data-focus={focusSlot ?? "none"}
    >
      <div className="marketing-canvas-stage__dots" aria-hidden="true" />
      <div className="marketing-canvas-stage__chrome">
        <div className="marketing-canvas-stage__traffic" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <div className="marketing-canvas-stage__path">
          <BookOpen size={12} aria-hidden="true" />
          <strong>Memory V3</strong>
          <span style={{ opacity: 0.5 }}>/ 今日画布</span>
        </div>
        <div className="marketing-canvas-stage__toolbar" aria-hidden="true">
          <button type="button" aria-label="Add window" tabIndex={-1}>
            <Plus size={14} />
          </button>
          <button type="button" aria-label="Layout" tabIndex={-1}>
            <Layers size={14} />
          </button>
          <button type="button" aria-label="Settings" tabIndex={-1}>
            <Settings size={14} />
          </button>
        </div>
      </div>

      <div className="marketing-canvas-stage__viewport">
        <MarketingWorkspacePreview focus={workspaceFocus} surface="hero" />
      </div>

      <div className="marketing-canvas-stage__hint">
        <Mouse size={12} aria-hidden="true" />
        拖动任意窗口
      </div>
    </div>
  );
}
