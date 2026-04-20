import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ROLE_COOKIE_NAME, useRoleSelection } from "@/hooks/useRoleSelection";

function Probe({
  onReady,
}: {
  onReady: (api: ReturnType<typeof useRoleSelection>) => void;
}) {
  const api = useRoleSelection(null);
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
  afterEach(() => clearAllCookies());

  it("starts with initialRole (SSR hint)", () => {
    let api: ReturnType<typeof useRoleSelection> | null = null;
    function Probe2() {
      api = useRoleSelection("researcher");
      return null;
    }
    render(<Probe2 />);
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
});
