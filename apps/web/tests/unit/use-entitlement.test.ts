import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useEntitlement } from "@/hooks/useEntitlement";

afterEach(() => { vi.restoreAllMocks(); });

interface BillingMeMock {
  plan: string;
  entitlements: Record<string, boolean | number>;
  usage_this_month: Record<string, number>;
}

function mockMe(me: BillingMeMock) {
  global.fetch = vi.fn(async (url: RequestInfo | URL) => {
    const u = String(url);
    if (u.includes("/api/v1/auth/csrf")) {
      return { ok: true, status: 200,
               json: async () => ({ csrf_token: "t" }) } as Response;
    }
    if (u.includes("/api/v1/billing/me")) {
      return { ok: true, status: 200, json: async () => me } as Response;
    }
    return { ok: true, status: 200, json: async () => ({}) } as Response;
  }) as typeof fetch;
}

describe("useEntitlement", () => {
  it("returns allowed for unlimited counted entitlement", async () => {
    mockMe({
      plan: "pro", entitlements: { "notebooks.max": -1 },
      usage_this_month: { notebooks: 5 },
    });
    const { result } = renderHook(() => useEntitlement("notebooks.max"));
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.allowed).toBe(true);
  });

  it("returns denied when current >= limit", async () => {
    mockMe({
      plan: "free", entitlements: { "notebooks.max": 1 },
      usage_this_month: { notebooks: 1 },
    });
    const { result } = renderHook(() => useEntitlement("notebooks.max"));
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.allowed).toBe(false);
  });

  it("returns allowed for true bool entitlement", async () => {
    mockMe({
      plan: "pro", entitlements: { "voice.enabled": true },
      usage_this_month: {},
    });
    const { result } = renderHook(() => useEntitlement("voice.enabled"));
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.allowed).toBe(true);
  });
});
