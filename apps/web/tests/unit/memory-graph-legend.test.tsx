import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LegendAndZoom } from "@/components/console/graph/memory-graph/LegendAndZoom";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("LegendAndZoom", () => {
  it("renders 5 legend dots, one per role", () => {
    render(<LegendAndZoom zoom={1} onZoomIn={() => {}} onZoomOut={() => {}} onFit={() => {}} />);
    expect(screen.getByText("memoryGraph.roles.fact")).toBeTruthy();
    expect(screen.getByText("memoryGraph.roles.structure")).toBeTruthy();
    expect(screen.getByText("memoryGraph.roles.subject")).toBeTruthy();
    expect(screen.getByText("memoryGraph.roles.concept")).toBeTruthy();
    expect(screen.getByText("memoryGraph.roles.summary")).toBeTruthy();
  });

  it("shows zoom % formatted to integer", () => {
    render(<LegendAndZoom zoom={1.23} onZoomIn={() => {}} onZoomOut={() => {}} onFit={() => {}} />);
    const indicator = screen.getAllByTestId("mg-zoom-indicator")[0];
    expect(indicator.textContent).toContain("123%");
  });

  it("calls handlers on +/−/fit buttons", () => {
    const onZoomIn = vi.fn();
    const onZoomOut = vi.fn();
    const onFit = vi.fn();
    render(<LegendAndZoom zoom={1} onZoomIn={onZoomIn} onZoomOut={onZoomOut} onFit={onFit} />);
    fireEvent.click(screen.getByTestId("mg-zoom-in"));
    fireEvent.click(screen.getByTestId("mg-zoom-out"));
    fireEvent.click(screen.getByTestId("mg-zoom-fit"));
    expect(onZoomIn).toHaveBeenCalledTimes(1);
    expect(onZoomOut).toHaveBeenCalledTimes(1);
    expect(onFit).toHaveBeenCalledTimes(1);
  });
});
