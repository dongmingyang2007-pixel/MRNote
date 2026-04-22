import { afterEach, describe, expect, it, vi } from "vitest";
import { AUTH_SESSION_EXPIRED_EVENT, apiPost, ApiRequestError } from "@/lib/api";

describe("api auth unauthorized handling", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not treat public login failures as expired sessions", async () => {
    const expiredSpy = vi.fn();
    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, expiredSpy);

    global.fetch = vi.fn(async (url: RequestInfo | URL) => {
      const urlStr = String(url);
      if (urlStr.includes("/api/v1/auth/login")) {
        return {
          ok: false,
          status: 401,
          json: async () => ({
            error: {
              code: "invalid_credentials",
              message: "Invalid email or password",
            },
          }),
        } as Response;
      }
      throw new Error(`unexpected fetch ${urlStr}`);
    }) as typeof fetch;

    await expect(
      apiPost("/api/v1/auth/login", { email: "nobody@example.com", password: "wrong" }),
    ).rejects.toBeInstanceOf(ApiRequestError);
    expect(expiredSpy).not.toHaveBeenCalled();

    window.removeEventListener(AUTH_SESSION_EXPIRED_EVENT, expiredSpy);
  });
});
