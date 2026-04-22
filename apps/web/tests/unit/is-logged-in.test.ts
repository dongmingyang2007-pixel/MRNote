import { beforeEach, describe, expect, it, vi } from "vitest";

type CookieStub = { get: (name: string) => { value: string } | undefined };

const cookieStore: CookieStub = { get: () => undefined };

vi.mock("next/headers", () => ({
  cookies: async () => cookieStore,
}));

import { isLoggedInFromCookies } from "@/lib/auth/is-logged-in";

describe("isLoggedInFromCookies", () => {
  beforeEach(() => {
    cookieStore.get = () => undefined;
  });

  it("returns false when no auth cookie is present", async () => {
    expect(await isLoggedInFromCookies()).toBe(false);
  });

  it("returns true when auth_state cookie is set", async () => {
    cookieStore.get = (name) =>
      name === "auth_state" ? { value: "1" } : undefined;
    expect(await isLoggedInFromCookies()).toBe(true);
  });

  it("returns true when a legacy workspace cookie is set", async () => {
    cookieStore.get = (name) =>
      name === "qihang_workspace_id" ? { value: "ws_123" } : undefined;
    expect(await isLoggedInFromCookies()).toBe(true);
  });
});
