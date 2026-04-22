import { renderHook, act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useSearch } from "@/hooks/useSearch";

afterEach(() => { vi.restoreAllMocks(); });

function setupFetch(onCall: (url: string) => void) {
  global.fetch = vi.fn(async (url: RequestInfo | URL) => {
    const u = String(url);
    onCall(u);
    if (u.includes("/api/v1/auth/csrf")) {
      return { ok: true, status: 200,
               json: async () => ({ csrf_token: "t" }) } as Response;
    }
    return {
      ok: true, status: 200,
      json: async () => ({
        query: "q", duration_ms: 1,
        results: {
          pages: [],
          blocks: [],
          study_assets: [],
          files: [],
          memory: [],
          playbooks: [],
          ai_actions: [],
        },
      }),
    } as Response;
  }) as typeof fetch;
}

describe("useSearch", () => {
  it("does not call fetch for queries shorter than 2 chars", async () => {
    const calls: string[] = [];
    setupFetch((u) => calls.push(u));
    const { result } = renderHook(() => useSearch());
    act(() => { result.current.setQuery("a"); });
    await new Promise((r) => setTimeout(r, 400));
    expect(calls.filter((u) => u.includes("/api/v1/search")).length).toBe(0);
  });

  it("debounces rapid typing", async () => {
    const calls: string[] = [];
    setupFetch((u) => calls.push(u));
    const { result } = renderHook(() => useSearch());
    act(() => { result.current.setQuery("hello"); });
    act(() => { result.current.setQuery("hello world"); });
    await new Promise((r) => setTimeout(r, 400));
    const searchCalls = calls.filter((u) => u.includes("/api/v1/search") || u.includes("/search"));
    // Latest query wins; at most 1 search call (hello world).
    expect(searchCalls.length).toBeLessThanOrEqual(1);
    if (searchCalls[0]) {
      expect(searchCalls[0]).toContain("hello%20world");
    }
  });
});
