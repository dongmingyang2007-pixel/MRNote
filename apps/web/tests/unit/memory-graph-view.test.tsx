import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Mock the 3D scene hook — jsdom has no WebGL.
vi.mock("@/components/console/graph/memory-graph/Memory3D/useThreeScene", () => ({
  useThreeScene: () => ({
    focusOn: vi.fn(), rearrange: vi.fn(), zoomIn: vi.fn(), zoomOut: vi.fn(),
    fit: vi.fn(), toggleAutoRotate: vi.fn(), getProjectedScreenPos: vi.fn(() => null),
  }),
}));

import { MemoryGraphView } from "@/components/console/graph/memory-graph/MemoryGraphView";
import type { GraphNode } from "@/components/console/graph/memory-graph/types";

function makeNode(over: Partial<GraphNode>): GraphNode {
  return {
    id: "n", role: "fact", label: "L",
    conf: 0.8, reuse: 0, lastUsed: null, pinned: false, source: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    raw: {} as any,
    ...over,
  };
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("MemoryGraphView layout", () => {
  it("renders HeaderBar + FilterRow + ViewBar + graph canvas", () => {
    render(<MemoryGraphView nodes={[makeNode({ id: "a", label: "Alpha" })]} edges={[]} />);
    expect(screen.getByText("memoryGraph.title")).toBeTruthy();
    expect(screen.getByTestId("mg-search-input")).toBeTruthy();
    expect(screen.getByTestId("mg-btn-view-graph")).toBeTruthy();
    expect(screen.getByTestId("mg-btn-view-3d")).toBeTruthy();
    expect(screen.getByTestId("mg-btn-view-list")).toBeTruthy();
    expect(screen.getByTestId("mg-svg")).toBeTruthy();
  });

  it("opens drawer when a node is clicked", () => {
    const nodes = [makeNode({ id: "a", label: "Alpha" })];
    render(<MemoryGraphView nodes={nodes} edges={[]} />);
    fireEvent.click(screen.getByTestId("mg-node-a"));
    const drawer = screen.getByRole("complementary", { name: "Node detail" });
    expect(drawer).toBeTruthy();
    expect(drawer.querySelector("h2")?.textContent).toBe("Alpha");
  });

  it("switches to list view when List tab clicked", () => {
    render(<MemoryGraphView nodes={[makeNode({ id: "a", label: "Alpha" })]} edges={[]} />);
    fireEvent.click(screen.getByTestId("mg-btn-view-list"));
    expect(screen.getByTestId("mg-list-row-a")).toBeTruthy();
    expect(screen.queryByTestId("mg-svg")).toBeFalsy();
  });

  it("switches to 3d view (Memory3D mount)", () => {
    render(<MemoryGraphView nodes={[]} edges={[]} />);
    fireEvent.click(screen.getByTestId("mg-btn-view-3d"));
    expect(screen.getByTestId("mg3d-mount")).toBeTruthy();
  });
});
