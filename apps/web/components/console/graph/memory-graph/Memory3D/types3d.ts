import type { Vector3 } from "three";
import type { GraphNode, Role } from "../types";

export interface PlacedNode {
  id: string;
  node: GraphNode;
  position: Vector3;
  ringY: number;
}

export interface CameraAnim {
  fromTarget: Vector3;
  toTarget: Vector3;
  fromPos: Vector3;
  toPos: Vector3;
  t: number;
  dur: number;
}

export interface SceneHandle {
  focusOn: (nodeId: string | null) => void;
  rearrange: () => void;
  zoomIn: () => void;
  zoomOut: () => void;
  fit: () => void;
  toggleAutoRotate: () => void;
  getProjectedScreenPos: (nodeId: string) => { x: number; y: number } | null;
}

export type RoleGlyph = Record<Role, string>;
