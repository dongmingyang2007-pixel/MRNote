import type { MemoryNode as BackendMemoryNode } from "@/hooks/useGraphData";

export type Role = "fact" | "structure" | "subject" | "concept" | "summary";

export interface GraphNode {
  id: string;
  role: Role;
  label: string;
  conf: number;           // 0..1 (backend confidence ?? 0.5)
  reuse: number;          // metadata_json.retrieval_count ?? 0
  lastUsed: string | null; // humanized: "2h" / "3d" / null
  pinned: boolean;
  source: string | null;
  raw: BackendMemoryNode;
}

export interface GraphEdge {
  a: string;              // source_memory_id
  b: string;              // target_memory_id
  rel: string;            // backend edge_type verbatim (fallback-tolerant)
  w: number;              // strength
}

export interface ViewportState {
  k: number;
  tx: number;
  ty: number;
}

export interface ViewportBounds {
  kMin: number;
  kMax: number;
}

export interface RoleStyle {
  fill: string;
  stroke: string;
  text: string;
  dot: string;
}

export interface EdgeStyle {
  stroke: string;
  width: number;
  style: "solid" | "dashed";
}

export interface ForceParams {
  linkDistance: number;
  linkStrength: number;
  charge: number;
  centerStrength: number;
  collide: number;
  damping: number;
  alphaInit: number;
  alphaDecay: number;
  alphaMin: number;
}

export type Position = { x: number; y: number; vx: number; vy: number; fx: number | null; fy: number | null };
