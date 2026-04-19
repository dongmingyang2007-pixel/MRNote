import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CanvasControls } from "@/components/console/graph/memory-graph/CanvasControls";

afterEach(() => { cleanup(); });

describe("CanvasControls", () => {
  it("renders rearrange + fit buttons", () => {
    render(<CanvasControls onRearrange={() => {}} onFit={() => {}} />);
    expect(screen.getByTestId("mg-btn-rearrange")).toBeTruthy();
    expect(screen.getByTestId("mg-btn-fit")).toBeTruthy();
  });

  it("fires handlers on click", () => {
    const onR = vi.fn(), onF = vi.fn();
    render(<CanvasControls onRearrange={onR} onFit={onF} />);
    fireEvent.click(screen.getByTestId("mg-btn-rearrange"));
    fireEvent.click(screen.getByTestId("mg-btn-fit"));
    expect(onR).toHaveBeenCalled();
    expect(onF).toHaveBeenCalled();
  });
});
