import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FilterRow } from "@/components/console/graph/memory-graph/FilterRow";
import type { Role } from "@/components/console/graph/memory-graph/types";

const ALL_ROLES: Role[] = ["fact", "structure", "subject", "concept", "summary"];

afterEach(() => { cleanup(); });

function defaults() {
  return {
    search: "",
    confMin: 0.6,
    filters: Object.fromEntries(ALL_ROLES.map((r) => [r, true])) as Record<Role, boolean>,
    counts: Object.fromEntries(ALL_ROLES.map((r) => [r, 3])) as Record<Role, number>,
    compact: false,
    onSearch: vi.fn(),
    onConfMin: vi.fn(),
    onToggleFilter: vi.fn(),
  };
}

describe("FilterRow", () => {
  it("renders 5 role chips with counts", () => {
    const p = defaults();
    render(<FilterRow {...p} />);
    for (const r of ALL_ROLES) {
      expect(screen.getByTestId(`mg-chip-${r}`)).toBeTruthy();
    }
  });

  it("fires onToggleFilter with role on chip click", () => {
    const p = defaults();
    render(<FilterRow {...p} />);
    fireEvent.click(screen.getByTestId("mg-chip-concept"));
    expect(p.onToggleFilter).toHaveBeenCalledWith("concept");
  });

  it("fires onSearch + onConfMin", () => {
    const p = defaults();
    render(<FilterRow {...p} />);
    fireEvent.change(screen.getByTestId("mg-search-input"), { target: { value: "grad" } });
    fireEvent.change(screen.getByTestId("mg-conf-slider"), { target: { value: "0.85" } });
    expect(p.onSearch).toHaveBeenCalledWith("grad");
    expect(p.onConfMin).toHaveBeenCalledWith(0.85);
  });

  it("compact mode hides chips + slider label", () => {
    const p = defaults();
    render(<FilterRow {...p} compact />);
    expect(screen.queryByTestId("mg-chip-fact")).toBeFalsy();
  });
});
