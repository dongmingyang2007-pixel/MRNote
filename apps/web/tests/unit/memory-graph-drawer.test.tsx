import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NodeDetailDrawer } from "@/components/console/graph/memory-graph/NodeDetailDrawer";
import type { GraphNode } from "@/components/console/graph/memory-graph/types";

function makeGraphNode(overrides: Partial<GraphNode> = {}): GraphNode {
  return {
    id: "n1",
    role: "fact",
    label: "Gradient Descent",
    conf: 0.97,
    reuse: 28,
    lastUsed: "30m",
    pinned: true,
    source: "§3.1",
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    raw: { content: "A lot of longer summary text describing the node." } as any,
    ...overrides,
  };
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("NodeDetailDrawer", () => {
  it("renders role pill + conf + pinned marker", () => {
    const node = makeGraphNode();
    render(<NodeDetailDrawer node={node} neighbors={[]} onSelectNeighbor={() => {}} onClose={() => {}} />);
    expect(screen.getByText("memoryGraph.roles.fact")).toBeTruthy();
    expect(screen.getByText("Gradient Descent")).toBeTruthy();
    expect(screen.getByText("0.97")).toBeTruthy();
    // Pinned label uses the i18n key "memoryGraph.drawer.pinned"
    expect(screen.getAllByText("memoryGraph.drawer.pinned").length).toBeGreaterThan(0);
  });

  it("renders 3 meta columns (source / reuse / last used)", () => {
    const node = makeGraphNode();
    render(<NodeDetailDrawer node={node} neighbors={[]} onSelectNeighbor={() => {}} onClose={() => {}} />);
    expect(screen.getByText("§3.1")).toBeTruthy();
    expect(screen.getByText("28")).toBeTruthy();
    expect(screen.getByText("30m")).toBeTruthy();
  });

  it("renders summary from raw.content", () => {
    const node = makeGraphNode();
    render(<NodeDetailDrawer node={node} neighbors={[]} onSelectNeighbor={() => {}} onClose={() => {}} />);
    expect(screen.getByText(/A lot of longer summary text/)).toBeTruthy();
  });

  it("renders neighbors list and fires onSelectNeighbor on click", () => {
    const neighbors = [
      { id: "n2", rel: "evidence", node: makeGraphNode({ id: "n2", label: "Backprop", role: "subject" }) },
    ];
    const onSelect = vi.fn();
    render(
      <NodeDetailDrawer
        node={makeGraphNode()}
        neighbors={neighbors}
        onSelectNeighbor={onSelect}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("mg-drawer-neighbor-n2"));
    expect(onSelect).toHaveBeenCalledWith("n2");
  });

  it("renders 4 lifecycle stages, 3 filled", () => {
    render(<NodeDetailDrawer node={makeGraphNode()} neighbors={[]} onSelectNeighbor={() => {}} onClose={() => {}} />);
    expect(screen.getAllByTestId(/^mg-lifecycle-stage-/).length).toBe(4);
    expect(screen.getAllByTestId(/^mg-lifecycle-stage-.*-done$/).length).toBe(3);
  });
});
