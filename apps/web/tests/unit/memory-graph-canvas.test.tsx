import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GraphCanvas, clampZoom, nextZoom } from "@/components/console/graph/memory-graph/GraphCanvas";
import type { GraphNode, GraphEdge, Position } from "@/components/console/graph/memory-graph/types";
import { VIEWPORT_DEFAULTS } from "@/components/console/graph/memory-graph/constants";

describe("clampZoom / nextZoom", () => {
  it("clampZoom keeps values inside [kMin, kMax]", () => {
    expect(clampZoom(0.1, VIEWPORT_DEFAULTS)).toBe(VIEWPORT_DEFAULTS.kMin);
    expect(clampZoom(99,  VIEWPORT_DEFAULTS)).toBe(VIEWPORT_DEFAULTS.kMax);
    expect(clampZoom(1.2, VIEWPORT_DEFAULTS)).toBe(1.2);
  });
  it("nextZoom multiplies/divides by 1.2 for +/- actions", () => {
    expect(nextZoom(1, "in",  VIEWPORT_DEFAULTS)).toBeCloseTo(1.2);
    expect(nextZoom(1, "out", VIEWPORT_DEFAULTS)).toBeCloseTo(1 / 1.2);
  });
});

function makeNode(over: Partial<GraphNode> = {}): GraphNode {
  return {
    id: "n1", role: "fact", label: "Alpha",
    conf: 0.8, reuse: 0, lastUsed: null,
    pinned: false, source: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    raw: {} as any, ...over,
  };
}

function makePositions(ids: string[]): Map<string, Position> {
  const m = new Map<string, Position>();
  ids.forEach((id, i) => m.set(id, { x: 100 + i * 50, y: 100, vx: 0, vy: 0, fx: null, fy: null }));
  return m;
}

const ALL_FILTERS = { fact: true, structure: true, subject: true, concept: true, summary: true } as const;

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("GraphCanvas render", () => {
  it("renders an SVG with one <g.mg-node> per node", () => {
    const nodes = [makeNode({ id: "a" }), makeNode({ id: "b" })];
    const edges: GraphEdge[] = [];
    render(
      <GraphCanvas
        nodes={nodes} edges={edges} positions={makePositions(["a", "b"])}
        width={400} height={300}
        viewport={{ k: 1, tx: 0, ty: 0 }}
        hoverId={null} selectedId={null} searchMatches={new Set()}
        filters={{ ...ALL_FILTERS }}
        onViewportChange={() => {}}
        onHover={() => {}}
        onSelect={() => {}}
        onDragStart={() => {}}
        onDrag={() => {}}
        onDragEnd={() => {}}
      />,
    );
    expect(screen.getAllByTestId(/^mg-node-/)).toHaveLength(2);
  });

  it("fires onHover with id on pointerenter over node", () => {
    const nodes = [makeNode({ id: "a" })];
    const onHover = vi.fn();
    render(
      <GraphCanvas
        nodes={nodes} edges={[]} positions={makePositions(["a"])}
        width={400} height={300}
        viewport={{ k: 1, tx: 0, ty: 0 }}
        hoverId={null} selectedId={null} searchMatches={new Set()}
        filters={{ ...ALL_FILTERS }}
        onViewportChange={() => {}}
        onHover={onHover}
        onSelect={() => {}}
        onDragStart={() => {}}
        onDrag={() => {}}
        onDragEnd={() => {}}
      />,
    );
    fireEvent.pointerEnter(screen.getByTestId("mg-node-a"));
    expect(onHover).toHaveBeenCalledWith("a");
  });

  it("fires onSelect on click and onHover(null) on pointerleave", () => {
    const nodes = [makeNode({ id: "a" })];
    const onSelect = vi.fn();
    const onHover = vi.fn();
    render(
      <GraphCanvas
        nodes={nodes} edges={[]} positions={makePositions(["a"])}
        width={400} height={300}
        viewport={{ k: 1, tx: 0, ty: 0 }}
        hoverId={null} selectedId={null} searchMatches={new Set()}
        filters={{ ...ALL_FILTERS }}
        onViewportChange={() => {}}
        onHover={onHover}
        onSelect={onSelect}
        onDragStart={() => {}}
        onDrag={() => {}}
        onDragEnd={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("mg-node-a"));
    fireEvent.pointerLeave(screen.getByTestId("mg-node-a"));
    expect(onSelect).toHaveBeenCalledWith("a");
    expect(onHover).toHaveBeenLastCalledWith(null);
  });
});
