import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  CURRENT_SCHEMA_VERSION,
  STORAGE_KEY_PREFIX,
  loadPersistedLayout,
  savePersistedLayout,
} from "@/components/notebook/window-persistence";
import type { WindowState } from "@/components/notebook/WindowManager";

const SAMPLE: WindowState[] = [
  {
    id: "w1",
    type: "note",
    title: "t",
    x: 10,
    y: 20,
    width: 780,
    height: 600,
    zIndex: 1,
    minimized: false,
    maximized: false,
    meta: { pageId: "p1", notebookId: "nb1" },
  },
];

beforeEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("window-persistence", () => {
  it("loadPersistedLayout returns [] when nothing is stored", () => {
    expect(loadPersistedLayout("nb1")).toEqual([]);
  });

  it("roundtrips save → load", () => {
    savePersistedLayout("nb1", SAMPLE);
    expect(loadPersistedLayout("nb1")).toEqual(SAMPLE);
  });

  it("loadPersistedLayout returns [] on malformed JSON", () => {
    window.localStorage.setItem(STORAGE_KEY_PREFIX + "nb1", "not-json");
    expect(loadPersistedLayout("nb1")).toEqual([]);
  });

  it("loadPersistedLayout returns [] when schema version does not match", () => {
    window.localStorage.setItem(
      STORAGE_KEY_PREFIX + "nb1",
      JSON.stringify({ v: 99, windows: SAMPLE }),
    );
    expect(loadPersistedLayout("nb1")).toEqual([]);
  });

  it("loadPersistedLayout returns [] when windows is not an array", () => {
    window.localStorage.setItem(
      STORAGE_KEY_PREFIX + "nb1",
      JSON.stringify({ v: CURRENT_SCHEMA_VERSION, windows: "bogus" }),
    );
    expect(loadPersistedLayout("nb1")).toEqual([]);
  });

  it("savePersistedLayout swallows localStorage quota errors", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const setItem = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new DOMException("quota", "QuotaExceededError");
      });
    expect(() => savePersistedLayout("nb1", SAMPLE)).not.toThrow();
    expect(warn).toHaveBeenCalled();
    setItem.mockRestore();
  });
});
