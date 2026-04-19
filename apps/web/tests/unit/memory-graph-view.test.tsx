import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryGraphView } from "@/components/console/graph/memory-graph/MemoryGraphView";
import type { GraphNode, GraphEdge } from "@/components/console/graph/memory-graph/types";

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

describe("MemoryGraphView", () => {
  it("renders toolbar + canvas + legend, no drawer until a node is selected", () => {
    const nodes: GraphNode[] = [makeNode({ id: "a", label: "Alpha" })];
    const edges: GraphEdge[] = [];
    render(<MemoryGraphView nodes={nodes} edges={edges} />);
    expect(screen.getByTestId("mg-search-input")).toBeTruthy();
    expect(screen.getByTestId("mg-svg")).toBeTruthy();
    expect(screen.queryByRole("complementary", { name: "Node detail" })).toBeNull();
  });

  it("opens drawer when a node is clicked", () => {
    const nodes: GraphNode[] = [makeNode({ id: "a", label: "Alpha" })];
    render(<MemoryGraphView nodes={nodes} edges={[]} />);
    fireEvent.click(screen.getByTestId("mg-node-a"));
    const drawer = screen.getByRole("complementary", { name: "Node detail" });
    expect(drawer).toBeTruthy();
    // drawer h2 contains the node label
    expect(drawer.querySelector("h2")?.textContent).toBe("Alpha");
  });

  it("switches to ListView when List tab clicked", () => {
    const nodes: GraphNode[] = [makeNode({ id: "a", label: "Alpha" })];
    render(<MemoryGraphView nodes={nodes} edges={[]} />);
    fireEvent.click(screen.getByTestId("mg-btn-view-list"));
    expect(screen.getByTestId("mg-list-row-a")).toBeTruthy();
    expect(screen.queryByTestId("mg-svg")).toBeNull();
  });
});
