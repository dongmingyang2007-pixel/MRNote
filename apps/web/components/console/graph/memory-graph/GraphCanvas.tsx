"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import {
  ROLE_STYLE,
  EDGE_STYLE,
  FOCUS_PRIMARY,
  OPACITY_NORMAL_NODE,
  OPACITY_NORMAL_EDGE,
  OPACITY_DIM_NODE,
  OPACITY_DIM_EDGE,
  OPACITY_SEARCH_MISS,
  TRANSITION_MS,
  VIEWPORT_DEFAULTS,
} from "./constants";
import type { GraphEdge, GraphNode, Position, Role, ViewportState } from "./types";

const ZOOM_STEP = 1.2;

export function clampZoom(k: number, bounds = VIEWPORT_DEFAULTS): number {
  return Math.max(bounds.kMin, Math.min(bounds.kMax, k));
}

export function nextZoom(k: number, dir: "in" | "out", bounds = VIEWPORT_DEFAULTS): number {
  return clampZoom(dir === "in" ? k * ZOOM_STEP : k / ZOOM_STEP, bounds);
}

function nodeRadius(n: GraphNode): number {
  const base = 8 + Math.max(-0.7, n.conf - 0.7) * 14;
  return n.pinned ? base + 3 : base;
}

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
  positions: Map<string, Position>;
  width: number;
  height: number;
  viewport: ViewportState;
  hoverId: string | null;
  selectedId: string | null;
  searchMatches: Set<string>;          // empty set = search inactive
  filters: Record<Role, boolean>;
  onViewportChange: (v: ViewportState) => void;
  onHover: (id: string | null) => void;
  onSelect: (id: string | null) => void;
  onDragStart: (id: string) => void;
  onDrag: (id: string, x: number, y: number) => void;
  onDragEnd: (id: string) => void;
}

