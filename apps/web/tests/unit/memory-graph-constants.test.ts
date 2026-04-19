import { describe, expect, it } from "vitest";
import {
  ROLE_STYLE,
  EDGE_STYLE,
  FORCE_PARAMS,
  VIEWPORT_DEFAULTS,
} from "@/components/console/graph/memory-graph/constants";
import type { Role } from "@/components/console/graph/memory-graph/types";

describe("memory-graph constants", () => {
  it("exposes one ROLE_STYLE entry per role (5 total)", () => {
    const roles: Role[] = ["fact", "structure", "subject", "concept", "summary"];
    expect(Object.keys(ROLE_STYLE).sort()).toEqual([...roles].sort());
    for (const r of roles) {
      expect(ROLE_STYLE[r]).toMatchObject({
        fill: expect.any(String),
        stroke: expect.any(String),
        text: expect.any(String),
        dot: expect.any(String),
      });
    }
  });

  it("exposes one EDGE_STYLE entry per backend edge_type (11 total, plus fallback)", () => {
    const expected = [
      "parent", "center", "supersedes", "conflict", "prerequisite",
      "evidence", "summary", "related", "auto", "manual", "file",
      "__fallback__",
    ];
    expect(Object.keys(EDGE_STYLE).sort()).toEqual([...expected].sort());
    for (const key of expected) {
      expect(EDGE_STYLE[key]).toMatchObject({
        stroke: expect.any(String),
        width: expect.any(Number),
        style: expect.stringMatching(/^(solid|dashed)$/),
      });
    }
  });

  it("FORCE_PARAMS matches UPGRADE_GUIDE.md §3.2", () => {
    expect(FORCE_PARAMS).toEqual({
      linkDistance: 90,
      linkStrength: 0.06,
      charge: -340,
      centerStrength: 0.015,
      collide: 38,
      damping: 0.82,
      alphaInit: 1,
      alphaDecay: 0.985,
      alphaMin: 0.001,
    });
  });

  it("VIEWPORT_DEFAULTS has identity transform + MIN/MAX zoom", () => {
    expect(VIEWPORT_DEFAULTS).toEqual({
      k: 1, tx: 0, ty: 0, kMin: 0.4, kMax: 2.5,
    });
  });
});
