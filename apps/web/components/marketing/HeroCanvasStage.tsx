"use client";

import { useMemo } from "react";
import MemoryMock from "./mocks/MemoryMock";
import FollowupMock from "./mocks/FollowupMock";
import DigestMock from "./mocks/DigestMock";
import { useRoleContext } from "@/lib/marketing/RoleContext";
import { ROLE_CONTENT, type FocusWin } from "@/lib/marketing/role-content";

/**
 * The right half of the Hero. Three mocks overlap and float idly on
 * a soft stage; when a role is active, the mock tied to that role's
 * `hero.focusWin` lifts forward with a quiet glow outline.
 *
 * The stage renders only three mocks but the role content uses four
 * logical window ids (page / memory / ai / study) per spec §1.6.
 * We fold `page` into the same slot as `memory` for now — both are
 * "content"-style panels — until a dedicated PageMock ships.
 */
const FOCUS_WIN_TO_SLOT: Record<FocusWin, "a" | "b" | "c"> = {
  memory: "a",
  page: "a",
  ai: "b",
  study: "c",
};

export default function HeroCanvasStage() {
  const { role } = useRoleContext();
  const focusSlot = useMemo(() => {
    if (!role) return null;
    const win = ROLE_CONTENT[role].hero?.focusWin;
    return win ? FOCUS_WIN_TO_SLOT[win] : null;
  }, [role]);

  const slotClass = (id: "a" | "b" | "c") =>
    [
      "marketing-canvas-stage__slot",
      `marketing-canvas-stage__slot--${id}`,
      focusSlot === id ? "is-focused" : "",
    ]
      .filter(Boolean)
      .join(" ");

  return (
    <div className="marketing-canvas-stage" data-focus={focusSlot ?? "none"}>
      <div className={slotClass("a")}>
        <MemoryMock />
      </div>
      <div className={slotClass("b")}>
        <FollowupMock />
      </div>
      <div className={slotClass("c")}>
        <DigestMock />
      </div>
    </div>
  );
}
