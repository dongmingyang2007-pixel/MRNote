import { act, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ROLE_COOKIE_NAME, useRoleSelection } from "@/hooks/useRoleSelection";
import { AUTH_SESSION_EXPIRED_EVENT } from "@/lib/api";

function Probe({
  initialRole = null,
  onReady,
}: {
  initialRole?: Parameters<typeof useRoleSelection>[0];
  onReady: (api: ReturnType<typeof useRoleSelection>) => void;
}) {
  const api = useRoleSelection(initialRole);
  onReady(api);
  return null;
}

function clearAllCookies() {
  document.cookie
    .split(";")
    .map((c) => c.trim().split("=")[0])
    .filter(Boolean)
    .forEach((name) => {
      document.cookie = `${name}=; Max-Age=0; Path=/`;
    });
}

describe("useRoleSelection", () => {
  beforeEach(() => clearAllCookies());
  afterEach(() => {
    clearAllCookies();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("starts with initialRole (SSR hint)", () => {
    let api: ReturnType<typeof useRoleSelection> | null = null;
    render(<Probe initialRole="researcher" onReady={(a) => (api = a)} />);
    expect(api!.role).toBe("researcher");
  });

  it("setRole writes the cookie and updates state", () => {
    let api: ReturnType<typeof useRoleSelection> | null = null;
    render(<Probe onReady={(a) => (api = a)} />);
    act(() => { api!.setRole("lawyer"); });
    expect(api!.role).toBe("lawyer");
    expect(document.cookie).toContain(`${ROLE_COOKIE_NAME}=lawyer`);
  });

  it("clearRole removes the cookie and resets state", () => {
    let api: ReturnType<typeof useRoleSelection> | null = null;
    render(<Probe onReady={(a) => (api = a)} />);
    act(() => { api!.setRole("doctor"); });
    act(() => { api!.clearRole(); });
    expect(api!.role).toBeNull();
    expect(document.cookie).not.toContain(`${ROLE_COOKIE_NAME}=`);
  });

  it("ignores unknown roles written directly to cookie", () => {
    document.cookie = `${ROLE_COOKIE_NAME}=hacker; Path=/`;
    let api: ReturnType<typeof useRoleSelection> | null = null;
    render(<Probe onReady={(a) => (api = a)} />);
    expect(api!.role).toBeNull();
  });

  it("reconciles a live cookie over a stale initialRole after mount", async () => {
    document.cookie = `${ROLE_COOKIE_NAME}=doctor; Path=/`;
    let api: ReturnType<typeof useRoleSelection> | null = null;
    await act(async () => {
      render(<Probe initialRole="lawyer" onReady={(a) => (api = a)} />);
    });
    expect(api!.role).toBe("doctor");
  });

  it("does not redirect guests when the homepage persona probe returns 401", async () => {
    const expiredSpy = vi.fn();
    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, expiredSpy);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: RequestInfo | URL) => {
        const urlStr = String(url);
        if (urlStr.includes("/api/v1/auth/me")) {
          return {
            ok: false,
            status: 401,
            json: async () => ({
              error: {
                code: "unauthorized",
                message: "Authentication required",
              },
            }),
          } as Response;
        }
        throw new Error(`unexpected fetch ${urlStr}`);
      }),
    );

    render(<Probe onReady={() => {}} />);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalled();
    });
    expect(expiredSpy).not.toHaveBeenCalled();

    window.removeEventListener(AUTH_SESSION_EXPIRED_EVENT, expiredSpy);
  });
});
