import { describe, expect, it } from "vitest";
import {
  TIER_RADIUS, CARD_W, CARD_H, CARD_WORLD_W,
  CAMERA_DEFAULT_POS, CAMERA_DEFAULT_FOV, ORBIT_MIN_DIST, ORBIT_MAX_DIST,
  FOG_NEAR, FOG_FAR, TIER_VISIBLE_ROLES, MASTERY_Y_RANGE,
} from "@/components/console/graph/memory-graph/Memory3D/constants3d";

describe("3D constants", () => {
  it("ring radii match prototype + spec", () => {
    expect(TIER_RADIUS.subject).toBe(95);
    expect(TIER_RADIUS.concept).toBe(175);
    expect(TIER_RADIUS.fact).toBe(245);
  });

  it("visible roles cover the 3 roles that reach the frontend", () => {
    expect(TIER_VISIBLE_ROLES.sort()).toEqual(["concept", "fact", "subject"].sort());
  });

  it("card sizes match prototype (320x200, world width 58)", () => {
    expect(CARD_W).toBe(320);
    expect(CARD_H).toBe(200);
    expect(CARD_WORLD_W).toBe(58);
  });

  it("camera defaults", () => {
    expect(CAMERA_DEFAULT_POS).toEqual([0, 110, 360]);
    expect(CAMERA_DEFAULT_FOV).toBe(45);
    expect(ORBIT_MIN_DIST).toBe(140);
    expect(ORBIT_MAX_DIST).toBe(820);
  });

  it("fog distances", () => {
    expect(FOG_NEAR).toBe(380);
    expect(FOG_FAR).toBe(1100);
  });

  it("mastery Y range is 140 units", () => {
    expect(MASTERY_Y_RANGE).toBe(140);
  });
});
