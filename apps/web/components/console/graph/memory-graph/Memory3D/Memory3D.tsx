"use client";

import { useEffect, useRef, useState } from "react";
import { useThreeScene } from "./useThreeScene";
import { Tooltip3d } from "./Tooltip3d";
import { CameraControlsHud } from "./CameraControlsHud";
import type { GraphEdge, GraphNode } from "../types";

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  hoverId: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string | null) => void;
}

export function Memory3D({ nodes, edges, selectedId, hoverId, onHover, onSelect }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const [autoRot, setAutoRot] = useState(false);
  const [zoomPct, setZoomPct] = useState(100);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null);

  const handle = useThreeScene({ mountRef, nodes, edges, onHover, onSelect });

  useEffect(() => {
    handle.focusOn(selectedId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  useEffect(() => {
    if (!hoverId) { setTooltipPos(null); return; }
    let rafId = 0;
    const update = () => {
      const pos = handle.getProjectedScreenPos(hoverId);
      if (pos) setTooltipPos(pos);
      rafId = requestAnimationFrame(update);
    };
    rafId = requestAnimationFrame(update);
    return () => cancelAnimationFrame(rafId);
  }, [hoverId, handle]);

  const hoveredNode = hoverId ? nodes.find((n) => n.id === hoverId) : null;

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <div
        ref={mountRef}
        data-testid="mg3d-mount"
        style={{ position: "absolute", inset: 0, background: "var(--bg-base, #f8fafc)" }}
      />
      {hoveredNode && tooltipPos && (
        <Tooltip3d node={hoveredNode} x={tooltipPos.x} y={tooltipPos.y} />
      )}
      <CameraControlsHud
        zoomPct={zoomPct}
        autoRotating={autoRot}
        onZoomIn={() => { handle.zoomIn(); setZoomPct((z) => Math.min(250, z * 1.2)); }}
        onZoomOut={() => { handle.zoomOut(); setZoomPct((z) => Math.max(40, z / 1.2)); }}
        onFit={() => { handle.fit(); setZoomPct(100); }}
        onToggleAutoRotate={() => { handle.toggleAutoRotate(); setAutoRot((v) => !v); }}
      />
    </div>
  );
}
