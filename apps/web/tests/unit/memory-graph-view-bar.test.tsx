import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ViewBar } from "@/components/console/graph/memory-graph/ViewBar";

afterEach(() => { cleanup(); });

describe("ViewBar", () => {
  it("renders 2D / 3D / List tabs", () => {
    render(<ViewBar view="graph" totalCount={12} onViewChange={() => {}} />);
    expect(screen.getByTestId("mg-btn-view-graph")).toBeTruthy();
    expect(screen.getByTestId("mg-btn-view-3d")).toBeTruthy();
    expect(screen.getByTestId("mg-btn-view-list")).toBeTruthy();
  });

  it("shows the node count badge on each tab", () => {
    render(<ViewBar view="graph" totalCount={22} onViewChange={() => {}} />);
    const counts = screen.getAllByText("22");
    expect(counts.length).toBe(3);
  });

  it("marks the active tab with aria-selected=true", () => {
    render(<ViewBar view="3d" totalCount={5} onViewChange={() => {}} />);
    expect(screen.getByTestId("mg-btn-view-3d").getAttribute("aria-selected")).toBe("true");
    expect(screen.getByTestId("mg-btn-view-graph").getAttribute("aria-selected")).toBe("false");
  });

  it("fires onViewChange on click", () => {
    const onChange = vi.fn();
    render(<ViewBar view="graph" totalCount={3} onViewChange={onChange} />);
    fireEvent.click(screen.getByTestId("mg-btn-view-3d"));
    fireEvent.click(screen.getByTestId("mg-btn-view-list"));
    expect(onChange).toHaveBeenNthCalledWith(1, "3d");
    expect(onChange).toHaveBeenNthCalledWith(2, "list");
  });
});
