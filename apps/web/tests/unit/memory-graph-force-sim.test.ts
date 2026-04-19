import { describe, expect, it } from "vitest";
import { tickOnce, seedCircle, shouldStop } from "@/components/console/graph/memory-graph/useForceSim";
import { FORCE_PARAMS } from "@/components/console/graph/memory-graph/constants";
import type { GraphNode, GraphEdge, Position } from "@/components/console/graph/memory-graph/types";

function makeGNode(id: string, overrides: Partial<GraphNode> = {}): GraphNode {
  return {
    id,
    role: "fact",
    label: id,
    conf: 0.8,
    reuse: 0,
    lastUsed: null,
    pinned: false,
    source: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    raw: {} as any,
    ...overrides,
  };
}

describe("seedCircle", () => {
  it("places N nodes evenly around a circle centered on (W/2, H/2)", () => {
    const nodes = [makeGNode("a"), makeGNode("b"), makeGNode("c"), makeGNode("d")];
    const positions = seedCircle(nodes, 400, 300);
    expect(positions.size).toBe(4);
    for (const p of positions.values()) {
      expect(p.vx).toBe(0);
      expect(p.vy).toBe(0);
      expect(p.fx).toBeNull();
      expect(p.fy).toBeNull();
      expect(p.x).toBeGreaterThanOrEqual(0);
      expect(p.x).toBeLessThanOrEqual(400);
      expect(p.y).toBeGreaterThanOrEqual(0);
      expect(p.y).toBeLessThanOrEqual(300);
    }
  });
});

describe("tickOnce", () => {
  it("advances alpha by the decay factor", () => {
    const positions = new Map<string, Position>();
    positions.set("a", { x: 100, y: 100, vx: 0, vy: 0, fx: null, fy: null });
    positions.set("b", { x: 200, y: 100, vx: 0, vy: 0, fx: null, fy: null });
    const nodes = [makeGNode("a"), makeGNode("b")];
    const edges: GraphEdge[] = [{ a: "a", b: "b", rel: "related", w: 1 }];

    const next = tickOnce({
      positions, nodes, edges, width: 400, height: 300,
      alpha: 1, params: FORCE_PARAMS,
    });
    expect(next.alpha).toBeCloseTo(FORCE_PARAMS.alphaDecay, 5);
  });

  it("fixes position when fx/fy are set (integrator skips them)", () => {
    const positions = new Map<string, Position>();
    positions.set("a", { x: 100, y: 100, vx: 0, vy: 0, fx: 300, fy: 150 });
    positions.set("b", { x: 200, y: 100, vx: 0, vy: 0, fx: null, fy: null });
    const nodes = [makeGNode("a"), makeGNode("b")];
    const edges: GraphEdge[] = [{ a: "a", b: "b", rel: "related", w: 1 }];

    tickOnce({
      positions, nodes, edges, width: 400, height: 300,
      alpha: 1, params: FORCE_PARAMS,
    });
    const a = positions.get("a")!;
    expect(a.x).toBe(300);
    expect(a.y).toBe(150);
    expect(a.vx).toBe(0);
    expect(a.vy).toBe(0);
  });

  it("keeps positions clamped inside viewport with 24px pad", () => {
    const positions = new Map<string, Position>();
    positions.set("a", { x: 5, y: 5, vx: -100, vy: -100, fx: null, fy: null });
    const nodes = [makeGNode("a")];

    tickOnce({
      positions, nodes, edges: [], width: 400, height: 300,
      alpha: 1, params: FORCE_PARAMS,
    });
    const p = positions.get("a")!;
    expect(p.x).toBeGreaterThanOrEqual(24);
    expect(p.y).toBeGreaterThanOrEqual(24);
  });
});

describe("shouldStop", () => {
  it("is true when alpha < alphaMin", () => {
    expect(shouldStop(0.0005, FORCE_PARAMS)).toBe(true);
    expect(shouldStop(FORCE_PARAMS.alphaMin, FORCE_PARAMS)).toBe(false);
    expect(shouldStop(1, FORCE_PARAMS)).toBe(false);
  });
});
