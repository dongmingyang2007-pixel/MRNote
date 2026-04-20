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
      <RoleProvider initialRole="researcher">
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
});
