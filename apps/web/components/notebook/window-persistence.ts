import type { WindowState } from "./WindowManager";

export const STORAGE_KEY_PREFIX = "mrai.windows.";
export const CURRENT_SCHEMA_VERSION = 1 as const;

interface PersistedLayout {
  v: typeof CURRENT_SCHEMA_VERSION;
  windows: WindowState[];
}

export function loadPersistedLayout(notebookId: string): WindowState[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY_PREFIX + notebookId);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (
      !parsed ||
      typeof parsed !== "object" ||
      (parsed as { v?: unknown }).v !== CURRENT_SCHEMA_VERSION ||
      !Array.isArray((parsed as { windows?: unknown }).windows)
    ) {
      return [];
    }
    return (parsed as PersistedLayout).windows;
  } catch {
    return [];
  }
}

export function savePersistedLayout(
  notebookId: string,
  windows: WindowState[],
): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      STORAGE_KEY_PREFIX + notebookId,
      JSON.stringify({ v: CURRENT_SCHEMA_VERSION, windows }),
    );
  } catch (err) {
    console.warn("window-persistence: save failed", err);
  }
}
