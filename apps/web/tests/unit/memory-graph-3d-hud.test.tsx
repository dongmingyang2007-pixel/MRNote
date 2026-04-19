import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Tooltip3d } from "@/components/console/graph/memory-graph/Memory3D/Tooltip3d";
import { CameraControlsHud } from "@/components/console/graph/memory-graph/Memory3D/CameraControlsHud";
import type { GraphNode } from "@/components/console/graph/memory-graph/types";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function n(over: Partial<GraphNode>): GraphNode {
  return {
    id: "a", role: "fact", label: "Alpha", conf: 0.9, reuse: 0,
    lastUsed: null, pinned: false, source: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    raw: {} as any, ...over,
  };
}

describe("Tooltip3d", () => {
  it("renders node label when visible", () => {
    render(<Tooltip3d node={n({})} x={100} y={200} />);
    expect(screen.getByText("Alpha")).toBeTruthy();
  });

  it("positions via absolute x/y (offset -14 above)", () => {
    const { container } = render(<Tooltip3d node={n({})} x={150} y={250} />);
    const el = container.firstChild as HTMLElement;
    expect(el.style.left).toBe("150px");
    expect(el.style.top).toBe("236px");
  });
});

describe("CameraControlsHud", () => {
  it("renders zoom pct + 4 buttons", () => {
    render(<CameraControlsHud zoomPct={80} autoRotating={false} onZoomIn={() => {}} onZoomOut={() => {}} onFit={() => {}} onToggleAutoRotate={() => {}} />);
    expect(screen.getByText("80%")).toBeTruthy();
    expect(screen.getByTestId("mg3d-zoom-in")).toBeTruthy();
    expect(screen.getByTestId("mg3d-zoom-out")).toBeTruthy();
    expect(screen.getByTestId("mg3d-fit")).toBeTruthy();
    expect(screen.getByTestId("mg3d-auto-rotate")).toBeTruthy();
  });

  it("fires handlers", () => {
    const onZI = vi.fn(), onZO = vi.fn(), onFit = vi.fn(), onAR = vi.fn();
    render(<CameraControlsHud zoomPct={100} autoRotating={false} onZoomIn={onZI} onZoomOut={onZO} onFit={onFit} onToggleAutoRotate={onAR} />);
    fireEvent.click(screen.getByTestId("mg3d-zoom-in"));
    fireEvent.click(screen.getByTestId("mg3d-zoom-out"));
    fireEvent.click(screen.getByTestId("mg3d-fit"));
    fireEvent.click(screen.getByTestId("mg3d-auto-rotate"));
    expect(onZI).toHaveBeenCalled();
    expect(onZO).toHaveBeenCalled();
    expect(onFit).toHaveBeenCalled();
    expect(onAR).toHaveBeenCalled();
  });
});
