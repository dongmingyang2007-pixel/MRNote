import { describe, expect, it } from "vitest";
import { masteryOf, placeNodes } from "@/components/console/graph/memory-graph/Memory3D/layout3d";
import type { GraphNode } from "@/components/console/graph/memory-graph/types";

function makeNode(over: Partial<GraphNode>): GraphNode {
  return {
    id: "n", role: "fact", label: "L", conf: 0.8, reuse: 0,
    lastUsed: null, pinned: false, source: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    raw: {} as any,
    ...over,
  };
}

describe("masteryOf", () => {
  it("combines conf (0.5 weight), reuse (0.3), recency (0.2)", () => {
    const n = makeNode({ conf: 0.8, reuse: 20, lastUsed: "0m" });
    expect(masteryOf(n)).toBeCloseTo(0.9, 2);
  });
});

describe("placeNodes — depth rings", () => {
  it("places fact nodes on the fact ring (r=245)", () => {
    const nodes = [
      makeNode({ id: "a", role: "fact" }),
      makeNode({ id: "b", role: "fact" }),
      makeNode({ id: "c", role: "fact" }),
    ];
    const placed = placeNodes(nodes);
    for (const p of placed) {
      const rXZ = Math.sqrt(p.position.x ** 2 + p.position.z ** 2);
      expect(rXZ).toBeGreaterThan(245 - 15);
      expect(rXZ).toBeLessThan(245 + 15);
    }
  });

  it("places subject nodes on inner ring and concept on mid", () => {
    const placed = placeNodes([
      makeNode({ id: "s", role: "subject" }),
      makeNode({ id: "c", role: "concept" }),
    ]);
    const s = placed.find((p) => p.node.role === "subject")!;
    const c = placed.find((p) => p.node.role === "concept")!;
    const rS = Math.sqrt(s.position.x ** 2 + s.position.z ** 2);
    const rC = Math.sqrt(c.position.x ** 2 + c.position.z ** 2);
    expect(rS).toBeLessThan(rC);
    expect(rC).toBeLessThan(200);
  });

  it("Y position tracks mastery", () => {
    const low = makeNode({ id: "low", role: "fact", conf: 0.7, reuse: 0 });
    const high = makeNode({ id: "high", role: "fact", conf: 0.99, reuse: 20, lastUsed: "0m" });
    const placed = placeNodes([low, high]);
    expect(placed.find((p) => p.id === "high")!.position.y).toBeGreaterThan(placed.find((p) => p.id === "low")!.position.y);
  });

  it("is deterministic (same id → same position across runs)", () => {
    const nodes = [makeNode({ id: "stable", role: "fact" })];
    const p1 = placeNodes(nodes);
    const p2 = placeNodes(nodes);
    expect(p1[0].position.x).toBe(p2[0].position.x);
    expect(p1[0].position.z).toBe(p2[0].position.z);
  });

  it("drops structure / summary roles (no tier)", () => {
    const placed = placeNodes([
      makeNode({ id: "a", role: "fact" }),
      makeNode({ id: "b", role: "structure" }),
      makeNode({ id: "c", role: "summary" }),
    ]);
    expect(placed.map((p) => p.id).sort()).toEqual(["a"]);
  });
});
