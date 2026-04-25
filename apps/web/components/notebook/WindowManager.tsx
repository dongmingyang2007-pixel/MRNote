"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
} from "react";
import type { ReactNode } from "react";
import { loadPersistedLayout, savePersistedLayout } from "./window-persistence";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type WindowType =
  | "note"
  | "guest_note"
  | "ai_panel"
  | "file"
  | "memory"
  | "memory_graph"
  | "study"
  | "digest"
  | "search";

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
  /**
   * When true, always open a new window even if an existing one matches.
   * Defaults to false. Callers opt into this for Shift+Click / "Open in new
   * window" interactions. Spec §6.3 allows multi-open but the default flow
   * should de-dup so repeated clicks on the same page/item focus the existing
   * window instead of stacking duplicates (see B-02 in the notebook audit).
   */
  force_new?: boolean;
}

type WindowAction =
  | { kind: "OPEN_WINDOW"; payload: OpenWindowPayload }
  | { kind: "CLOSE_WINDOW"; id: string }
  | { kind: "MINIMIZE"; id: string }
  | { kind: "MAXIMIZE"; id: string }
  | { kind: "RESTORE"; id: string }
  | { kind: "FOCUS"; id: string }
  | { kind: "MOVE"; id: string; x: number; y: number }
  | { kind: "RESIZE"; id: string; width: number; height: number }
  | { kind: "RENAME"; id: string; title: string }
  | {
      kind: "RENAME_BY_META";
      metaKey: string;
      metaValue: string;
      title: string;
    }
  | { kind: "HYDRATE"; windows: WindowState[] };

// ---------------------------------------------------------------------------
// Defaults
// ---------------------------------------------------------------------------

const DEFAULT_SIZES: Record<WindowType, { width: number; height: number }> = {
  note: { width: 780, height: 600 },
  guest_note: { width: 780, height: 600 },
  ai_panel: { width: 480, height: 620 },
  file: { width: 700, height: 500 },
  memory: { width: 500, height: 600 },
  memory_graph: { width: 1100, height: 720 },
  study: { width: 600, height: 500 },
  digest: { width: 520, height: 620 },
  search: { width: 680, height: 720 },
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
  return sorted.map((w, i) =>
    w.zIndex === i + 1 ? w : { ...w, zIndex: i + 1 },
  );
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
      const { type, title, meta = {}, force_new = false } = action.payload;
      // `ai_panel` / `file` still support multi-open out of the box (multiple AI
      // conversations, multiple files side by side). `note` used to be in this
      // list but that produced unbounded duplicates when the page-tree was
      // clicked repeatedly — B-02 in the notebook audit. We now default to
      // focus-existing and require `force_new=true` (e.g. Shift+Click) to stack.
      const supportsMultiOpen = type === "file" || type === "ai_panel";

      const existing =
        force_new || supportsMultiOpen
          ? undefined
          : state.find((w) => {
              if (w.type !== type) return false;
              // For `note` windows, de-dup by pageId only. Other meta fields
              // may differ (e.g. scroll offset) but the same page means the
              // same window.
              if (type === "note") {
                const existingPage = w.meta.pageId;
                const targetPage = meta.pageId;
                return !!existingPage && existingPage === targetPage;
              }
              if (type === "guest_note") {
                const existingPage = w.meta.guestPageId;
                const targetPage = meta.guestPageId;
                return !!existingPage && existingPage === targetPage;
              }
              return JSON.stringify(w.meta) === JSON.stringify(meta);
            });
      if (existing) {
        // Just focus it — also un-minimize so clicking a minimized page
        // restores it (previously minimized notes were invisible after click).
        const top = maxZIndex(state) + 1;
        return state.map((w) =>
          w.id === existing.id ? { ...w, zIndex: top, minimized: false } : w,
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
          ? {
              ...w,
              minimized: false,
              maximized: false,
              zIndex: maxZIndex(state) + 1,
            }
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

    case "RENAME":
      return state.map((w) =>
        w.id === action.id && w.title !== action.title
          ? { ...w, title: action.title }
          : w,
      );

    case "RENAME_BY_META":
      return state.map((w) =>
        w.meta[action.metaKey] === action.metaValue && w.title !== action.title
          ? { ...w, title: action.title }
          : w,
      );

    case "RESIZE":
      return state.map((w) =>
        w.id === action.id
          ? { ...w, width: action.width, height: action.height }
          : w,
      );

    case "HYDRATE":
      return action.windows;

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
  renameWindow: (id: string, title: string) => void;
  renameWindowByMeta: (
    metaKey: string,
    metaValue: string,
    title: string,
  ) => void;
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
  // Always start with an empty layout so the server-rendered HTML matches
  // the first client render (localStorage is unavailable on the server).
  // The persisted layout is then applied in a mount effect via HYDRATE,
  // which runs after React has finished hydrating the SSR tree.
  const [windows, dispatch] = useReducer(windowReducer, []);
  const hydratedRef = useRef(false);

  useEffect(() => {
    const persisted = loadPersistedLayout(notebookId);
    if (persisted.length > 0) {
      dispatch({ kind: "HYDRATE", windows: persisted });
    }
    hydratedRef.current = true;
  }, [notebookId]);

  // Debounced persist on change. Skip the first run so we don't overwrite
  // localStorage with `[]` before HYDRATE has a chance to load it.
  useEffect(() => {
    if (!hydratedRef.current) return;
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
    (id: string, x: number, y: number) => dispatch({ kind: "MOVE", id, x, y }),
    [],
  );
  const resizeWindow = useCallback(
    (id: string, width: number, height: number) =>
      dispatch({ kind: "RESIZE", id, width, height }),
    [],
  );
  const renameWindow = useCallback(
    (id: string, title: string) => dispatch({ kind: "RENAME", id, title }),
    [],
  );
  const renameWindowByMeta = useCallback(
    (metaKey: string, metaValue: string, title: string) =>
      dispatch({ kind: "RENAME_BY_META", metaKey, metaValue, title }),
    [],
  );

  const value = useMemo<WindowManagerContextValue>(
    () => ({
      windows,
      dispatch,
      openWindow,
      closeWindow,
      renameWindow,
      renameWindowByMeta,
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
      renameWindow,
      renameWindowByMeta,
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
