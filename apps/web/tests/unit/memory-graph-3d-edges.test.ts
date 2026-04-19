import { describe, expect, it } from "vitest";
import { Vector3 } from "three";
import { buildEdgeGeometry } from "@/components/console/graph/memory-graph/Memory3D/edges3d";
import { buildGround } from "@/components/console/graph/memory-graph/Memory3D/ground";

describe("buildEdgeGeometry", () => {
  it("returns a bezier curve with lifted midpoint", () => {
    const geo = buildEdgeGeometry(new Vector3(0, 0, 0), new Vector3(100, 0, 0));
    const pts = geo.attributes.position;
    // getPoints(24) samples along the curve; concrete count depends on three version.
    expect(pts.count).toBeGreaterThanOrEqual(5);
    // Midpoint Y of a quadratic Bezier with control +14 lift = 14/2 = 7 (not the control point).
    const midIdx = Math.floor(pts.count / 2);
    expect(pts.getY(midIdx)).toBeGreaterThan(3);
  });
});

describe("buildGround", () => {
  it("returns a Group with disc + rings + spokes + column", () => {
    const group = buildGround();
    expect(group.type).toBe("Group");
    const lineCount = group.children.filter((c) => c.type === "Line").length;
    // 3 rings + 12 spokes + 1 Y column = 16
    expect(lineCount).toBeGreaterThanOrEqual(16);
  });
});
