import type { Role } from "../types";
import type { RoleGlyph } from "./types3d";

/** Tier ring radii. subject innermost, fact outermost. structure/summary never placed (backend filters). */
export const TIER_RADIUS: Record<Role, number> = {
  subject:   95,
  concept:   175,
  fact:      245,
  structure: 60,
  summary:   310,
};

export const RING_COLORS: Record<Role, number> = {
  subject:   0x10b981,
  concept:   0x0d9488,
  fact:      0x0d9488,
  structure: 0x7c3aed,
  summary:   0xf59e0b,
};

export const TIER_VISIBLE_ROLES: Role[] = ["subject", "concept", "fact"];

export const CARD_W = 320;
export const CARD_H = 200;
export const CARD_WORLD_W = 58;
export const CARD_WORLD_H = CARD_WORLD_W / (CARD_W / CARD_H);

export const CAMERA_DEFAULT_POS: [number, number, number] = [0, 110, 360];
export const CAMERA_DEFAULT_FOV = 45;
export const ORBIT_MIN_DIST = 140;
export const ORBIT_MAX_DIST = 820;
export const ORBIT_POLAR_MIN = Math.PI * 0.15;
export const ORBIT_POLAR_MAX = Math.PI * 0.52;

export const FOG_NEAR = 380;
export const FOG_FAR = 1100;
export const FOG_FALLBACK_COLOR = 0xf8fafc;

export const GROUND_Y = -90;
export const MASTERY_Y_RANGE = 140;
export const EDGE_ARC_LIFT = 14;

export const ROLE_GLYPH: RoleGlyph = {
  fact: "◇",
  structure: "▣",
  subject: "⬢",
  concept: "◈",
  summary: "▤",
};

export const CAMERA_ANIM_DUR = 0.9;
