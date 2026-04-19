import { Vector3 } from "three";
import type { GraphNode } from "../types";
import { TIER_RADIUS, TIER_VISIBLE_ROLES, GROUND_Y, MASTERY_Y_RANGE } from "./constants3d";
import type { PlacedNode } from "./types3d";

/** `conf * 0.5 + min(reuse/20, 1) * 0.3 + max(0, 1 - ageHrs/96) * 0.2`. */
export function masteryOf(n: GraphNode): number {
  const conf = typeof n.conf === "number" ? n.conf : 0.8;
  const reuseNormalized = Math.min((n.reuse ?? 0) / 20, 1);
  let ageHrs = 24;
  const lu = n.lastUsed;
  if (lu) {
    if (lu.endsWith("m")) ageHrs = parseInt(lu) / 60;
    else if (lu.endsWith("h")) ageHrs = parseInt(lu);
    else if (lu.endsWith("d")) ageHrs = parseInt(lu) * 24;
  }
  const recency = Math.max(0, 1 - ageHrs / 96);
  return conf * 0.5 + reuseNormalized * 0.3 + recency * 0.2;
}

function hashJitter(id: string) {
  const c = id.charCodeAt(1) || 0;
  return {
    angular: ((c * 37) % 13 - 6) * 0.02,
    radial: ((c % 5) - 2) * 4,
  };
}

export function placeNodes(nodes: GraphNode[]): PlacedNode[] {
  const visibleSet = new Set(TIER_VISIBLE_ROLES);
  const byRole = new Map<string, GraphNode[]>();
  for (const n of nodes) {
    if (!visibleSet.has(n.role)) continue;
    if (!byRole.has(n.role)) byRole.set(n.role, []);
    byRole.get(n.role)!.push(n);
  }
  for (const list of byRole.values()) list.sort((a, b) => a.id.localeCompare(b.id));

  const out: PlacedNode[] = [];
  for (const role of TIER_VISIBLE_ROLES) {
    const list = byRole.get(role) ?? [];
    const r = TIER_RADIUS[role];
    list.forEach((n, i) => {
      const { angular, radial } = hashJitter(n.id);
      const ang = (i / Math.max(1, list.length)) * Math.PI * 2 + angular;
      const rr = r + radial;
      const mastery = masteryOf(n);
      const y = (mastery - 0.5) * MASTERY_Y_RANGE;
      out.push({
        id: n.id,
        node: n,
        position: new Vector3(Math.cos(ang) * rr, y, Math.sin(ang) * rr),
        ringY: GROUND_Y + 1,
      });
    });
  }
  return out;
}
