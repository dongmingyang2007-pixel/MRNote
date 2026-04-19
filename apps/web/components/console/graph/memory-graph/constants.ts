import type { EdgeStyle, ForceParams, Role, RoleStyle, ViewportState, ViewportBounds } from "./types";

export const ROLE_STYLE: Record<Role, RoleStyle> = {
  fact:      { fill: "#dbeafe", stroke: "#2563eb", text: "#1e40af", dot: "#2563eb" },
  structure: { fill: "#ede9fe", stroke: "#7c3aed", text: "#5b21b6", dot: "#7c3aed" },
  subject:   { fill: "#d1fae5", stroke: "#10b981", text: "#047857", dot: "#10b981" },
  concept:   { fill: "#ccfbf1", stroke: "#0d9488", text: "#0f766e", dot: "#0d9488" },
  summary:   { fill: "#fef3c7", stroke: "#f59e0b", text: "#b45309", dot: "#f59e0b" },
};

export const EDGE_STYLE: Record<string, EdgeStyle> = {
  parent:       { stroke: "#64748b", width: 1.4, style: "solid" },
  center:       { stroke: "#64748b", width: 1.4, style: "solid" },
  supersedes:   { stroke: "#ef4444", width: 1.2, style: "solid" },
  conflict:     { stroke: "#ef4444", width: 1.2, style: "dashed" },
  prerequisite: { stroke: "#2563eb", width: 1.2, style: "solid" },
  evidence:     { stroke: "#10b981", width: 1.2, style: "solid" },
  summary:      { stroke: "#f59e0b", width: 1.2, style: "dashed" },
  related:      { stroke: "#94a3b8", width: 1.0, style: "solid" },
  auto:         { stroke: "#94a3b8", width: 1.0, style: "solid" },
  manual:       { stroke: "#94a3b8", width: 1.0, style: "solid" },
  file:         { stroke: "#6366f1", width: 1.0, style: "dashed" },
  __fallback__: { stroke: "#94a3b8", width: 1.0, style: "solid" },
};

export const FORCE_PARAMS: ForceParams = {
  linkDistance: 90,
  linkStrength: 0.06,
  charge: -340,
  centerStrength: 0.015,
  collide: 38,
  damping: 0.82,
  alphaInit: 1,
  alphaDecay: 0.985,
  alphaMin: 0.001,
};

export const VIEWPORT_DEFAULTS: ViewportState & ViewportBounds = {
  k: 1, tx: 0, ty: 0, kMin: 0.4, kMax: 2.5,
};

export const FOCUS_PRIMARY = "#0D9488";
export const OPACITY_NORMAL_NODE = 1;
export const OPACITY_NORMAL_EDGE = 0.65;
export const OPACITY_DIM_NODE = 0.38;
export const OPACITY_DIM_EDGE = 0.15;
export const OPACITY_SEARCH_MISS = 0.18;
export const TRANSITION_MS = 200;
export const LABEL_MAX_CHARS = 28;
