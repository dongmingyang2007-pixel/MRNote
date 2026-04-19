"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Toolbar } from "./Toolbar";
import { GraphCanvas, nextZoom } from "./GraphCanvas";
import { LegendAndZoom } from "./LegendAndZoom";
import { NodeDetailDrawer, type DrawerNeighbor } from "./NodeDetailDrawer";
import { ListView } from "./ListView";
import { VIEWPORT_DEFAULTS } from "./constants";
import type { GraphEdge, GraphNode, Role, ViewportState } from "./types";
import { useForceSim } from "./useForceSim";

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

const ALL_ROLES: Role[] = ["fact", "structure", "subject", "concept", "summary"];
const BOTTOM_SHEET_BREAKPOINT = 960;
const LEGEND_HIDE_BREAKPOINT = 720;

export function MemoryGraphView({ nodes, edges }: Props) {
  const [search, setSearch] = useState("");
  const [confMin, setConfMin] = useState(0.6);
  const [filters, setFilters] = useState<Record<Role, boolean>>(() =>
    Object.fromEntries(ALL_ROLES.map((r) => [r, true])) as Record<Role, boolean>,
  );
  const [view, setView] = useState<"graph" | "list">("graph");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [viewport, setViewport] = useState<ViewportState>({
    k: VIEWPORT_DEFAULTS.k, tx: VIEWPORT_DEFAULTS.tx, ty: VIEWPORT_DEFAULTS.ty,
  });
  const containerRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 800, h: 600 });
  const isNarrow = box.w < BOTTOM_SHEET_BREAKPOINT;
  const compactToolbar = box.w < LEGEND_HIDE_BREAKPOINT;

  // Resize observer → canvas dimensions (guard for jsdom which lacks ResizeObserver)
  useEffect(() => {
    if (!containerRef.current) return;
    if (typeof ResizeObserver === "undefined") return;
    const el = containerRef.current;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        setBox({ w: Math.max(300, Math.floor(width)), h: Math.max(200, Math.floor(height)) });
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Counts by role (applies confMin)
  const counts = useMemo(() => {
    const out = Object.fromEntries(ALL_ROLES.map((r) => [r, 0])) as Record<Role, number>;
    for (const n of nodes) if (n.conf >= confMin) out[n.role]++;
    return out;
  }, [nodes, confMin]);

  // Effective nodes (applies confMin, but NOT role-filter — role-filter is opacity-based to keep layout stable)
  const effectiveNodes = useMemo(() => nodes.filter((n) => n.conf >= confMin), [nodes, confMin]);
  const effectiveIds = useMemo(() => new Set(effectiveNodes.map((n) => n.id)), [effectiveNodes]);
  const effectiveEdges = useMemo(
    () => edges.filter((e) => effectiveIds.has(e.a) && effectiveIds.has(e.b)),
    [edges, effectiveIds],
  );

  // Search matches: empty set = not searching
  const searchMatches = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return new Set<string>();
    const out = new Set<string>();
    for (const n of effectiveNodes) {
      if (n.label.toLowerCase().includes(q)) out.add(n.id);
    }
    return out;
  }, [effectiveNodes, search]);

  const selectedNode = useMemo(
    () => effectiveNodes.find((n) => n.id === selectedId) ?? null,
    [effectiveNodes, selectedId],
  );

  const drawerNeighbors: DrawerNeighbor[] = useMemo(() => {
    if (!selectedNode) return [];
    const out: DrawerNeighbor[] = [];
    for (const e of effectiveEdges) {
      if (e.a === selectedNode.id) {
        const nb = effectiveNodes.find((n) => n.id === e.b);
        if (nb) out.push({ id: nb.id, rel: e.rel, node: nb });
      } else if (e.b === selectedNode.id) {
        const nb = effectiveNodes.find((n) => n.id === e.a);
        if (nb) out.push({ id: nb.id, rel: e.rel, node: nb });
      }
    }
    return out;
  }, [selectedNode, effectiveEdges, effectiveNodes]);

  // Single sim instance; positions flow down to GraphCanvas as a prop
  const canvasWidth = box.w - (isNarrow ? 0 : (selectedId ? 300 : 0));
  const canvasHeight = box.h - 52 - (isNarrow && selectedId ? Math.floor(box.h * 0.6) : 0);
  const sim = useForceSim({
    nodes: effectiveNodes,
    edges: effectiveEdges,
    width: canvasWidth,
    height: canvasHeight,
  });
  const positions = sim.getPositions();

  const handleViewport = useCallback((v: ViewportState) => setViewport(v), []);
  const handleFit = useCallback(() => setViewport({ k: 1, tx: 0, ty: 0 }), []);
  const handleZoomIn = useCallback(() => setViewport((v) => ({ ...v, k: nextZoom(v.k, "in") })), []);
  const handleZoomOut = useCallback(() => setViewport((v) => ({ ...v, k: nextZoom(v.k, "out") })), []);

  const toggleFilter = useCallback(
    (role: Role) => setFilters((f) => ({ ...f, [role]: !f[role] })),
    [],
  );

  const handleDragStart = useCallback((id: string) => {
    void id;
  }, []);
  const handleDrag = useCallback((id: string, x: number, y: number) => {
    sim.setFixed(id, x, y);
  }, [sim]);
  const handleDragEnd = useCallback((id: string) => {
    sim.setFixed(id, null, null);
    sim.reheat(0.3);
  }, [sim]);

  const handleRearrange = useCallback(() => {
    sim.rearrange();
    handleFit();
  }, [sim, handleFit]);

  return (
    <div
      ref={containerRef}
      className="mg-root"
      style={{
        display: "flex", flexDirection: isNarrow ? "column" : "row",
        height: "100%", width: "100%", overflow: "hidden",
        background: "var(--bg-base, #f8fafc)",
      }}
    >
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, minHeight: 0 }}>
        <Toolbar
          search={search} confMin={confMin} filters={filters} view={view} counts={counts}
          onSearch={setSearch} onConfMin={setConfMin} onToggleFilter={toggleFilter}
          onRearrange={handleRearrange} onFit={handleFit} onViewChange={setView}
          compact={compactToolbar}
        />
        <div style={{ position: "relative", flex: 1, minHeight: 0 }}>
          {view === "graph" ? (
            <>
              <GraphCanvas
                nodes={effectiveNodes} edges={effectiveEdges}
                positions={positions}
                width={canvasWidth}
                height={canvasHeight}
                viewport={viewport}
                hoverId={hoverId} selectedId={selectedId} searchMatches={searchMatches}
                filters={filters}
                onViewportChange={handleViewport}
                onHover={setHoverId}
                onSelect={setSelectedId}
                onDragStart={handleDragStart}
                onDrag={handleDrag}
                onDragEnd={handleDragEnd}
              />
              <LegendAndZoom
                zoom={viewport.k}
                onZoomIn={handleZoomIn} onZoomOut={handleZoomOut} onFit={handleFit}
                showLegend={!compactToolbar}
              />
            </>
          ) : (
            <ListView nodes={effectiveNodes} selectedId={selectedId} onSelect={setSelectedId} />
          )}
        </div>
      </div>
      {selectedNode && (
        <NodeDetailDrawer
          node={selectedNode}
          neighbors={drawerNeighbors}
          onSelectNeighbor={(id) => setSelectedId(id)}
          onClose={() => setSelectedId(null)}
          layout={isNarrow ? "bottomSheet" : "side"}
        />
      )}
    </div>
  );
}
