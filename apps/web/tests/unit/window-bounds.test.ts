import { describe, expect, it } from "vitest";

import {
  HORIZONTAL_RESCUE_VISIBLE_PX,
  TITLEBAR_RESCUE_VISIBLE_PX,
  clampWindowPosition,
} from "@/components/notebook/window-bounds";

describe("clampWindowPosition", () => {
  it("keeps a draggable horizontal strip visible when a window is dragged left", () => {
    const pos = clampWindowPosition({
      x: -900,
      y: 40,
      width: 600,
      canvasWidth: 1000,
      canvasHeight: 700,
    });

    expect(pos.x).toBe(-600 + HORIZONTAL_RESCUE_VISIBLE_PX);
    expect(pos.y).toBe(40);
  });

  it("keeps a draggable horizontal strip visible when a window is dragged right", () => {
    const pos = clampWindowPosition({
      x: 980,
      y: 40,
      width: 600,
      canvasWidth: 1000,
      canvasHeight: 700,
    });

    expect(pos.x).toBe(1000 - HORIZONTAL_RESCUE_VISIBLE_PX);
  });

  it("keeps the titlebar vertically recoverable", () => {
    const pos = clampWindowPosition({
      x: 20,
      y: 900,
      width: 600,
      canvasWidth: 1000,
      canvasHeight: 700,
    });

    expect(pos.y).toBe(700 - TITLEBAR_RESCUE_VISIBLE_PX);
  });

  it("normalizes invalid coordinates instead of persisting NaN", () => {
    const pos = clampWindowPosition({
      x: Number.NaN,
      y: Number.POSITIVE_INFINITY,
      width: Number.NaN,
      canvasWidth: 1000,
      canvasHeight: 700,
    });

    expect(pos).toEqual({ x: 0, y: 0 });
  });
});
