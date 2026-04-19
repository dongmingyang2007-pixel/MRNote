import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ListView } from "@/components/console/graph/memory-graph/ListView";
import type { GraphNode } from "@/components/console/graph/memory-graph/types";

function makeNode(over: Partial<GraphNode>): GraphNode {
  return {
    id: "n",
    role: "fact",
    label: "Node",
    conf: 0.8,
    reuse: 0,
    lastUsed: null,
    pinned: false,
    source: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    raw: {} as any,
    ...over,
  };
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("ListView", () => {
  it("renders one row per node", () => {
    const nodes = [
      makeNode({ id: "a", label: "Alpha" }),
      makeNode({ id: "b", label: "Beta" }),
    ];
    render(<ListView nodes={nodes} onSelect={() => {}} selectedId={null} />);
    expect(screen.getByText("Alpha")).toBeTruthy();
    expect(screen.getByText("Beta")).toBeTruthy();
  });

  it("fires onSelect with node id on row click", () => {
    const onSelect = vi.fn();
    const nodes = [makeNode({ id: "x", label: "Xenon" })];
    render(<ListView nodes={nodes} onSelect={onSelect} selectedId={null} />);
    fireEvent.click(screen.getByTestId("mg-list-row-x"));
    expect(onSelect).toHaveBeenCalledWith("x");
  });

  it("highlights selectedId", () => {
    const nodes = [makeNode({ id: "y", label: "Ytterbium" })];
    render(<ListView nodes={nodes} onSelect={() => {}} selectedId="y" />);
    const row = screen.getByTestId("mg-list-row-y");
    expect(row.getAttribute("aria-selected")).toBe("true");
  });

  it("sorts by conf descending when clicking conf header", () => {
    const nodes = [
      makeNode({ id: "a", label: "Lo", conf: 0.6 }),
      makeNode({ id: "b", label: "Hi", conf: 0.95 }),
    ];
    render(<ListView nodes={nodes} onSelect={() => {}} selectedId={null} />);
    const initialRows = screen.getAllByTestId(/^mg-list-row-/);
    expect(initialRows[0].textContent).toMatch(/Lo/);
    fireEvent.click(screen.getByTestId("mg-list-header-conf"));
    const sortedRows = screen.getAllByTestId(/^mg-list-row-/);
    expect(sortedRows[0].textContent).toMatch(/Hi/);
  });
});
