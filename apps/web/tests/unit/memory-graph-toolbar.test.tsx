import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Toolbar } from "@/components/console/graph/memory-graph/Toolbar";
import type { Role } from "@/components/console/graph/memory-graph/types";

const ALL_ROLES: Role[] = ["fact", "structure", "subject", "concept", "summary"];

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function defaults() {
  return {
    search: "",
    confMin: 0.6,
    filters: Object.fromEntries(ALL_ROLES.map((r) => [r, true])) as Record<Role, boolean>,
    view: "graph" as "graph" | "list",
    counts: Object.fromEntries(ALL_ROLES.map((r) => [r, 3])) as Record<Role, number>,
    onSearch: vi.fn(),
    onConfMin: vi.fn(),
    onToggleFilter: vi.fn(),
    onRearrange: vi.fn(),
    onFit: vi.fn(),
    onViewChange: vi.fn(),
  };
}

describe("Toolbar", () => {
  it("fires onSearch as user types", () => {
    const props = defaults();
    render(<Toolbar {...props} />);
    const input = screen.getByTestId("mg-search-input");
    fireEvent.change(input, { target: { value: "grad" } });
    expect(props.onSearch).toHaveBeenCalledWith("grad");
  });

  it("fires onConfMin when slider moves", () => {
    const props = defaults();
    render(<Toolbar {...props} />);
    const slider = screen.getByTestId("mg-conf-slider");
    fireEvent.change(slider, { target: { value: "0.8" } });
    expect(props.onConfMin).toHaveBeenCalledWith(0.8);
  });

  it("renders one chip per role with count", () => {
    const props = defaults();
    render(<Toolbar {...props} />);
    for (const r of ALL_ROLES) {
      expect(screen.getByTestId(`mg-chip-${r}`)).toBeTruthy();
    }
  });

  it("fires onToggleFilter with role on chip click", () => {
    const props = defaults();
    render(<Toolbar {...props} />);
    fireEvent.click(screen.getByTestId("mg-chip-fact"));
    expect(props.onToggleFilter).toHaveBeenCalledWith("fact");
  });

  it("fires onRearrange / onFit / onViewChange on buttons", () => {
    const props = defaults();
    render(<Toolbar {...props} />);
    fireEvent.click(screen.getByTestId("mg-btn-rearrange"));
    fireEvent.click(screen.getByTestId("mg-btn-fit"));
    fireEvent.click(screen.getByTestId("mg-btn-view-list"));
    expect(props.onRearrange).toHaveBeenCalled();
    expect(props.onFit).toHaveBeenCalled();
    expect(props.onViewChange).toHaveBeenCalledWith("list");
  });
});
