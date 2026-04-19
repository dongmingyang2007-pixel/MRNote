import {
  BufferGeometry, QuadraticBezierCurve3, Vector3,
  LineBasicMaterial, Line, Color,
} from "three";
import { EDGE_STYLE } from "../constants";
import { EDGE_ARC_LIFT } from "./constants3d";

export function buildEdgeGeometry(a: Vector3, b: Vector3): BufferGeometry {
  const mid = new Vector3(
    (a.x + b.x) / 2,
    (a.y + b.y) / 2 + EDGE_ARC_LIFT,
    (a.z + b.z) / 2,
  );
  const curve = new QuadraticBezierCurve3(a, mid, b);
  const pts = curve.getPoints(24);
  return new BufferGeometry().setFromPoints(pts);
}

export interface EdgeMesh {
  line: Line;
  baseColor: Color;
  rel: string;
}

export function buildEdgeLine(a: Vector3, b: Vector3, rel: string, focused: boolean): EdgeMesh {
  const geo = buildEdgeGeometry(a, b);
  const style = EDGE_STYLE[rel] ?? EDGE_STYLE.__fallback__;
  const baseColor = new Color(style.stroke);
  const mat = new LineBasicMaterial({
    color: focused ? new Color("#0D9488") : baseColor,
    transparent: true, opacity: focused ? 0.85 : 0.42, depthWrite: false,
  });
  const line = new Line(geo, mat);
  return { line, baseColor, rel };
}
