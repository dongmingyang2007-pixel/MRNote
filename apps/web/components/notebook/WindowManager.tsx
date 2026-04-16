"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
} from "react";
import type { ReactNode } from "react";
import {
  loadPersistedLayout,
  savePersistedLayout,
} from "./window-persistence";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type WindowType = "note" | "ai_panel" | "file" | "memory" | "study";

export interface WindowState {
  id: string;
  type: WindowType;
  title: string;
  x: number;
  y: number;
  width: number;
  height: number;
  zIndex: number;
  minimized: boolean;
  maximized: boolean;
  meta: Record<string, string>;
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

interface OpenWindowPayload {
  type: WindowType;
  title: string;
  meta?: Record<string, string>;
}

type WindowAction =
  | { kind: "OPEN_WINDOW"; payload: OpenWindowPayload }
  | { kind: "CLOSE_WINDOW"; id: string }
  | { kind: "MINIMIZE"; id: string }
  | { kind: "MAXIMIZE"; id: string }
  | { kind: "RESTORE"; id: string }
  | { kind: "FOCUS"; id: string }
  | { kind: "MOVE"; id: string; x: number; y: number }
  | { kind: "RESIZE"; id: string; width: number; height: number };

// ---------------------------------------------------------------------------
// Defaults
// ---------------------------------------------------------------------------

const DEFAULT_SIZES: Record<WindowType, { width: number; height: number }> = {
  note: { width: 780, height: 600 },
  ai_panel: { width: 480, height: 620 },
  file: { width: 700, height: 500 },
  memory: { width: 500, height: 600 },
  study: { width: 600, height: 500 },
};

function generateId(): string {
  return crypto.randomUUID();
}

function cascadePosition(count: number): { x: number; y: number } {
  return {
    x: 80 + 30 * (count % 8),
    y: 40 + 30 * (count % 6),
  };
}

function maxZIndex(windows: WindowState[]): number {
  if (windows.length === 0) return 0;
  return Math.max(...windows.map((w) => w.zIndex));
}

/** Re-normalize all zIndex values to [1..N] to prevent unbounded growth. */
function normalizeZIndexes(windows: WindowState[]): WindowState[] {
  const sorted = [...windows].sort((a, b) => a.zIndex - b.zIndex);
  return sorted.map((w, i) => (w.zIndex === i + 1 ? w : { ...w, zIndex: i + 1 }));
}

const Z_INDEX_NORMALIZE_THRESHOLD = 10000;

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

function windowReducer(
  state: WindowState[],
  action: WindowAction,
): WindowState[] {
  switch (action.kind) {
    case "OPEN_WINDOW": {
      const { type, title, meta = {} } = action.payload;
      const supportsMultiOpen =
        type === "note" || type === "file" || type === "ai_panel";

      const existing = supportsMultiOpen
        ? undefined
        : state.find(
            (w) =>
              w.type === type &&
              JSON.stringify(w.meta) === JSON.stringify(meta),
          );
      if (existing) {
        // Just focus it
        const top = maxZIndex(state) + 1;
        return state.map((w) =>
          w.id === existing.id
            ? { ...w, zIndex: top, minimized: false }
            : w,
        );
      }

      const size = DEFAULT_SIZES[type];
      const pos = cascadePosition(state.length);
      const newWindow: WindowState = {
        id: generateId(),
        type,
        title,
        x: pos.x,
        y: pos.y,
        width: size.width,
        height: size.height,
        zIndex: maxZIndex(state) + 1,
        minimized: false,
        maximized: false,
        meta,
      };
      return [...state, newWindow];
    }

    case "CLOSE_WINDOW":
      return state.filter((w) => w.id !== action.id);

    case "MINIMIZE":
      return state.map((w) =>
        w.id === action.id ? { ...w, minimized: true } : w,
      );

    case "MAXIMIZE":
      return state.map((w) =>
        w.id === action.id
          ? { ...w, maximized: true, zIndex: maxZIndex(state) + 1 }
          : w,
      );

    case "RESTORE":
      return state.map((w) =>
        w.id === action.id
          ? { ...w, minimized: false, maximized: false, zIndex: maxZIndex(state) + 1 }
          : w,
      );

    case "FOCUS": {
      const top = maxZIndex(state) + 1;
      let next = state.map((w) =>
        w.id === action.id ? { ...w, zIndex: top } : w,
      );
      if (top > Z_INDEX_NORMALIZE_THRESHOLD) {
        next = normalizeZIndexes(next);
      }
      return next;
    }

    case "MOVE":
      return state.map((w) =>
        w.id === action.id ? { ...w, x: action.x, y: action.y } : w,
      );

    case "RESIZE":
      return state.map((w) =>
        w.id === action.id
          ? { ...w, width: action.width, height: action.height }
          : w,
      );

    default:
      return state;
  }
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

interface WindowManagerContextValue {
  windows: WindowState[];
  dispatch: (action: WindowAction) => void;
  openWindow: (payload: OpenWindowPayload) => void;
  closeWindow: (id: string) => void;
  minimizeWindow: (id: string) => void;
  maximizeWindow: (id: string) => void;
  restoreWindow: (id: string) => void;
  focusWindow: (id: string) => void;
  moveWindow: (id: string, x: number, y: number) => void;
  resizeWindow: (id: string, width: number, height: number) => void;
}

const WindowManagerContext = createContext<WindowManagerContextValue | null>(
  null,
);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function WindowManagerProvider({
  children,
  notebookId,
}: {
  children: ReactNode;
  notebookId: string;
}) {
  const [windows, dispatch] = useReducer(
    windowReducer,
    undefined,
    () => loadPersistedLayout(notebookId),
  );

  // Debounced persist on change.
  useEffect(() => {
    const handle = setTimeout(() => {
      savePersistedLayout(notebookId, windows);
    }, 500);
    return () => clearTimeout(handle);
  }, [notebookId, windows]);

  const openWindow = useCallback(
    (payload: OpenWindowPayload) => dispatch({ kind: "OPEN_WINDOW", payload }),
    [],
  );
  const closeWindow = useCallback(
    (id: string) => dispatch({ kind: "CLOSE_WINDOW", id }),
    [],
  );
  const minimizeWindow = useCallback(
    (id: string) => dispatch({ kind: "MINIMIZE", id }),
    [],
  );
  const maximizeWindow = useCallback(
    (id: string) => dispatch({ kind: "MAXIMIZE", id }),
    [],
  );
  const restoreWindow = useCallback(
    (id: string) => dispatch({ kind: "RESTORE", id }),
    [],
  );
  const focusWindow = useCallback(
    (id: string) => dispatch({ kind: "FOCUS", id }),
    [],
  );
  const moveWindow = useCallback(
    (id: string, x: number, y: number) =>
      dispatch({ kind: "MOVE", id, x, y }),
    [],
  );
  const resizeWindow = useCallback(
    (id: string, width: number, height: number) =>
      dispatch({ kind: "RESIZE", id, width, height }),
    [],
  );

  const value = useMemo<WindowManagerContextValue>(
    () => ({
      windows,
      dispatch,
      openWindow,
      closeWindow,
      minimizeWindow,
      maximizeWindow,
      restoreWindow,
      focusWindow,
      moveWindow,
      resizeWindow,
    }),
    [
      windows,
      openWindow,
      closeWindow,
      minimizeWindow,
      maximizeWindow,
      restoreWindow,
      focusWindow,
      moveWindow,
      resizeWindow,
    ],
  );

  return (
    <WindowManagerContext.Provider value={value}>
      {children}
    </WindowManagerContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useWindowManager(): WindowManagerContextValue {
  const ctx = useContext(WindowManagerContext);
  if (!ctx) {
    throw new Error(
      "useWindowManager must be used within a WindowManagerProvider",
    );
  }
  return ctx;
}

export function useWindows(): WindowState[] {
  const { windows } = useWindowManager();
  return windows;
}
