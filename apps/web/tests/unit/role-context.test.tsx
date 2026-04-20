import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import { RoleProvider, useRoleContext } from "@/lib/marketing/RoleContext";

function clearAllCookies() {
  document.cookie
    .split(";")
    .map((c) => c.trim().split("=")[0])
    .filter(Boolean)
    .forEach((name) => {
      document.cookie = `${name}=; Max-Age=0; Path=/`;
    });
}

function RoleDisplay() {
  const { role } = useRoleContext();
  return <span data-testid="role-display">{role ?? "none"}</span>;
}

function RoleSetter() {
  const { setRole, clearRole } = useRoleContext();
  return (
    <>
      <button type="button" data-testid="set-lawyer" onClick={() => setRole("lawyer")}>
        set lawyer
      </button>
      <button type="button" data-testid="clear" onClick={clearRole}>
        clear
      </button>
    </>
  );
}

describe("RoleProvider", () => {
  afterEach(() => { cleanup(); clearAllCookies(); });

  it("shares role state between two consumers", () => {
    render(
      <RoleProvider initialRole="researcher" locale="zh">
        <RoleDisplay />
        <RoleSetter />
      </RoleProvider>,
    );
    expect(screen.getByTestId("role-display").textContent).toBe("researcher");

    act(() => { fireEvent.click(screen.getByTestId("set-lawyer")); });
    expect(screen.getByTestId("role-display").textContent).toBe("lawyer");

    act(() => { fireEvent.click(screen.getByTestId("clear")); });
    expect(screen.getByTestId("role-display").textContent).toBe("none");
  });

  it("throws a helpful error when useRoleContext is used outside provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<RoleDisplay />)).toThrow(/useRoleContext must be used inside/);
    spy.mockRestore();
  });

  it("emits landing.role.restored once when mounted with initialRole", async () => {
    const debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
    // Set NODE_ENV to development so the analytics module actually logs
    const origEnv = process.env.NODE_ENV;
    vi.stubEnv("NODE_ENV", "development");

    render(
      <RoleProvider initialRole="researcher" locale="zh">
        <div>mounted</div>
      </RoleProvider>,
    );

    await new Promise((r) => setTimeout(r, 0));
    expect(debugSpy).toHaveBeenCalledWith(
      "[mrai.analytics]",
      "landing.role.restored",
      { role: "researcher", locale: "zh" },
    );

    vi.unstubAllEnvs();
    debugSpy.mockRestore();
  });

  it("does NOT emit landing.role.restored when initialRole is null", async () => {
    const debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
    vi.stubEnv("NODE_ENV", "development");

    render(
      <RoleProvider initialRole={null} locale="zh">
        <div>mounted</div>
      </RoleProvider>,
    );

    await new Promise((r) => setTimeout(r, 0));
    const restoredCalls = debugSpy.mock.calls.filter(
      (c) => c[1] === "landing.role.restored",
    );
    expect(restoredCalls).toHaveLength(0);

    vi.unstubAllEnvs();
    debugSpy.mockRestore();
  });
});
