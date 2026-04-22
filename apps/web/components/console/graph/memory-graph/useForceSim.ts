"use client";

import { useEffect, useRef, useState } from "react";
import type { ForceParams, GraphEdge, GraphNode, Position } from "./types";
import { FORCE_PARAMS } from "./constants";

const PAD = 24;

export function seedCircle(nodes: GraphNode[], width: number, height: number): Map<string, Position> {
  const cx = width / 2;
  const cy = height / 2;
  const r = Math.min(width, height) * 0.35;
  const out = new Map<string, Position>();
  nodes.forEach((n, i) => {
    const a = (i / Math.max(1, nodes.length)) * Math.PI * 2;
    out.set(n.id, {
      x: cx + Math.cos(a) * r,
      y: cy + Math.sin(a) * r,
      vx: 0, vy: 0, fx: null, fy: null,
    });
  });
  return out;
}

export function buildForceSimSignature(
  nodes: GraphNode[],
  edges: GraphEdge[],
  width: number,
  height: number,
): string {
  const nodeSig = nodes.map((node) => node.id).sort().join("|");
  const edgeSig = edges
    .map((edge) => {
      const [a, b] = edge.a < edge.b ? [edge.a, edge.b] : [edge.b, edge.a];
      return `${a}~${b}~${edge.rel}~${edge.w ?? 1}`;
    })
    .sort()
    .join("|");
  return `${width}:${height}:${nodeSig}:${edgeSig}`;
}

interface TickInput {
  positions: Map<string, Position>;
  nodes: GraphNode[];
  edges: GraphEdge[];
  width: number;
  height: number;
  alpha: number;
  params: ForceParams;
}

interface TickResult {
  alpha: number;
}

export function tickOnce(input: TickInput): TickResult {
  const { positions, nodes, edges, width, height, alpha, params } = input;

  // 1) N² charge
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const pa = positions.get(nodes[i].id);
      const pb = positions.get(nodes[j].id);
      if (!pa || !pb) continue;
      const dx = pb.x - pa.x;
      const dy = pb.y - pa.y;
      const distSq = dx * dx + dy * dy || 0.01;
      const force = (params.charge * alpha) / distSq;
      const dist = Math.sqrt(distSq);
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      pa.vx -= fx;
      pa.vy -= fy;
      pb.vx += fx;
      pb.vy += fy;
    }
  }

  // 2) link spring
  for (const e of edges) {
    const pa = positions.get(e.a);
    const pb = positions.get(e.b);
    if (!pa || !pb) continue;
    const dx = pb.x - pa.x;
    const dy = pb.y - pa.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
    const delta = dist - params.linkDistance;
    const strength = params.linkStrength * (e.w || 1) * alpha;
    const fx = (dx / dist) * delta * strength;
    const fy = (dy / dist) * delta * strength;
    pa.vx += fx;
    pa.vy += fy;
    pb.vx -= fx;
    pb.vy -= fy;
  }

  // 3) center gravity
  const cx = width / 2;
  const cy = height / 2;
  for (const n of nodes) {
    const p = positions.get(n.id);
    if (!p) continue;
    p.vx += (cx - p.x) * params.centerStrength * alpha;
    p.vy += (cy - p.y) * params.centerStrength * alpha;
  }

  // 4) collision (2× radius)
  const collideDist = params.collide * 2;
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const pa = positions.get(nodes[i].id);
      const pb = positions.get(nodes[j].id);
      if (!pa || !pb) continue;
      const dx = pb.x - pa.x;
      const dy = pb.y - pa.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
      if (dist < collideDist) {
        const overlap = (collideDist - dist) / 2;
        const nx = dx / dist;
        const ny = dy / dist;
        pa.x -= nx * overlap;
        pa.y -= ny * overlap;
        pb.x += nx * overlap;
        pb.y += ny * overlap;
      }
    }
  }

  // 5) integrate with damping + clamp; fx/fy pinned
  for (const n of nodes) {
    const p = positions.get(n.id);
    if (!p) continue;
    if (p.fx != null && p.fy != null) {
      p.x = p.fx;
      p.y = p.fy;
      p.vx = 0;
      p.vy = 0;
      continue;
    }
    p.vx *= params.damping;
    p.vy *= params.damping;
    p.x += p.vx;
    p.y += p.vy;
    if (p.x < PAD) p.x = PAD;
    if (p.x > width - PAD) p.x = width - PAD;
    if (p.y < PAD) p.y = PAD;
    if (p.y > height - PAD) p.y = height - PAD;
  }

  return { alpha: alpha * params.alphaDecay };
}

export function shouldStop(alpha: number, params: ForceParams): boolean {
  return alpha < params.alphaMin;
}

interface UseForceSimOptions {
  nodes: GraphNode[];
  edges: GraphEdge[];
  width: number;
  height: number;
  params?: ForceParams;
}

export interface ForceSimHandle {
  getPositions: () => Map<string, Position>;
  setFixed: (id: string, x: number | null, y: number | null) => void;
  reheat: (alpha?: number) => void;
  rearrange: () => void;
}

export function useForceSim(opts: UseForceSimOptions): ForceSimHandle {
  const params = opts.params ?? FORCE_PARAMS;
  const [initialPositions] = useState(() => seedCircle(opts.nodes, opts.width, opts.height));
  const positionsRef = useRef<Map<string, Position>>(initialPositions);
  const alphaRef = useRef<number>(params.alphaInit);
  const rafRef = useRef<number | null>(null);
  const [, forceRender] = useState(0);

  // RAF loop
  useEffect(() => {
    const loop = () => {
      if (shouldStop(alphaRef.current, params)) {
        rafRef.current = null;
        return;
      }
      const { alpha } = tickOnce({
        positions: positionsRef.current,
        nodes: opts.nodes,
        edges: opts.edges,
        width: opts.width,
        height: opts.height,
        alpha: alphaRef.current,
        params,
      });
      alphaRef.current = alpha;
      forceRender((v) => (v + 1) % 1_000_000);
      rafRef.current = requestAnimationFrame(loop);
    };
    if (rafRef.current == null) rafRef.current = requestAnimationFrame(loop);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    };
  }, [opts.nodes, opts.edges, opts.width, opts.height, params]);

  return {
    getPositions: () => positionsRef.current,
    setFixed: (id, x, y) => {
      const p = positionsRef.current.get(id);
      if (!p) return;
      p.fx = x;
      p.fy = y;
    },
    reheat: (alpha = 0.3) => {
      alphaRef.current = alpha;
      if (rafRef.current == null) {
        const loop = () => {
          if (shouldStop(alphaRef.current, params)) { rafRef.current = null; return; }
          const { alpha: a2 } = tickOnce({
            positions: positionsRef.current,
            nodes: opts.nodes, edges: opts.edges,
            width: opts.width, height: opts.height,
            alpha: alphaRef.current, params,
          });
          alphaRef.current = a2;
          forceRender((v) => (v + 1) % 1_000_000);
          rafRef.current = requestAnimationFrame(loop);
        };
        rafRef.current = requestAnimationFrame(loop);
      }
    },
    rearrange: () => {
      positionsRef.current = seedCircle(opts.nodes, opts.width, opts.height);
      alphaRef.current = params.alphaInit;
      forceRender((v) => (v + 1) % 1_000_000);
    },
  };
}
