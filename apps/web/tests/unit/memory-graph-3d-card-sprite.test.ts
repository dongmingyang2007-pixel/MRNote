import { describe, expect, it, beforeAll } from "vitest";
import { makeNodeCard, cardCacheKey } from "@/components/console/graph/memory-graph/Memory3D/cardSprite";
import type { GraphNode } from "@/components/console/graph/memory-graph/types";

// jsdom doesn't provide 2D canvas; install a minimal polyfill.
beforeAll(() => {
  const proto = HTMLCanvasElement.prototype;
  const origGetContext = proto.getContext;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  proto.getContext = function (type: string): any {
    if (type === "2d") {
      const noop = () => {};
      return {
        scale: noop, fillRect: noop, fillText: noop, measureText: () => ({ width: 40 }),
        beginPath: noop, moveTo: noop, lineTo: noop, closePath: noop, arc: noop,
        quadraticCurveTo: noop, stroke: noop, fill: noop,
        createLinearGradient: () => ({ addColorStop: noop }),
        createRadialGradient: () => ({ addColorStop: noop }),
        set fillStyle(_v: string) {}, get fillStyle() { return ""; },
        set strokeStyle(_v: string) {}, get strokeStyle() { return ""; },
        set lineWidth(_v: number) {}, get lineWidth() { return 1; },
        set lineCap(_v: string) {}, get lineCap() { return "butt"; },
        set textAlign(_v: string) {}, get textAlign() { return "left"; },
        set textBaseline(_v: string) {}, get textBaseline() { return "alphabetic"; },
        set font(_v: string) {}, get font() { return ""; },
      };
    }
    return origGetContext?.call(this, type);
  };
});

function n(over: Partial<GraphNode>): GraphNode {
  return {
    id: "n", role: "fact", label: "Alpha", conf: 0.85, reuse: 0,
    lastUsed: null, pinned: false, source: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    raw: {} as any, ...over,
  };
}

describe("cardCacheKey", () => {
  it("changes when display-affecting props change", () => {
    const keyBase = cardCacheKey(n({}));
    expect(keyBase).toBe(cardCacheKey(n({})));
    expect(cardCacheKey(n({ conf: 0.9 }))).not.toBe(keyBase);
    expect(cardCacheKey(n({ reuse: 3 }))).not.toBe(keyBase);
    expect(cardCacheKey(n({ pinned: true }))).not.toBe(keyBase);
  });
});

describe("makeNodeCard", () => {
  it("returns a Sprite with CanvasTexture material", () => {
    const sprite = makeNodeCard(n({}));
    expect(sprite.type).toBe("Sprite");
    expect(sprite.material).toBeDefined();
    expect(sprite.userData.cacheKey).toBe(cardCacheKey(n({})));
  });

  it("scales sprite to world size", () => {
    const sprite = makeNodeCard(n({}));
    expect(sprite.scale.x).toBeGreaterThan(0);
    expect(sprite.scale.y).toBeGreaterThan(0);
  });
});