export function GraphCanvas(p: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ id: string | null; panStart: { x: number; y: number; tx: number; ty: number } | null }>({
    id: null, panStart: null,
  });
  const [isPanning, setIsPanning] = useState(false);

  // Convert screen (client) coords → SVG user-space under current viewport transform
  const toWorld = useCallback((clientX: number, clientY: number) => {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };
    const rect = svg.getBoundingClientRect();
    const sx = clientX - rect.left;
    const sy = clientY - rect.top;
    return {
      x: (sx - p.viewport.tx) / p.viewport.k,
      y: (sy - p.viewport.ty) / p.viewport.k,
    };
  }, [p.viewport.k, p.viewport.tx, p.viewport.ty]);

  const handleWheel: React.WheelEventHandler<SVGSVGElement> = useCallback((e) => {
    e.preventDefault();
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
    const kNext = clampZoom(p.viewport.k * factor);
    const tx = cx - ((cx - p.viewport.tx) * kNext) / p.viewport.k;
    const ty = cy - ((cy - p.viewport.ty) * kNext) / p.viewport.k;
    p.onViewportChange({ k: kNext, tx, ty });
  }, [p]);

  const handleBackgroundPointerDown: React.PointerEventHandler<SVGRectElement> = (e) => {
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    dragRef.current.panStart = {
      x: e.clientX, y: e.clientY, tx: p.viewport.tx, ty: p.viewport.ty,
    };
    setIsPanning(true);
  };
  const handleBackgroundPointerMove: React.PointerEventHandler<SVGRectElement> = (e) => {
    const s = dragRef.current.panStart;
    if (!s) return;
    p.onViewportChange({
      k: p.viewport.k,
      tx: s.tx + (e.clientX - s.x),
      ty: s.ty + (e.clientY - s.y),
    });
  };
  const handleBackgroundPointerUp: React.PointerEventHandler<SVGRectElement> = (e) => {
    try { (e.currentTarget as Element).releasePointerCapture(e.pointerId); } catch { /* not captured */ }
    dragRef.current.panStart = null;
    setIsPanning(false);
  };
  const handleBackgroundClick: React.MouseEventHandler<SVGRectElement> = () => {
    p.onSelect(null);
  };

  const onNodePointerDown = (id: string, e: React.PointerEvent<SVGGElement>) => {
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    dragRef.current.id = id;
    p.onDragStart(id);
  };
  const onNodePointerMove = (id: string, e: React.PointerEvent<SVGGElement>) => {
    if (dragRef.current.id !== id) return;
    const { x, y } = toWorld(e.clientX, e.clientY);
    p.onDrag(id, x, y);
  };
  const onNodePointerUp = (id: string, e: React.PointerEvent<SVGGElement>) => {
    if (dragRef.current.id !== id) return;
    try { (e.currentTarget as Element).releasePointerCapture(e.pointerId); } catch { /* ignore */ }
    dragRef.current.id = null;
    p.onDragEnd(id);
  };

  // Focus = hover (preferred) else selection
  const focusId = p.hoverId ?? p.selectedId;
  // 1-hop set for focus dimming
  const neighbors = useMemo(() => {
    if (!focusId) return new Set<string>();
    const s = new Set<string>([focusId]);
    for (const e of p.edges) {
      if (e.a === focusId) s.add(e.b);
      if (e.b === focusId) s.add(e.a);
    }
    return s;
  }, [focusId, p.edges]);

  const positions = p.positions;

  return (
    <svg
      ref={svgRef}
      data-testid="mg-svg"
      width={p.width}
      height={p.height}
      onWheel={handleWheel}
      style={{ display: "block", userSelect: "none", cursor: isPanning ? "grabbing" : "default" }}
    >
      <defs>
        <filter id="mg-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="3" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      <rect
        data-testid="mg-bg"
        x={0} y={0} width={p.width} height={p.height}
        fill="transparent"
        onPointerDown={handleBackgroundPointerDown}
        onPointerMove={handleBackgroundPointerMove}
        onPointerUp={handleBackgroundPointerUp}
        onClick={handleBackgroundClick}
      />
      <g transform={`translate(${p.viewport.tx},${p.viewport.ty}) scale(${p.viewport.k})`}>
        {/* Edges */}
        {p.edges.map((e, i) => {
          const pa = positions.get(e.a);
          const pb = positions.get(e.b);
          if (!pa || !pb) return null;
          const style = EDGE_STYLE[e.rel] ?? EDGE_STYLE.__fallback__;
          const focused = focusId != null && (e.a === focusId || e.b === focusId);
          const dim = focusId != null && !focused;
          const stroke = focused ? FOCUS_PRIMARY : style.stroke;
          const opacity = dim ? OPACITY_DIM_EDGE : OPACITY_NORMAL_EDGE;
          const mx = (pa.x + pb.x) / 2;
          const my = (pa.y + pb.y) / 2;
          return (
            <g key={`${e.a}-${e.b}-${i}`}>
              <line
                x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y}
                stroke={stroke} strokeWidth={focused ? style.width + 0.8 : style.width}
                strokeDasharray={style.style === "dashed" ? "4 3" : undefined}
                opacity={opacity}
                style={{ transition: `opacity ${TRANSITION_MS}ms` }}
              />
              {focused && (
                <g transform={`translate(${mx},${my})`}>
                  <rect x={-28} y={-9} width={56} height={18} rx={9} ry={9}
                    fill="#fff" stroke={FOCUS_PRIMARY} strokeWidth={1} />
                  <text x={0} y={3} textAnchor="middle" fontFamily="monospace" fontSize={9.5} fill={FOCUS_PRIMARY}>
                    {e.rel}
                  </text>
                </g>
              )}
            </g>
          );
        })}

        {/* Nodes */}
        {p.nodes.map((n) => {
          const pos = positions.get(n.id);
          if (!pos) return null;
          const style = ROLE_STYLE[n.role];
          const r = nodeRadius(n);
          const isFocus = n.id === focusId;
          const r2 = isFocus ? r + 3 : r;
          let opacity = OPACITY_NORMAL_NODE;
          if (focusId != null && !neighbors.has(n.id)) opacity = OPACITY_DIM_NODE;
          if (p.searchMatches.size > 0 && !p.searchMatches.has(n.id)) opacity = OPACITY_SEARCH_MISS;
          const hiddenByFilter = !p.filters[n.role];
          if (hiddenByFilter) opacity = 0;
          return (
            <g
              key={n.id}
              data-testid={`mg-node-${n.id}`}
              transform={`translate(${pos.x},${pos.y})`}
              onPointerEnter={() => !hiddenByFilter && p.onHover(n.id)}
              onPointerLeave={() => p.onHover(null)}
              onPointerDown={(e) => !hiddenByFilter && onNodePointerDown(n.id, e)}
              onPointerMove={(e) => onNodePointerMove(n.id, e)}
              onPointerUp={(e) => onNodePointerUp(n.id, e)}
              onClick={(e) => { e.stopPropagation(); if (!hiddenByFilter) p.onSelect(n.id); }}
              style={{ cursor: "pointer", transition: `opacity ${TRANSITION_MS}ms` }}
              opacity={opacity}
            >
              {n.pinned && (
                <circle r={r2 + 4} fill="none" stroke={style.stroke}
                  strokeWidth={1} strokeDasharray="2 2" opacity={0.6} filter="url(#mg-glow)" />
              )}
              <circle r={r2} fill={style.fill} stroke={style.stroke} strokeWidth={isFocus ? 2 : 1.4} />
              <text y={r2 + 12} textAnchor="middle" fontSize={11} fill={style.text}
                style={{ pointerEvents: "none" }}>
                {n.label}
              </text>
            </g>
          );
        })}
      </g>
    </svg>
  );
}
