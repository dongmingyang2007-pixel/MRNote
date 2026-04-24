import type { WindowState } from "./WindowManager";

// Keep enough horizontal titlebar surface visible to drag the window back.
// The old 80px threshold could leave only the control buttons visible when a
// window was pushed far left, which made the recovery affordance unreliable.
export const HORIZONTAL_RESCUE_VISIBLE_PX = 220;
export const TITLEBAR_RESCUE_VISIBLE_PX = 80;

function finiteOr(value: number, fallback: number): number {
  return Number.isFinite(value) ? value : fallback;
}

function clamp(value: number, min: number, max: number): number {
  if (min > max) return min;
  return Math.max(min, Math.min(value, max));
}

export function clampWindowPosition({
  x,
  y,
  width,
  canvasWidth,
  canvasHeight,
}: {
  x: number;
  y: number;
  width: number;
  canvasWidth: number;
  canvasHeight: number;
}): { x: number; y: number } {
  const safeWidth = Math.max(1, finiteOr(width, HORIZONTAL_RESCUE_VISIBLE_PX));
  const safeCanvasWidth = Math.max(1, finiteOr(canvasWidth, safeWidth));
  const safeCanvasHeight = Math.max(
    TITLEBAR_RESCUE_VISIBLE_PX,
    finiteOr(canvasHeight, TITLEBAR_RESCUE_VISIBLE_PX),
  );
  const visibleWidth = Math.min(
    safeWidth,
    HORIZONTAL_RESCUE_VISIBLE_PX,
    safeCanvasWidth,
  );

  return {
    x: clamp(
      finiteOr(x, 0),
      -safeWidth + visibleWidth,
      safeCanvasWidth - visibleWidth,
    ),
    y: clamp(
      finiteOr(y, 0),
      0,
      Math.max(0, safeCanvasHeight - TITLEBAR_RESCUE_VISIBLE_PX),
    ),
  };
}

export function constrainWindowsToCanvas(
  windows: WindowState[],
  canvasWidth: number,
  canvasHeight: number,
): WindowState[] {
  let changed = false;
  const next = windows.map((windowState) => {
    if (windowState.maximized) return windowState;
    const position = clampWindowPosition({
      x: windowState.x,
      y: windowState.y,
      width: windowState.width,
      canvasWidth,
      canvasHeight,
    });
    if (position.x === windowState.x && position.y === windowState.y) {
      return windowState;
    }
    changed = true;
    return { ...windowState, ...position };
  });

  return changed ? next : windows;
}
