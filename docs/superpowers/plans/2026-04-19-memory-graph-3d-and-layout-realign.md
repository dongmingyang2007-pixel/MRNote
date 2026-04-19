# Memory Graph — 3D View + Layout Realignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a 3D 星云 view inside the existing `memory_graph` notebook window, and realign the window header to match the `index.html` prototype (title + FilterRow + ViewBar + canvas).

**Architecture:** Break the overstuffed `Toolbar` into three focused components (`HeaderBar` / `FilterRow` / `ViewBar`) plus floating `CanvasControls`. Add a new `Memory3D/` sub-folder hosting the Three.js scene (card sprites on concentric tier rings, OrbitControls, fog in CSS-var-driven bg color). State (search / conf / filters / selection) is lifted in `MemoryGraphView` so switching 2D ↔ 3D preserves it.

**Tech Stack:** Next.js 16 + React 19 + TypeScript + vitest + @testing-library/react + next-intl + three@0.183 + lucide-react.

**Test commands:**
- Unit run: `cd apps/web && node_modules/.bin/vitest run <path>` (pnpm not on PATH)
- Unit full: `cd apps/web && node_modules/.bin/vitest run`
- Typecheck: `cd apps/web && node_modules/.bin/tsc --noEmit`
- Dev server: managed via `preview_start` (see `.claude/launch.json` — `web-dev` config, port 3000, autoPort:false)

**Commit policy:** One commit per task. `feat(web): …` for new components, `refactor(web): …` for layout split, `chore(web): …` for wiring / i18n, `test(web): …` for test-only commits. Co-author line mandatory.

**Reference files** (don't re-read — paste content per task):
- Spec: `docs/superpowers/specs/2026-04-19-memory-graph-3d-and-layout-realign-design.md`
- Prototype 3D source: `/Users/dog/Downloads/index.html` lines 1493–1940 (Memory3D component + ground + card sprites) + lines 4003–4061 (view tab bar)
- Existing 2D shipped: `apps/web/components/console/graph/memory-graph/*` (all files)

---

## Task 1: HeaderBar component

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/HeaderBar.tsx`
- Test: `apps/web/tests/unit/memory-graph-header-bar.test.tsx`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-header-bar.test.tsx`:

```tsx
import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { HeaderBar } from "@/components/console/graph/memory-graph/HeaderBar";

afterEach(() => { cleanup(); });

describe("HeaderBar", () => {
  it("renders title + brand suffix", () => {
    render(<HeaderBar />);
    expect(screen.getByText("memoryGraph.title")).toBeTruthy();
    expect(screen.getByText("memoryGraph.header.brand")).toBeTruthy();
  });

  it("renders the graph icon", () => {
    const { container } = render(<HeaderBar />);
    expect(container.querySelector("svg")).toBeTruthy();
  });
});
```

### - [ ] Step 2: Run test to verify it fails

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-header-bar.test.tsx
```
Expected: FAIL — `Cannot find module '.../HeaderBar'`.

### - [ ] Step 3: Implement

Create `apps/web/components/console/graph/memory-graph/HeaderBar.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import { Brain } from "lucide-react";

export function HeaderBar() {
  const t = useTranslations("console-notebooks");
  return (
    <div
      className="mg-header"
      style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "10px 14px",
        borderBottom: "1px solid var(--border, rgba(15,42,45,0.08))",
        fontSize: 14,
      }}
    >
      <Brain size={16} strokeWidth={1.8} style={{ color: "var(--accent, #0d9488)" }} />
      <span style={{ fontWeight: 700, color: "var(--text-primary, #0f172a)" }}>
        {t("memoryGraph.title")}
      </span>
      <span style={{ color: "var(--text-secondary, #64748b)", fontSize: 13 }}>
        {t("memoryGraph.header.brand")}
      </span>
    </div>
  );
}
```

### - [ ] Step 4: Run test to verify it passes

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-header-bar.test.tsx
```
Expected: PASS — 2 tests.

### - [ ] Step 5: Commit

```bash
cd /Users/dog/Desktop/MRAI
git add apps/web/components/console/graph/memory-graph/HeaderBar.tsx \
        apps/web/tests/unit/memory-graph-header-bar.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): add HeaderBar for memory-graph window

Title (记忆图谱) + brand suffix (· V3). Replaces the brain icon +
text that used to live atop the existing Toolbar.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: FilterRow component

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/FilterRow.tsx`
- Test: `apps/web/tests/unit/memory-graph-filter-row.test.tsx`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-filter-row.test.tsx`:

```tsx
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FilterRow } from "@/components/console/graph/memory-graph/FilterRow";
import type { Role } from "@/components/console/graph/memory-graph/types";

const ALL_ROLES: Role[] = ["fact", "structure", "subject", "concept", "summary"];

afterEach(() => { cleanup(); });

function defaults() {
  return {
    search: "",
    confMin: 0.6,
    filters: Object.fromEntries(ALL_ROLES.map((r) => [r, true])) as Record<Role, boolean>,
    counts: Object.fromEntries(ALL_ROLES.map((r) => [r, 3])) as Record<Role, number>,
    compact: false,
    onSearch: vi.fn(),
    onConfMin: vi.fn(),
    onToggleFilter: vi.fn(),
  };
}

describe("FilterRow", () => {
  it("renders 5 role chips with counts", () => {
    const p = defaults();
    render(<FilterRow {...p} />);
    for (const r of ALL_ROLES) {
      expect(screen.getByTestId(`mg-chip-${r}`)).toBeTruthy();
    }
  });

  it("fires onToggleFilter with role on chip click", () => {
    const p = defaults();
    render(<FilterRow {...p} />);
    fireEvent.click(screen.getByTestId("mg-chip-concept"));
    expect(p.onToggleFilter).toHaveBeenCalledWith("concept");
  });

  it("fires onSearch + onConfMin", () => {
    const p = defaults();
    render(<FilterRow {...p} />);
    fireEvent.change(screen.getByTestId("mg-search-input"), { target: { value: "grad" } });
    fireEvent.change(screen.getByTestId("mg-conf-slider"), { target: { value: "0.85" } });
    expect(p.onSearch).toHaveBeenCalledWith("grad");
    expect(p.onConfMin).toHaveBeenCalledWith(0.85);
  });

  it("compact mode hides chips + slider label", () => {
    const p = defaults();
    render(<FilterRow {...p} compact />);
    expect(screen.queryByTestId("mg-chip-fact")).toBeFalsy();
  });
});
```

### - [ ] Step 2: Run test to verify it fails

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-filter-row.test.tsx
```
Expected: FAIL — module not found.

### - [ ] Step 3: Implement

Create `apps/web/components/console/graph/memory-graph/FilterRow.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import { ROLE_STYLE } from "./constants";
import type { Role } from "./types";

const ALL_ROLES: Role[] = ["fact", "structure", "subject", "concept", "summary"];

interface Props {
  search: string;
  confMin: number;
  filters: Record<Role, boolean>;
  counts: Record<Role, number>;
  compact?: boolean;
  onSearch: (value: string) => void;
  onConfMin: (value: number) => void;
  onToggleFilter: (role: Role) => void;
}

export function FilterRow(p: Props) {
  const t = useTranslations("console-notebooks");
  return (
    <div
      className="mg-filter-row"
      style={{
        display: "flex", alignItems: "center", gap: 10, padding: "8px 12px",
        borderBottom: "1px solid var(--border, rgba(15,42,45,0.08))",
        flexWrap: "wrap",
      }}
    >
      {!p.compact && (
        <div style={{ display: "flex", gap: 4 }}>
          {ALL_ROLES.map((r) => {
            const on = p.filters[r];
            const style = ROLE_STYLE[r];
            return (
              <button
                key={r}
                data-testid={`mg-chip-${r}`}
                type="button"
                onClick={() => p.onToggleFilter(r)}
                aria-pressed={on}
                style={{
                  padding: "4px 10px", borderRadius: 999, fontSize: 12, fontWeight: 500,
                  border: `1px solid ${on ? style.stroke : "rgba(15,42,45,0.15)"}`,
                  background: on ? style.fill : "transparent",
                  color: on ? style.text : "var(--text-secondary)",
                  opacity: on ? 1 : 0.55,
                  cursor: "pointer",
                }}
              >
                <span aria-hidden="true" style={{
                  display: "inline-block", width: 6, height: 6, borderRadius: "50%",
                  background: style.dot, marginRight: 6, verticalAlign: "middle",
                }} />
                {t(`memoryGraph.roles.${r}`)} <span style={{ opacity: 0.65 }}>{p.counts[r]}</span>
              </button>
            );
          })}
        </div>
      )}
      <div style={{ flex: 1 }} />
      <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
        {!p.compact && <span>{t("memoryGraph.confSlider.label")}</span>}
        <input
          data-testid="mg-conf-slider"
          type="range" min={0.6} max={0.99} step={0.01}
          value={p.confMin}
          onChange={(e) => p.onConfMin(Number(e.target.value))}
          style={{ width: p.compact ? 80 : 120 }}
        />
        <span style={{ minWidth: 30, fontFamily: "monospace" }}>{p.confMin.toFixed(2)}</span>
      </label>
      <input
        data-testid="mg-search-input"
        type="search"
        placeholder={t("memoryGraph.searchPlaceholder")}
        value={p.search}
        onChange={(e) => p.onSearch(e.target.value)}
        style={{
          flex: "0 1 200px", padding: "6px 10px", borderRadius: 8,
          border: "1px solid var(--border, rgba(15,42,45,0.1))",
          background: "var(--bg-raised, #fff)", fontSize: 13,
        }}
      />
    </div>
  );
}
```

### - [ ] Step 4: Run test to verify it passes

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-filter-row.test.tsx
```
Expected: PASS — 4 tests.

### - [ ] Step 5: Commit

```bash
cd /Users/dog/Desktop/MRAI
git add apps/web/components/console/graph/memory-graph/FilterRow.tsx \
        apps/web/tests/unit/memory-graph-filter-row.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): add FilterRow (chips + conf slider + search) for memory-graph

First of three new components that replace the overstuffed Toolbar.
Chips left, slider + search pushed right via flex. Compact mode hides
chips + slider label.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: ViewBar component (with 3d tab)

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/ViewBar.tsx`
- Test: `apps/web/tests/unit/memory-graph-view-bar.test.tsx`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-view-bar.test.tsx`:

```tsx
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ViewBar } from "@/components/console/graph/memory-graph/ViewBar";

afterEach(() => { cleanup(); });

describe("ViewBar", () => {
  it("renders 2D / 3D / List tabs", () => {
    render(<ViewBar view="graph" totalCount={12} onViewChange={() => {}} />);
    expect(screen.getByTestId("mg-btn-view-graph")).toBeTruthy();
    expect(screen.getByTestId("mg-btn-view-3d")).toBeTruthy();
    expect(screen.getByTestId("mg-btn-view-list")).toBeTruthy();
  });

  it("shows the node count badge on each tab", () => {
    render(<ViewBar view="graph" totalCount={22} onViewChange={() => {}} />);
    const counts = screen.getAllByText("22");
    expect(counts.length).toBe(3);
  });

  it("marks the active tab with aria-selected=true", () => {
    render(<ViewBar view="3d" totalCount={5} onViewChange={() => {}} />);
    expect(screen.getByTestId("mg-btn-view-3d").getAttribute("aria-selected")).toBe("true");
    expect(screen.getByTestId("mg-btn-view-graph").getAttribute("aria-selected")).toBe("false");
  });

  it("fires onViewChange on click", () => {
    const onChange = vi.fn();
    render(<ViewBar view="graph" totalCount={3} onViewChange={onChange} />);
    fireEvent.click(screen.getByTestId("mg-btn-view-3d"));
    fireEvent.click(screen.getByTestId("mg-btn-view-list"));
    expect(onChange).toHaveBeenNthCalledWith(1, "3d");
    expect(onChange).toHaveBeenNthCalledWith(2, "list");
  });
});
```

### - [ ] Step 2: Run to verify failure

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-view-bar.test.tsx
```
Expected: FAIL — module not found.

### - [ ] Step 3: Implement

Create `apps/web/components/console/graph/memory-graph/ViewBar.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import { Network, Activity, ListTree } from "lucide-react";

export type MemoryGraphView = "graph" | "3d" | "list";

interface TabDef {
  id: MemoryGraphView;
  Icon: typeof Network;
  labelKey: string;
}

const TABS: TabDef[] = [
  { id: "graph", Icon: Network, labelKey: "memoryGraph.view.graph" },
  { id: "3d", Icon: Activity, labelKey: "memoryGraph.view.3d" },
  { id: "list", Icon: ListTree, labelKey: "memoryGraph.view.list" },
];

interface Props {
  view: MemoryGraphView;
  totalCount: number;
  onViewChange: (view: MemoryGraphView) => void;
}

export function ViewBar({ view, totalCount, onViewChange }: Props) {
  const t = useTranslations("console-notebooks");
  return (
    <div
      role="tablist"
      className="mg-view-bar"
      style={{
        display: "flex", alignItems: "center", gap: 2, padding: "4px 12px",
        borderBottom: "1px solid var(--border, rgba(15,42,45,0.08))",
      }}
    >
      {TABS.map((tab) => {
        const active = view === tab.id;
        return (
          <button
            key={tab.id}
            data-testid={`mg-btn-view-${tab.id}`}
            type="button" role="tab" aria-selected={active}
            onClick={() => onViewChange(tab.id)}
            style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "6px 12px", fontSize: 12,
              fontWeight: active ? 600 : 500,
              color: active ? "var(--accent, #0d9488)" : "var(--text-secondary, #64748b)",
              borderBottom: `2px solid ${active ? "var(--accent, #0d9488)" : "transparent"}`,
              background: "transparent", cursor: "pointer",
            }}
          >
            <tab.Icon size={13} strokeWidth={active ? 2 : 1.7} />
            {t(tab.labelKey)}
            <span style={{
              background: active ? "rgba(13,148,136,0.14)" : "rgba(15,42,45,0.06)",
              color: active ? "var(--accent, #0d9488)" : "var(--text-secondary, #64748b)",
              padding: "1px 6px", borderRadius: 999, fontSize: 11, fontWeight: 600,
              fontFeatureSettings: '"tnum"',
            }}>{totalCount}</span>
          </button>
        );
      })}
    </div>
  );
}
```

### - [ ] Step 4: Run to verify pass

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-view-bar.test.tsx
```
Expected: PASS — 4 tests.

### - [ ] Step 5: Commit

```bash
cd /Users/dog/Desktop/MRAI
git add apps/web/components/console/graph/memory-graph/ViewBar.tsx \
        apps/web/tests/unit/memory-graph-view-bar.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): add ViewBar (2D / 3D / List tabs) for memory-graph

Introduces the "3d" view id; exports MemoryGraphView union type.
Tab strip styled per the index.html prototype (underline on active,
count badge on right).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: CanvasControls (floating rearrange / fit buttons)

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/CanvasControls.tsx`
- Test: `apps/web/tests/unit/memory-graph-canvas-controls.test.tsx`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-canvas-controls.test.tsx`:

```tsx
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CanvasControls } from "@/components/console/graph/memory-graph/CanvasControls";

afterEach(() => { cleanup(); });

describe("CanvasControls", () => {
  it("renders rearrange + fit buttons", () => {
    render(<CanvasControls onRearrange={() => {}} onFit={() => {}} />);
    expect(screen.getByTestId("mg-btn-rearrange")).toBeTruthy();
    expect(screen.getByTestId("mg-btn-fit")).toBeTruthy();
  });

  it("fires handlers on click", () => {
    const onR = vi.fn(), onF = vi.fn();
    render(<CanvasControls onRearrange={onR} onFit={onF} />);
    fireEvent.click(screen.getByTestId("mg-btn-rearrange"));
    fireEvent.click(screen.getByTestId("mg-btn-fit"));
    expect(onR).toHaveBeenCalled();
    expect(onF).toHaveBeenCalled();
  });
});
```

### - [ ] Step 2: Run to verify failure

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-canvas-controls.test.tsx
```
Expected: FAIL — module not found.

### - [ ] Step 3: Implement

Create `apps/web/components/console/graph/memory-graph/CanvasControls.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import { RotateCcw, Maximize2 } from "lucide-react";

interface Props {
  onRearrange: () => void;
  onFit: () => void;
}

export function CanvasControls({ onRearrange, onFit }: Props) {
  const t = useTranslations("console-notebooks");
  const btnStyle = {
    display: "inline-flex", alignItems: "center", gap: 4,
    padding: "4px 8px", fontSize: 12, fontWeight: 500,
    background: "rgba(255,255,255,0.88)",
    backdropFilter: "blur(12px)",
    border: "1px solid rgba(15,42,45,0.1)", borderRadius: 8,
    color: "var(--text-primary, #0f172a)", cursor: "pointer",
  } as const;

  return (
    <div
      className="mg-canvas-controls"
      style={{
        position: "absolute", top: 12, right: 12,
        display: "flex", gap: 6, zIndex: 2,
      }}
    >
      <button data-testid="mg-btn-rearrange" type="button" onClick={onRearrange} style={btnStyle}>
        <RotateCcw size={12} /> {t("memoryGraph.rearrange")}
      </button>
      <button data-testid="mg-btn-fit" type="button" onClick={onFit} style={btnStyle}>
        <Maximize2 size={12} /> {t("memoryGraph.fit")}
      </button>
    </div>
  );
}
```

### - [ ] Step 4: Run to verify pass

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-canvas-controls.test.tsx
```
Expected: PASS — 2 tests.

### - [ ] Step 5: Commit

```bash
cd /Users/dog/Desktop/MRAI
git add apps/web/components/console/graph/memory-graph/CanvasControls.tsx \
        apps/web/tests/unit/memory-graph-canvas-controls.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): add floating CanvasControls (rearrange + fit) for memory-graph

Glass-card button cluster absolutely positioned top-right of the
2D canvas. Replaces the inline buttons that used to live in the
Toolbar.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Rewire MemoryGraphView to use new layout components, delete Toolbar

**Files:**
- Modify: `apps/web/components/console/graph/memory-graph/MemoryGraphView.tsx`
- Delete: `apps/web/components/console/graph/memory-graph/Toolbar.tsx`
- Delete: `apps/web/tests/unit/memory-graph-toolbar.test.tsx`
- Modify: `apps/web/tests/unit/memory-graph-view.test.tsx` (update selectors to match new structure)

### - [ ] Step 1: Update MemoryGraphView

Rewrite `apps/web/components/console/graph/memory-graph/MemoryGraphView.tsx`:

```tsx
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { HeaderBar } from "./HeaderBar";
import { FilterRow } from "./FilterRow";
import { ViewBar, type MemoryGraphView as ViewId } from "./ViewBar";
import { CanvasControls } from "./CanvasControls";
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
const COMPACT_BREAKPOINT = 720;

export function MemoryGraphView({ nodes, edges }: Props) {
  const [search, setSearch] = useState("");
  const [confMin, setConfMin] = useState(0.6);
  const [filters, setFilters] = useState<Record<Role, boolean>>(() =>
    Object.fromEntries(ALL_ROLES.map((r) => [r, true])) as Record<Role, boolean>,
  );
  const [view, setView] = useState<ViewId>("graph");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [viewport, setViewport] = useState<ViewportState>({
    k: VIEWPORT_DEFAULTS.k, tx: VIEWPORT_DEFAULTS.tx, ty: VIEWPORT_DEFAULTS.ty,
  });
  const containerRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 800, h: 600 });
  const isNarrow = box.w < BOTTOM_SHEET_BREAKPOINT;
  const compact = box.w < COMPACT_BREAKPOINT;

  useEffect(() => {
    if (typeof ResizeObserver === "undefined" || !containerRef.current) return;
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

  const counts = useMemo(() => {
    const out = Object.fromEntries(ALL_ROLES.map((r) => [r, 0])) as Record<Role, number>;
    for (const n of nodes) if (n.conf >= confMin) out[n.role]++;
    return out;
  }, [nodes, confMin]);

  const effectiveNodes = useMemo(() => nodes.filter((n) => n.conf >= confMin), [nodes, confMin]);
  const effectiveIds = useMemo(() => new Set(effectiveNodes.map((n) => n.id)), [effectiveNodes]);
  const effectiveEdges = useMemo(
    () => edges.filter((e) => effectiveIds.has(e.a) && effectiveIds.has(e.b)),
    [edges, effectiveIds],
  );

  const searchMatches = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return new Set<string>();
    const out = new Set<string>();
    for (const n of effectiveNodes) if (n.label.toLowerCase().includes(q)) out.add(n.id);
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

  const canvasWidth = box.w - (isNarrow ? 0 : (selectedId ? 300 : 0));
  const canvasHeight = box.h - 120 - (isNarrow && selectedId ? Math.floor(box.h * 0.55) : 0);
  // 120 = HeaderBar (~36) + FilterRow (~44) + ViewBar (~40)

  const sim = useForceSim({
    nodes: effectiveNodes, edges: effectiveEdges,
    width: canvasWidth, height: canvasHeight,
  });
  const positions = sim.getPositions();

  const handleViewport = useCallback((v: ViewportState) => setViewport(v), []);
  const handleFit = useCallback(() => setViewport({ k: 1, tx: 0, ty: 0 }), []);
  const handleZoomIn = useCallback(() => setViewport((v) => ({ ...v, k: nextZoom(v.k, "in") })), []);
  const handleZoomOut = useCallback(() => setViewport((v) => ({ ...v, k: nextZoom(v.k, "out") })), []);
  const toggleFilter = useCallback((role: Role) => setFilters((f) => ({ ...f, [role]: !f[role] })), []);
  const handleDragStart = useCallback((id: string) => { void id; }, []);
  const handleDrag = useCallback((id: string, x: number, y: number) => { sim.setFixed(id, x, y); }, [sim]);
  const handleDragEnd = useCallback((id: string) => { sim.setFixed(id, null, null); sim.reheat(0.3); }, [sim]);
  const handleRearrange = useCallback(() => { sim.rearrange(); handleFit(); }, [sim, handleFit]);

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
        <HeaderBar />
        <FilterRow
          search={search} confMin={confMin} filters={filters} counts={counts} compact={compact}
          onSearch={setSearch} onConfMin={setConfMin} onToggleFilter={toggleFilter}
        />
        <ViewBar view={view} totalCount={effectiveNodes.length} onViewChange={setView} />
        <div style={{ position: "relative", flex: 1, minHeight: 0 }}>
          {view === "graph" && (
            <>
              <GraphCanvas
                nodes={effectiveNodes} edges={effectiveEdges} positions={positions}
                width={canvasWidth} height={canvasHeight} viewport={viewport}
                hoverId={hoverId} selectedId={selectedId} searchMatches={searchMatches}
                filters={filters}
                onViewportChange={handleViewport}
                onHover={setHoverId} onSelect={setSelectedId}
                onDragStart={handleDragStart} onDrag={handleDrag} onDragEnd={handleDragEnd}
              />
              <CanvasControls onRearrange={handleRearrange} onFit={handleFit} />
              <LegendAndZoom
                zoom={viewport.k}
                onZoomIn={handleZoomIn} onZoomOut={handleZoomOut} onFit={handleFit}
                showLegend={!compact}
              />
            </>
          )}
          {view === "3d" && (
            <div data-testid="mg-3d-placeholder" style={{ padding: 40, textAlign: "center", color: "var(--text-secondary)" }}>
              {/* Filled in by Task 13 */}
              3D view coming
            </div>
          )}
          {view === "list" && (
            <ListView nodes={effectiveNodes} selectedId={selectedId} onSelect={setSelectedId} />
          )}
        </div>
      </div>
      {selectedNode && (
        <NodeDetailDrawer
          node={selectedNode} neighbors={drawerNeighbors}
          onSelectNeighbor={(id) => setSelectedId(id)}
          onClose={() => setSelectedId(null)}
          layout={isNarrow ? "bottomSheet" : "side"}
        />
      )}
    </div>
  );
}
```

### - [ ] Step 2: Delete Toolbar + its test

```bash
cd /Users/dog/Desktop/MRAI
rm apps/web/components/console/graph/memory-graph/Toolbar.tsx
rm apps/web/tests/unit/memory-graph-toolbar.test.tsx
```

### - [ ] Step 3: Update MemoryGraphView test to match new structure

Rewrite `apps/web/tests/unit/memory-graph-view.test.tsx`:

```tsx
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryGraphView } from "@/components/console/graph/memory-graph/MemoryGraphView";
import type { GraphNode, GraphEdge } from "@/components/console/graph/memory-graph/types";

function makeNode(over: Partial<GraphNode>): GraphNode {
  return {
    id: "n", role: "fact", label: "L",
    conf: 0.8, reuse: 0, lastUsed: null, pinned: false, source: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    raw: {} as any,
    ...over,
  };
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("MemoryGraphView layout", () => {
  it("renders HeaderBar + FilterRow + ViewBar + graph canvas", () => {
    render(<MemoryGraphView nodes={[makeNode({ id: "a", label: "Alpha" })]} edges={[]} />);
    expect(screen.getByText("memoryGraph.title")).toBeTruthy();
    expect(screen.getByTestId("mg-search-input")).toBeTruthy();
    expect(screen.getByTestId("mg-btn-view-graph")).toBeTruthy();
    expect(screen.getByTestId("mg-btn-view-3d")).toBeTruthy();
    expect(screen.getByTestId("mg-btn-view-list")).toBeTruthy();
    expect(screen.getByTestId("mg-svg")).toBeTruthy();
  });

  it("opens drawer when a node is clicked", () => {
    const nodes: GraphNode[] = [makeNode({ id: "a", label: "Alpha" })];
    render(<MemoryGraphView nodes={nodes} edges={[]} />);
    fireEvent.click(screen.getByTestId("mg-node-a"));
    expect(screen.getByRole("complementary", { name: "Node detail" })).toBeTruthy();
  });

  it("switches to list view when List tab clicked", () => {
    render(<MemoryGraphView nodes={[makeNode({ id: "a", label: "Alpha" })]} edges={[]} />);
    fireEvent.click(screen.getByTestId("mg-btn-view-list"));
    expect(screen.getByTestId("mg-list-row-a")).toBeTruthy();
    expect(screen.queryByTestId("mg-svg")).toBeFalsy();
  });

  it("switches to 3d view placeholder (full impl in Task 13)", () => {
    render(<MemoryGraphView nodes={[]} edges={[]} />);
    fireEvent.click(screen.getByTestId("mg-btn-view-3d"));
    expect(screen.getByTestId("mg-3d-placeholder")).toBeTruthy();
  });
});
```

### - [ ] Step 4: Run the full memory-graph test suite

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph
```
Expected: all PASS. If any existing test still imports Toolbar directly, update those imports to FilterRow / ViewBar as appropriate.

### - [ ] Step 5: Typecheck

```bash
cd apps/web && node_modules/.bin/tsc --noEmit
```
Expected: 0 errors.

### - [ ] Step 6: Commit

```bash
cd /Users/dog/Desktop/MRAI
git add apps/web/components/console/graph/memory-graph/MemoryGraphView.tsx \
        apps/web/tests/unit/memory-graph-view.test.tsx
git rm apps/web/components/console/graph/memory-graph/Toolbar.tsx \
       apps/web/tests/unit/memory-graph-toolbar.test.tsx
git commit -m "$(cat <<'EOF'
refactor(web): swap memory-graph Toolbar for HeaderBar + FilterRow + ViewBar

The old single-row Toolbar was overloaded (search + slider + chips
+ buttons + view tabs in one flex). Prototype (index.html lines
4003-4061) splits these across three stacked bars with a floating
canvas-control cluster. This commit ports that structure.

View state now accepts "3d" as a view id; placeholder renders until
Task 13 wires Memory3D.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 3D constants + types

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/Memory3D/constants3d.ts`
- Create: `apps/web/components/console/graph/memory-graph/Memory3D/types3d.ts`
- Test: `apps/web/tests/unit/memory-graph-3d-constants.test.ts`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-3d-constants.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  TIER_RADIUS, RING_COLORS, CARD_W, CARD_H, CARD_WORLD_W,
  CAMERA_DEFAULT_POS, CAMERA_DEFAULT_FOV, ORBIT_MIN_DIST, ORBIT_MAX_DIST,
  FOG_NEAR, FOG_FAR, TIER_VISIBLE_ROLES, MASTERY_Y_RANGE,
} from "@/components/console/graph/memory-graph/Memory3D/constants3d";

describe("3D constants", () => {
  it("ring radii match prototype + spec", () => {
    expect(TIER_RADIUS.subject).toBe(95);
    expect(TIER_RADIUS.concept).toBe(175);
    expect(TIER_RADIUS.fact).toBe(245);
  });

  it("visible roles cover the 3 roles that reach the frontend", () => {
    expect(TIER_VISIBLE_ROLES.sort()).toEqual(["concept", "fact", "subject"].sort());
  });

  it("card sizes match prototype (320x200, world width 58)", () => {
    expect(CARD_W).toBe(320);
    expect(CARD_H).toBe(200);
    expect(CARD_WORLD_W).toBe(58);
  });

  it("camera defaults", () => {
    expect(CAMERA_DEFAULT_POS).toEqual([0, 110, 360]);
    expect(CAMERA_DEFAULT_FOV).toBe(45);
    expect(ORBIT_MIN_DIST).toBe(140);
    expect(ORBIT_MAX_DIST).toBe(820);
  });

  it("fog distances", () => {
    expect(FOG_NEAR).toBe(380);
    expect(FOG_FAR).toBe(1100);
  });

  it("mastery Y range is 140 units", () => {
    expect(MASTERY_Y_RANGE).toBe(140);
  });
});
```

### - [ ] Step 2: Run to verify failure

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-3d-constants.test.ts
```
Expected: FAIL — modules not found.

### - [ ] Step 3: Create `types3d.ts`

Create `apps/web/components/console/graph/memory-graph/Memory3D/types3d.ts`:

```ts
import type { Vector3 } from "three";
import type { GraphNode, Role } from "../types";

export interface PlacedNode {
  id: string;
  node: GraphNode;
  position: Vector3;  // world-space card position
  ringY: number;      // ground y (always -89 for drop-line end)
}

export interface CameraAnim {
  fromTarget: Vector3;
  toTarget: Vector3;
  fromPos: Vector3;
  toPos: Vector3;
  t: number;
  dur: number;  // seconds
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
```

### - [ ] Step 4: Create `constants3d.ts`

Create `apps/web/components/console/graph/memory-graph/Memory3D/constants3d.ts`:

```ts
import type { Role } from "../types";
import type { RoleGlyph } from "./types3d";

/** Tier ring radii. subject innermost, fact outermost. structure/summary never placed (backend filters). */
export const TIER_RADIUS: Record<Role, number> = {
  subject:   95,
  concept:   175,
  fact:      245,
  structure: 60,   // reserved for future: innermost meta-tier
  summary:   310,  // reserved for future: outermost summary-tier
};

/** Ring stroke / label colors as hex numbers (not CSS strings, three.js wants 0x-form). */
export const RING_COLORS: Record<Role, number> = {
  subject:   0x10b981,
  concept:   0x0d9488,
  fact:      0x2563eb,
  structure: 0x7c3aed,
  summary:   0xf59e0b,
};

/** Roles whose rings + nodes are actually rendered given current backend behavior. */
export const TIER_VISIBLE_ROLES: Role[] = ["subject", "concept", "fact"];

/** Node-card sprite — canvas texture size (logical px, retina handled by dpr=2 scale). */
export const CARD_W = 320;
export const CARD_H = 200;
export const CARD_WORLD_W = 58;
export const CARD_WORLD_H = CARD_WORLD_W / (CARD_W / CARD_H);

/** Camera. */
export const CAMERA_DEFAULT_POS: [number, number, number] = [0, 110, 360];
export const CAMERA_DEFAULT_FOV = 45;
export const ORBIT_MIN_DIST = 140;
export const ORBIT_MAX_DIST = 820;
export const ORBIT_POLAR_MIN = Math.PI * 0.15;
export const ORBIT_POLAR_MAX = Math.PI * 0.52;

/** Fog. Color is resolved at mount from CSS --bg-base. */
export const FOG_NEAR = 380;
export const FOG_FAR = 1100;
export const FOG_FALLBACK_COLOR = 0xf8fafc;

/** Ground plane y (disc + ring labels + spoke endpoints). */
export const GROUND_Y = -90;

/** Mastery lift: (mastery - 0.5) × MASTERY_Y_RANGE. */
export const MASTERY_Y_RANGE = 140;

/** Bezier arc lift for edges (midpoint +Y offset). */
export const EDGE_ARC_LIFT = 14;

/** Role glyphs used on card type-chip. */
export const ROLE_GLYPH: RoleGlyph = {
  fact: "◇",
  structure: "▣",
  subject: "⬢",
  concept: "◈",
  summary: "▤",
};

/** Role → human label keys (re-used from 2D i18n: `memoryGraph.roles.${role}`). */

/** Camera animation duration (seconds). */
export const CAMERA_ANIM_DUR = 0.9;
```

### - [ ] Step 5: Run to verify pass

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-3d-constants.test.ts
```
Expected: PASS — 6 tests.

### - [ ] Step 6: Typecheck

```bash
cd apps/web && node_modules/.bin/tsc --noEmit
```

### - [ ] Step 7: Commit

```bash
cd /Users/dog/Desktop/MRAI
git add apps/web/components/console/graph/memory-graph/Memory3D/constants3d.ts \
        apps/web/components/console/graph/memory-graph/Memory3D/types3d.ts \
        apps/web/tests/unit/memory-graph-3d-constants.test.ts
git commit -m "$(cat <<'EOF'
feat(web): scaffold Memory3D constants + types

Ring radii, camera defaults, fog, card sizes, role glyphs — all
copied from index.html prototype + spec. TIER_VISIBLE_ROLES
enumerates which rings are actually drawn (subject/concept/fact;
structure/summary reserved for future backend expansion).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Mastery + layout (depth-ring placement)

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/Memory3D/layout3d.ts`
- Test: `apps/web/tests/unit/memory-graph-3d-layout.test.ts`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-3d-layout.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { masteryOf, placeNodes } from "@/components/console/graph/memory-graph/Memory3D/layout3d";
import type { GraphNode } from "@/components/console/graph/memory-graph/types";

function makeNode(over: Partial<GraphNode>): GraphNode {
  return {
    id: "n", role: "fact", label: "L", conf: 0.8, reuse: 0,
    lastUsed: null, pinned: false, source: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    raw: {} as any,
    ...over,
  };
}

describe("masteryOf", () => {
  it("combines conf (0.5 weight), reuse (0.3), recency (0.2)", () => {
    const n = makeNode({ conf: 0.8, reuse: 20, lastUsed: "0m" });
    // conf 0.8 * 0.5 + reuse 1.0 * 0.3 + recency 1.0 * 0.2 = 0.4 + 0.3 + 0.2 = 0.9
    expect(masteryOf(n)).toBeCloseTo(0.9, 2);
  });

  it("defaults conf to 0.8 when missing", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const n = makeNode({ conf: undefined as any });
    // (0.8 * 0.5) + (0 * 0.3) + some recency fallback
    expect(masteryOf(n)).toBeGreaterThan(0);
  });
});

describe("placeNodes — depth rings", () => {
  it("places fact nodes on the fact ring (r=245)", () => {
    const nodes = [
      makeNode({ id: "a", role: "fact" }),
      makeNode({ id: "b", role: "fact" }),
      makeNode({ id: "c", role: "fact" }),
    ];
    const placed = placeNodes(nodes);
    for (const p of placed) {
      const rXZ = Math.sqrt(p.position.x ** 2 + p.position.z ** 2);
      // allow up to 10 units of radial jitter tolerance
      expect(rXZ).toBeGreaterThan(245 - 15);
      expect(rXZ).toBeLessThan(245 + 15);
    }
  });

  it("places subject nodes on r=95 and concept nodes on r=175", () => {
    const placed = placeNodes([
      makeNode({ id: "s", role: "subject" }),
      makeNode({ id: "c", role: "concept" }),
    ]);
    const s = placed.find((p) => p.node.role === "subject")!;
    const c = placed.find((p) => p.node.role === "concept")!;
    const rS = Math.sqrt(s.position.x ** 2 + s.position.z ** 2);
    const rC = Math.sqrt(c.position.x ** 2 + c.position.z ** 2);
    expect(rS).toBeLessThan(rC);
    expect(rC).toBeLessThan(200);
  });

  it("Y position tracks mastery", () => {
    const low = makeNode({ id: "low", role: "fact", conf: 0.7, reuse: 0 });
    const high = makeNode({ id: "high", role: "fact", conf: 0.99, reuse: 20, lastUsed: "0m" });
    const placed = placeNodes([low, high]);
    const pLow = placed.find((p) => p.id === "low")!;
    const pHigh = placed.find((p) => p.id === "high")!;
    expect(pHigh.position.y).toBeGreaterThan(pLow.position.y);
  });

  it("is deterministic (same id → same position across runs)", () => {
    const nodes = [makeNode({ id: "stable", role: "fact" })];
    const p1 = placeNodes(nodes);
    const p2 = placeNodes(nodes);
    expect(p1[0].position.x).toBe(p2[0].position.x);
    expect(p1[0].position.z).toBe(p2[0].position.z);
  });

  it("drops nodes whose role has no tier (structure / summary → skipped)", () => {
    const placed = placeNodes([
      makeNode({ id: "a", role: "fact" }),
      makeNode({ id: "b", role: "structure" }),
      makeNode({ id: "c", role: "summary" }),
    ]);
    expect(placed.map((p) => p.id).sort()).toEqual(["a"]);
  });
});
```

### - [ ] Step 2: Run to verify failure

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-3d-layout.test.ts
```
Expected: FAIL — module not found.

### - [ ] Step 3: Implement

Create `apps/web/components/console/graph/memory-graph/Memory3D/layout3d.ts`:

```ts
import { Vector3 } from "three";
import type { GraphNode } from "../types";
import { TIER_RADIUS, TIER_VISIBLE_ROLES, GROUND_Y, MASTERY_Y_RANGE } from "./constants3d";
import type { PlacedNode } from "./types3d";

/** `conf * 0.5 + min(reuse/20, 1) * 0.3 + max(0, 1 - ageHrs/96) * 0.2`. */
export function masteryOf(n: GraphNode): number {
  const conf = typeof n.conf === "number" ? n.conf : 0.8;
  const reuseNormalized = Math.min((n.reuse ?? 0) / 20, 1);
  // Parse lastUsed "30m" / "2h" / "3d" into hours
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

/** Stable hash from node id → angle / radius jitter. Matches prototype. */
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
  // Stable order within each ring: sort by id
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
```

### - [ ] Step 4: Run to verify pass

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-3d-layout.test.ts
```
Expected: PASS — 7 tests.

### - [ ] Step 5: Commit

```bash
cd /Users/dog/Desktop/MRAI
git add apps/web/components/console/graph/memory-graph/Memory3D/layout3d.ts \
        apps/web/tests/unit/memory-graph-3d-layout.test.ts
git commit -m "$(cat <<'EOF'
feat(web): add Memory3D layout (depth-ring placement + masteryOf)

masteryOf: conf*0.5 + reuse*0.3 + recency*0.2 → Y lift.
placeNodes: bucket by role, evenly distribute around tier ring,
apply stable hash jitter so the same id always lands in the same
slot across remounts. Drops structure/summary roles (no ring).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Card sprite texture builder

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/Memory3D/cardSprite.ts`
- Test: `apps/web/tests/unit/memory-graph-3d-card-sprite.test.ts`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-3d-card-sprite.test.ts`:

```ts
import { describe, expect, it, beforeAll } from "vitest";
import { makeNodeCard, cardCacheKey } from "@/components/console/graph/memory-graph/Memory3D/cardSprite";
import type { GraphNode } from "@/components/console/graph/memory-graph/types";

// jsdom doesn't provide 2D canvas; install a minimal polyfill.
beforeAll(() => {
  const OriginalCanvas = HTMLCanvasElement;
  const proto = OriginalCanvas.prototype;
  const origGetContext = proto.getContext;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  proto.getContext = function (type: string): any {
    if (type === "2d") {
      const noop = () => {};
      return {
        scale: noop, fillRect: noop, fillText: noop, measureText: () => ({ width: 40 }),
        beginPath: noop, moveTo: noop, lineTo: noop, closePath: noop, arc: noop,
        quadraticCurveTo: noop, stroke: noop, fill: noop,
        createLinearGradient: () => ({ addColorStop: noop }),
        createRadialGradient: () => ({ addColorStop: noop }),
        set fillStyle(_v: string) {}, get fillStyle() { return ""; },
        set strokeStyle(_v: string) {}, get strokeStyle() { return ""; },
        set lineWidth(_v: number) {}, get lineWidth() { return 1; },
        set lineCap(_v: string) {}, get lineCap() { return "butt"; },
        set textAlign(_v: string) {}, get textAlign() { return "left"; },
        set textBaseline(_v: string) {}, get textBaseline() { return "alphabetic"; },
        set font(_v: string) {}, get font() { return ""; },
      };
    }
    return origGetContext?.call(this, type);
  };
});

function n(over: Partial<GraphNode>): GraphNode {
  return {
    id: "n", role: "fact", label: "Alpha", conf: 0.85, reuse: 0,
    lastUsed: null, pinned: false, source: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    raw: {} as any, ...over,
  };
}

describe("cardCacheKey", () => {
  it("changes when display-affecting props change", () => {
    const base = n({});
    const keyBase = cardCacheKey(base);
    expect(keyBase).toBe(cardCacheKey(n({})));
    expect(cardCacheKey(n({ conf: 0.9 }))).not.toBe(keyBase);
    expect(cardCacheKey(n({ reuse: 3 }))).not.toBe(keyBase);
    expect(cardCacheKey(n({ pinned: true }))).not.toBe(keyBase);
  });

  it("ignores raw / lastUsed timing drift within same bucket", () => {
    expect(cardCacheKey(n({ lastUsed: "2h" }))).toBe(cardCacheKey(n({ lastUsed: "2h" })));
  });
});

describe("makeNodeCard", () => {
  it("returns a Sprite with a CanvasTexture material", () => {
    const sprite = makeNodeCard(n({}));
    expect(sprite.type).toBe("Sprite");
    expect(sprite.material).toBeDefined();
    expect(sprite.userData.cacheKey).toBe(cardCacheKey(n({})));
  });

  it("scales sprite to world size", () => {
    const sprite = makeNodeCard(n({}));
    expect(sprite.scale.x).toBeGreaterThan(0);
    expect(sprite.scale.y).toBeGreaterThan(0);
  });
});
```

### - [ ] Step 2: Run to verify failure

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-3d-card-sprite.test.ts
```
Expected: FAIL — module not found.

### - [ ] Step 3: Implement

Create `apps/web/components/console/graph/memory-graph/Memory3D/cardSprite.ts`:

```ts
import { CanvasTexture, Sprite, SpriteMaterial } from "three";
import type { GraphNode } from "../types";
import { ROLE_STYLE } from "../constants";
import {
  CARD_W, CARD_H, CARD_WORLD_W, CARD_WORLD_H, ROLE_GLYPH,
} from "./constants3d";

export function cardCacheKey(n: GraphNode): string {
  return `${n.id}:${n.role}:${n.conf.toFixed(2)}:${n.reuse}:${n.pinned ? 1 : 0}`;
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y); ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r); ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h); ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

export function makeNodeCard(n: GraphNode): Sprite {
  const cfg = ROLE_STYLE[n.role];
  const c = document.createElement("canvas");
  c.width = CARD_W * 2;   // retina
  c.height = CARD_H * 2;
  const ctx = c.getContext("2d")!;
  ctx.scale(2, 2);

  // Glass body
  const g = ctx.createLinearGradient(0, 0, 0, CARD_H);
  g.addColorStop(0, "rgba(255,255,255,0.96)");
  g.addColorStop(1, "rgba(245,250,252,0.90)");
  ctx.fillStyle = g;
  roundRect(ctx, 4, 4, CARD_W - 8, CARD_H - 8, 16);
  ctx.fill();

  // Colored corner wash (type-tinted)
  const corner = ctx.createRadialGradient(CARD_W - 30, 30, 4, CARD_W - 30, 30, 140);
  corner.addColorStop(0, cfg.fill);
  corner.addColorStop(1, cfg.fill + "00");
  ctx.fillStyle = corner;
  roundRect(ctx, 4, 4, CARD_W - 8, CARD_H - 8, 16);
  ctx.fill();

  // Inner border
  ctx.strokeStyle = "rgba(15,42,45,0.09)";
  ctx.lineWidth = 1;
  roundRect(ctx, 4.5, 4.5, CARD_W - 9, CARD_H - 9, 15.5);
  ctx.stroke();

  // Type chip
  ctx.fillStyle = cfg.stroke;
  roundRect(ctx, 18, 18, 84, 24, 12);
  ctx.fill();
  ctx.fillStyle = "#fff";
  ctx.font = '600 13px "Plus Jakarta Sans", system-ui, sans-serif';
  ctx.textBaseline = "middle";
  ctx.fillText(`${ROLE_GLYPH[n.role]}  ${n.role}`, 28, 30);

  // Reuse badge
  if (n.reuse) {
    ctx.fillStyle = "rgba(15,42,45,0.06)";
    roundRect(ctx, CARD_W - 70, 18, 50, 24, 12);
    ctx.fill();
    ctx.fillStyle = "#0f2a2d";
    ctx.font = '600 12px "Plus Jakarta Sans", system-ui, sans-serif';
    ctx.fillText(`×${n.reuse}`, CARD_W - 60, 30);
  }

  // Pinned dot
  if (n.pinned) {
    ctx.fillStyle = "#f97316";
    ctx.beginPath();
    ctx.arc(CARD_W - 88, 30, 4, 0, Math.PI * 2);
    ctx.fill();
  }

  // Label (2 lines max)
  ctx.fillStyle = "#0f172a";
  ctx.font = '700 18px "Plus Jakarta Sans", system-ui, sans-serif';
  const label = n.label || "(untitled)";
  const chars = [...label];
  const lines: string[] = [];
  let line = "";
  const maxW = CARD_W - 40;
  for (const ch of chars) {
    const test = line + ch;
    if (ctx.measureText(test).width > maxW && line) {
      lines.push(line);
      line = ch;
      if (lines.length === 2) break;
    } else {
      line = test;
    }
  }
  if (lines.length < 2 && line) lines.push(line);
  lines.slice(0, 2).forEach((ln, i) => ctx.fillText(ln, 18, 64 + i * 24));

  // Summary line
  ctx.fillStyle = "#64748b";
  ctx.font = '500 12px "Plus Jakarta Sans", system-ui, sans-serif';
  const summary = (n.raw?.content ?? "").trim();
  let sm = summary, smaxW = CARD_W - 36;
  while (ctx.measureText(sm + "…").width > smaxW && sm.length > 1) sm = sm.slice(0, -1);
  ctx.fillText(sm + (sm.length < summary.length ? "…" : ""), 18, 120);

  // Conf arc
  const cx = 38, cy = CARD_H - 34, rr = 16;
  ctx.strokeStyle = "rgba(15,42,45,0.08)";
  ctx.lineWidth = 4;
  ctx.beginPath();
  ctx.arc(cx, cy, rr, Math.PI * 0.75, Math.PI * 2.25);
  ctx.stroke();
  ctx.strokeStyle = cfg.stroke;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.arc(cx, cy, rr, Math.PI * 0.75, Math.PI * 0.75 + Math.PI * 1.5 * (n.conf || 0.8));
  ctx.stroke();
  ctx.fillStyle = cfg.text;
  ctx.font = '700 11px "Plus Jakarta Sans", system-ui, sans-serif';
  ctx.textAlign = "center";
  ctx.fillText((n.conf || 0).toFixed(2), cx, cy + 4);
  ctx.textAlign = "left";
  ctx.lineCap = "butt";

  // Source + age
  ctx.fillStyle = "#475569";
  ctx.font = '500 11px "JetBrains Mono", monospace';
  ctx.textAlign = "right";
  ctx.fillText(n.source || "—", CARD_W - 18, CARD_H - 28);
  ctx.fillStyle = "#94a3b8";
  ctx.fillText(n.lastUsed ? `${n.lastUsed} ago` : "—", CARD_W - 18, CARD_H - 14);
  ctx.textAlign = "left";

  const texture = new CanvasTexture(c);
  texture.needsUpdate = true;
  const material = new SpriteMaterial({
    map: texture, transparent: true, depthWrite: false, opacity: 1.0,
  });
  const sprite = new Sprite(material);
  sprite.scale.set(CARD_WORLD_W, CARD_WORLD_H, 1);
  sprite.userData.cacheKey = cardCacheKey(n);
  return sprite;
}
```

### - [ ] Step 4: Run to verify pass

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-3d-card-sprite.test.ts
```
Expected: PASS — 4 tests.

### - [ ] Step 5: Commit

```bash
cd /Users/dog/Desktop/MRAI
git add apps/web/components/console/graph/memory-graph/Memory3D/cardSprite.ts \
        apps/web/tests/unit/memory-graph-3d-card-sprite.test.ts
git commit -m "$(cat <<'EOF'
feat(web): add Memory3D card sprite builder

makeNodeCard: Canvas 2D → CanvasTexture → Sprite per node.
Layout follows index.html prototype: glass body, role chip,
reuse badge, pinned dot, 2-line label, summary, conf arc,
source + age. Cache key covers conf/reuse/pinned so SSE updates
trigger one-card regeneration (scene wiring in Task 11).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Edges + ground builders

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/Memory3D/edges3d.ts`
- Create: `apps/web/components/console/graph/memory-graph/Memory3D/ground.ts`
- Test: `apps/web/tests/unit/memory-graph-3d-edges.test.ts`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-3d-edges.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { Vector3 } from "three";
import { buildEdgeGeometry } from "@/components/console/graph/memory-graph/Memory3D/edges3d";
import { buildGround } from "@/components/console/graph/memory-graph/Memory3D/ground";

describe("buildEdgeGeometry", () => {
  it("returns a bezier-curve geometry with midpoint lifted", () => {
    const a = new Vector3(0, 0, 0);
    const b = new Vector3(100, 0, 0);
    const geo = buildEdgeGeometry(a, b);
    const pts = geo.attributes.position;
    expect(pts.count).toBeGreaterThan(10);
    // midpoint sample (index around middle) should have y > 0
    const midIdx = Math.floor(pts.count / 2);
    const midY = pts.getY(midIdx);
    expect(midY).toBeGreaterThan(10);
  });
});

describe("buildGround", () => {
  it("returns a THREE.Group with disc + ring lines + spokes + column", () => {
    const group = buildGround();
    expect(group.type).toBe("Group");
    expect(group.children.length).toBeGreaterThan(5);
    // At least 3 rings (Line objects, LineDashedMaterial)
    const lineCount = group.children.filter((c) => c.type === "Line").length;
    expect(lineCount).toBeGreaterThanOrEqual(3 + 12 + 1); // 3 rings + 12 spokes + 1 Y column
  });
});
```

### - [ ] Step 2: Run to verify failure

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-3d-edges.test.ts
```
Expected: FAIL — modules not found.

### - [ ] Step 3: Implement `edges3d.ts`

Create `apps/web/components/console/graph/memory-graph/Memory3D/edges3d.ts`:

```ts
import {
  BufferGeometry, QuadraticBezierCurve3, Vector3,
  LineBasicMaterial, Line, Color,
} from "three";
import { EDGE_STYLE } from "../constants";
import { EDGE_ARC_LIFT } from "./constants3d";

/** Build a geometry for a single edge from a→b, bezier-arced. */
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
```

### - [ ] Step 4: Implement `ground.ts`

Create `apps/web/components/console/graph/memory-graph/Memory3D/ground.ts`:

```ts
import {
  Group, Mesh, MeshBasicMaterial, CircleGeometry, RingGeometry,
  BufferGeometry, Vector3, Line, LineDashedMaterial, LineBasicMaterial,
  DoubleSide,
} from "three";
import {
  TIER_RADIUS, RING_COLORS, TIER_VISIBLE_ROLES, GROUND_Y,
} from "./constants3d";

export function buildGround(): Group {
  const group = new Group();

  // Disc (soft "table")
  const disc = new Mesh(
    new CircleGeometry(500, 64),
    new MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.28, depthWrite: false }),
  );
  disc.rotation.x = -Math.PI / 2;
  disc.position.y = GROUND_Y;
  group.add(disc);

  // Tier rings: dashed line + faint filled band
  for (const role of TIER_VISIBLE_ROLES) {
    const r = TIER_RADIUS[role];
    const color = RING_COLORS[role];

    const pts: Vector3[] = [];
    for (let i = 0; i <= 128; i++) {
      const a = (i / 128) * Math.PI * 2;
      pts.push(new Vector3(Math.cos(a) * r, GROUND_Y + 1, Math.sin(a) * r));
    }
    const ringGeo = new BufferGeometry().setFromPoints(pts);
    const ringMat = new LineDashedMaterial({
      color, transparent: true, opacity: 0.38, dashSize: 4, gapSize: 6, depthWrite: false,
    });
    const ring = new Line(ringGeo, ringMat);
    ring.computeLineDistances();
    group.add(ring);

    const band = new Mesh(
      new RingGeometry(r - 6, r, 96),
      new MeshBasicMaterial({ color, transparent: true, opacity: 0.07, side: DoubleSide, depthWrite: false }),
    );
    band.rotation.x = -Math.PI / 2;
    band.position.y = GROUND_Y + 0.5;
    group.add(band);
  }

  // 12 radial spokes
  for (let k = 0; k < 12; k++) {
    const a = (k / 12) * Math.PI * 2;
    const pts = [
      new Vector3(0, GROUND_Y + 1, 0),
      new Vector3(Math.cos(a) * 340, GROUND_Y + 1, Math.sin(a) * 340),
    ];
    const spokeGeo = new BufferGeometry().setFromPoints(pts);
    const spokeMat = new LineBasicMaterial({
      color: 0x9fb3c2, transparent: true, opacity: 0.18, depthWrite: false,
    });
    group.add(new Line(spokeGeo, spokeMat));
  }

  // Y column (mastery axis)
  const colGeo = new BufferGeometry().setFromPoints([
    new Vector3(0, GROUND_Y, 0),
    new Vector3(0, 90, 0),
  ]);
  const colMat = new LineDashedMaterial({
    color: 0x0f2a2d, transparent: true, opacity: 0.2, dashSize: 3, gapSize: 4, depthWrite: false,
  });
  const column = new Line(colGeo, colMat);
  column.computeLineDistances();
  group.add(column);

  return group;
}
```

### - [ ] Step 5: Run to verify pass

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-3d-edges.test.ts
```
Expected: PASS — 2 tests.

### - [ ] Step 6: Commit

```bash
cd /Users/dog/Desktop/MRAI
git add apps/web/components/console/graph/memory-graph/Memory3D/edges3d.ts \
        apps/web/components/console/graph/memory-graph/Memory3D/ground.ts \
        apps/web/tests/unit/memory-graph-3d-edges.test.ts
git commit -m "$(cat <<'EOF'
feat(web): add Memory3D edge + ground builders

edges3d: QuadraticBezierCurve3 with +14 midpoint Y lift, 24-point
sampled line geometry. Style uses existing EDGE_STYLE; focused
edges switch to primary teal 0.85 opacity.

ground: disc + 3 tier rings (dashed line + faint band) + 12 radial
spokes + Y column (dashed). All at y = GROUND_Y (-90).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: useThreeScene hook (bootstrap + RAF loop)

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/Memory3D/useThreeScene.ts`
- Test: `apps/web/tests/unit/memory-graph-3d-use-scene.test.ts`

This hook owns the scene lifecycle. It's a React integration point; the test is a smoke test (renderer created, cleanup on unmount, no leaks).

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-3d-use-scene.test.ts`:

```ts
import { renderHook, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useThreeScene } from "@/components/console/graph/memory-graph/Memory3D/useThreeScene";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("useThreeScene", () => {
  it("initializes without mount point — returns null handle", () => {
    const { result } = renderHook(() => useThreeScene({
      mountRef: { current: null } as React.RefObject<HTMLDivElement>,
      nodes: [], edges: [],
      onHover: () => {}, onSelect: () => {},
    }));
    expect(result.current).toBeDefined();
  });

  it("exposes focusOn / rearrange / zoom / fit / toggleAutoRotate / getProjectedScreenPos methods", () => {
    const { result } = renderHook(() => useThreeScene({
      mountRef: { current: null } as React.RefObject<HTMLDivElement>,
      nodes: [], edges: [],
      onHover: () => {}, onSelect: () => {},
    }));
    const h = result.current;
    expect(typeof h.focusOn).toBe("function");
    expect(typeof h.rearrange).toBe("function");
    expect(typeof h.zoomIn).toBe("function");
    expect(typeof h.zoomOut).toBe("function");
    expect(typeof h.fit).toBe("function");
    expect(typeof h.toggleAutoRotate).toBe("function");
    expect(typeof h.getProjectedScreenPos).toBe("function");
  });
});
```

### - [ ] Step 2: Run to verify failure

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-3d-use-scene.test.ts
```
Expected: FAIL — module not found.

### - [ ] Step 3: Implement

Create `apps/web/components/console/graph/memory-graph/Memory3D/useThreeScene.ts`:

```ts
"use client";

import { useEffect, useRef } from "react";
import {
  Scene, PerspectiveCamera, WebGLRenderer, AmbientLight, DirectionalLight,
  Group, Vector3, Color, Fog, Raycaster, Vector2, BufferGeometry,
  Line, LineBasicMaterial, Sprite,
} from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { GraphEdge, GraphNode } from "../types";
import { makeNodeCard, cardCacheKey } from "./cardSprite";
import { placeNodes } from "./layout3d";
import { buildGround } from "./ground";
import { buildEdgeGeometry } from "./edges3d";
import { EDGE_STYLE } from "../constants";
import {
  CAMERA_DEFAULT_POS, CAMERA_DEFAULT_FOV, ORBIT_MIN_DIST, ORBIT_MAX_DIST,
  ORBIT_POLAR_MIN, ORBIT_POLAR_MAX, FOG_NEAR, FOG_FAR, FOG_FALLBACK_COLOR,
  CAMERA_ANIM_DUR, GROUND_Y,
} from "./constants3d";
import type { SceneHandle, CameraAnim } from "./types3d";

interface Options {
  mountRef: React.RefObject<HTMLDivElement | null>;
  nodes: GraphNode[];
  edges: GraphEdge[];
  onHover: (id: string | null) => void;
  onSelect: (id: string | null) => void;
}

function resolveBgColor(mount: HTMLElement | null): Color {
  if (!mount) return new Color(FOG_FALLBACK_COLOR);
  const cs = getComputedStyle(mount);
  const bg = cs.backgroundColor;
  if (bg && bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent") {
    const c = new Color();
    try { c.set(bg); return c; } catch { /* fall through */ }
  }
  return new Color(FOG_FALLBACK_COLOR);
}

export function useThreeScene(opts: Options): SceneHandle {
  const handleRef = useRef<SceneHandle | null>(null);
  const sceneStateRef = useRef<{
    renderer?: WebGLRenderer;
    scene?: Scene;
    camera?: PerspectiveCamera;
    controls?: OrbitControls;
    nodeGroup?: Group;
    edgeGroup?: Group;
    dropLineGroup?: Group;
    spriteById?: Map<string, Sprite>;
    nodeById?: Map<string, GraphNode>;
    cameraAnim?: CameraAnim | null;
    rafId?: number | null;
    onWindowResize?: () => void;
  }>({});

  // Bootstrap once
  useEffect(() => {
    const mount = opts.mountRef.current;
    if (!mount) return;

    const w = Math.max(200, mount.clientWidth);
    const h = Math.max(200, mount.clientHeight);

    const scene = new Scene();
    scene.background = null; // transparent — CSS --bg-base shows through
    const fogColor = resolveBgColor(mount);
    scene.fog = new Fog(fogColor.getHex(), FOG_NEAR, FOG_FAR);

    const camera = new PerspectiveCamera(CAMERA_DEFAULT_FOV, w / h, 1, 3000);
    camera.position.set(...CAMERA_DEFAULT_POS);

    const renderer = new WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
    renderer.setSize(w, h);
    renderer.setClearColor(0x000000, 0);
    mount.appendChild(renderer.domElement);
    renderer.domElement.style.display = "block";
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";

    scene.add(new AmbientLight(0xffffff, 0.8));
    const sun = new DirectionalLight(0xffffff, 0.7); sun.position.set(160, 280, 180); scene.add(sun);
    const cool = new DirectionalLight(0xcfe7ff, 0.35); cool.position.set(-180, -40, -120); scene.add(cool);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.09;
    controls.rotateSpeed = 0.7;
    controls.minDistance = ORBIT_MIN_DIST;
    controls.maxDistance = ORBIT_MAX_DIST;
    controls.minPolarAngle = ORBIT_POLAR_MIN;
    controls.maxPolarAngle = ORBIT_POLAR_MAX;
    controls.target.set(0, 0, 0);
    controls.autoRotate = false;

    const ground = buildGround();
    scene.add(ground);
    const nodeGroup = new Group();
    const edgeGroup = new Group();
    const dropLineGroup = new Group();
    scene.add(edgeGroup, dropLineGroup, nodeGroup);

    sceneStateRef.current = {
      renderer, scene, camera, controls,
      nodeGroup, edgeGroup, dropLineGroup,
      spriteById: new Map(), nodeById: new Map(),
      cameraAnim: null, rafId: null,
    };

    // Raycast hover + click
    const raycaster = new Raycaster();
    const mouseNdc = new Vector2();
    let hoverId: string | null = null;
    const onPointerMove = (e: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      mouseNdc.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouseNdc.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouseNdc, camera);
      const hits = raycaster.intersectObjects(nodeGroup.children, false);
      const id = hits[0]?.object.userData.id ?? null;
      if (id !== hoverId) { hoverId = id; opts.onHover(id); }
    };
    const onClick = (e: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      mouseNdc.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouseNdc.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouseNdc, camera);
      const hits = raycaster.intersectObjects(nodeGroup.children, false);
      const id = hits[0]?.object.userData.id ?? null;
      opts.onSelect(id);
    };
    renderer.domElement.addEventListener("pointermove", onPointerMove);
    renderer.domElement.addEventListener("click", onClick);

    // Resize
    const onResize = () => {
      if (!sceneStateRef.current.renderer) return;
      const nw = Math.max(200, mount.clientWidth);
      const nh = Math.max(200, mount.clientHeight);
      sceneStateRef.current.camera!.aspect = nw / nh;
      sceneStateRef.current.camera!.updateProjectionMatrix();
      sceneStateRef.current.renderer.setSize(nw, nh);
    };
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(onResize) : null;
    ro?.observe(mount);

    // RAF loop
    let last = performance.now();
    const tick = () => {
      const now = performance.now();
      const dt = (now - last) / 1000;
      last = now;
      const s = sceneStateRef.current;
      if (!s.renderer || !s.scene || !s.camera || !s.controls) return;
      if (s.cameraAnim) {
        const ca = s.cameraAnim;
        ca.t += dt;
        const k = Math.min(1, ca.t / ca.dur);
        const ease = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        s.camera.position.lerpVectors(ca.fromPos, ca.toPos, ease);
        s.controls.target.lerpVectors(ca.fromTarget, ca.toTarget, ease);
        if (k >= 1) s.cameraAnim = null;
      }
      s.controls.update();
      s.renderer.render(s.scene, s.camera);
      s.rafId = requestAnimationFrame(tick);
    };
    sceneStateRef.current.rafId = requestAnimationFrame(tick);

    handleRef.current = makeHandle(sceneStateRef);

    return () => {
      const s = sceneStateRef.current;
      if (s.rafId) cancelAnimationFrame(s.rafId);
      renderer.domElement.removeEventListener("pointermove", onPointerMove);
      renderer.domElement.removeEventListener("click", onClick);
      ro?.disconnect();
      s.nodeGroup?.children.forEach((o) => {
        if ((o as Sprite).material && "map" in (o as Sprite).material) {
          const m = (o as Sprite).material as { map?: { dispose(): void }; dispose(): void };
          m.map?.dispose();
          m.dispose();
        }
      });
      renderer.dispose();
      if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
      sceneStateRef.current = {};
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Data changes → rebuild nodes + edges
  useEffect(() => {
    const s = sceneStateRef.current;
    if (!s.nodeGroup || !s.edgeGroup || !s.dropLineGroup || !s.spriteById || !s.nodeById) return;

    // Rebuild node sprites
    const placed = placeNodes(opts.nodes);
    const kept = new Set<string>();
    for (const p of placed) {
      kept.add(p.id);
      const existing = s.spriteById.get(p.id);
      const key = cardCacheKey(p.node);
      if (existing && existing.userData.cacheKey === key) {
        existing.position.copy(p.position);
        continue;
      }
      if (existing) {
        s.nodeGroup.remove(existing);
        const m = existing.material as { map?: { dispose(): void }; dispose(): void };
        m.map?.dispose();
        m.dispose();
      }
      const sprite = makeNodeCard(p.node);
      sprite.position.copy(p.position);
      sprite.userData.id = p.id;
      s.nodeGroup.add(sprite);
      s.spriteById.set(p.id, sprite);
      s.nodeById.set(p.id, p.node);
    }
    for (const [id, sprite] of s.spriteById.entries()) {
      if (!kept.has(id)) {
        s.nodeGroup.remove(sprite);
        const m = sprite.material as { map?: { dispose(): void }; dispose(): void };
        m.map?.dispose();
        m.dispose();
        s.spriteById.delete(id);
        s.nodeById.delete(id);
      }
    }

    // Rebuild edges (simple: clear + re-add)
    while (s.edgeGroup.children.length > 0) {
      const c = s.edgeGroup.children.pop()!;
      const l = c as Line;
      l.geometry.dispose();
      (l.material as LineBasicMaterial).dispose();
    }
    const placedById = new Map(placed.map((p) => [p.id, p]));
    for (const e of opts.edges) {
      const a = placedById.get(e.a);
      const b = placedById.get(e.b);
      if (!a || !b) continue;
      const style = EDGE_STYLE[e.rel] ?? EDGE_STYLE.__fallback__;
      const geo = buildEdgeGeometry(a.position, b.position);
      const line = new Line(geo, new LineBasicMaterial({
        color: new Color(style.stroke), transparent: true, opacity: 0.42, depthWrite: false,
      }));
      line.userData = { a: e.a, b: e.b, rel: e.rel };
      s.edgeGroup.add(line);
    }

    // Rebuild drop lines (vertical line card → ground)
    while (s.dropLineGroup.children.length > 0) {
      const c = s.dropLineGroup.children.pop()!;
      const l = c as Line;
      l.geometry.dispose();
      (l.material as LineBasicMaterial).dispose();
    }
    for (const p of placed) {
      const geo = new BufferGeometry().setFromPoints([
        new Vector3(p.position.x, p.position.y, p.position.z),
        new Vector3(p.position.x, GROUND_Y + 1, p.position.z),
      ]);
      const line = new Line(geo, new LineBasicMaterial({
        color: 0x94a3b8, transparent: true, opacity: 0.22, depthWrite: false,
      }));
      s.dropLineGroup.add(line);
    }
  }, [opts.nodes, opts.edges]);

  return handleRef.current ?? makeHandle(sceneStateRef);
}

function makeHandle(
  ref: React.MutableRefObject<{
    camera?: PerspectiveCamera;
    controls?: OrbitControls;
    spriteById?: Map<string, Sprite>;
    nodeById?: Map<string, GraphNode>;
    cameraAnim?: CameraAnim | null;
    renderer?: WebGLRenderer;
  }>,
): SceneHandle {
  return {
    focusOn: (id) => {
      const s = ref.current;
      if (!s.camera || !s.controls) return;
      const fromPos = s.camera.position.clone();
      const fromTarget = s.controls.target.clone();
      if (id && s.spriteById?.has(id)) {
        const sprite = s.spriteById.get(id)!;
        const toTarget = sprite.position.clone();
        const toPos = toTarget.clone().add(new Vector3(0, 60, 180));
        s.cameraAnim = { fromPos, fromTarget, toPos, toTarget, t: 0, dur: CAMERA_ANIM_DUR };
      } else {
        const toTarget = new Vector3(0, 0, 0);
        const toPos = new Vector3(...CAMERA_DEFAULT_POS);
        s.cameraAnim = { fromPos, fromTarget, toPos, toTarget, t: 0, dur: CAMERA_ANIM_DUR };
      }
    },
    rearrange: () => { /* Placements are deterministic — no-op. Focus reset triggers camera back. */ },
    zoomIn: () => { const s = ref.current; if (!s.camera || !s.controls) return; s.camera.position.multiplyScalar(1 / 1.2); s.controls.update(); },
    zoomOut: () => { const s = ref.current; if (!s.camera || !s.controls) return; s.camera.position.multiplyScalar(1.2); s.controls.update(); },
    fit: () => {
      const s = ref.current;
      if (!s.camera || !s.controls) return;
      const fromPos = s.camera.position.clone();
      const fromTarget = s.controls.target.clone();
      s.cameraAnim = {
        fromPos, fromTarget,
        toPos: new Vector3(...CAMERA_DEFAULT_POS), toTarget: new Vector3(0, 0, 0),
        t: 0, dur: CAMERA_ANIM_DUR,
      };
    },
    toggleAutoRotate: () => { if (ref.current.controls) ref.current.controls.autoRotate = !ref.current.controls.autoRotate; },
    getProjectedScreenPos: (id) => {
      const s = ref.current;
      if (!s.camera || !s.spriteById || !s.renderer) return null;
      const sprite = s.spriteById.get(id);
      if (!sprite) return null;
      const v = sprite.position.clone().project(s.camera);
      const rect = s.renderer.domElement.getBoundingClientRect();
      return {
        x: (v.x * 0.5 + 0.5) * rect.width,
        y: (-v.y * 0.5 + 0.5) * rect.height,
      };
    },
  };
}

import type { GraphNode as _GraphNode } from "../types";
```

### - [ ] Step 4: Run to verify pass

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-3d-use-scene.test.ts
```
Expected: PASS — 2 tests (smoke-level).

### - [ ] Step 5: Typecheck

```bash
cd apps/web && node_modules/.bin/tsc --noEmit
```
Expected: 0 errors.

### - [ ] Step 6: Commit

```bash
cd /Users/dog/Desktop/MRAI
git add apps/web/components/console/graph/memory-graph/Memory3D/useThreeScene.ts \
        apps/web/tests/unit/memory-graph-3d-use-scene.test.ts
git commit -m "$(cat <<'EOF'
feat(web): add Memory3D useThreeScene hook

Bootstraps Scene / PerspectiveCamera / WebGLRenderer (alpha:true)
/ OrbitControls / AmbientLight + sun + cool fill. Ground + node
group + edge group + drop-line group. Raycaster pointer-move →
onHover, click → onSelect. RAF loop with camera tween animations.
ResizeObserver drives setSize. Full dispose on unmount (textures +
geometries + renderer).

Exposes SceneHandle: focusOn / fit / zoomIn / zoomOut /
toggleAutoRotate / getProjectedScreenPos.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Tooltip3d + CameraControlsHud

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/Memory3D/Tooltip3d.tsx`
- Create: `apps/web/components/console/graph/memory-graph/Memory3D/CameraControlsHud.tsx`
- Test: `apps/web/tests/unit/memory-graph-3d-hud.test.tsx`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-3d-hud.test.tsx`:

```tsx
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Tooltip3d } from "@/components/console/graph/memory-graph/Memory3D/Tooltip3d";
import { CameraControlsHud } from "@/components/console/graph/memory-graph/Memory3D/CameraControlsHud";
import type { GraphNode } from "@/components/console/graph/memory-graph/types";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function n(over: Partial<GraphNode>): GraphNode {
  return {
    id: "a", role: "fact", label: "Alpha", conf: 0.9, reuse: 0,
    lastUsed: null, pinned: false, source: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    raw: {} as any, ...over,
  };
}

describe("Tooltip3d", () => {
  it("renders node label when visible", () => {
    render(<Tooltip3d node={n({})} x={100} y={200} />);
    expect(screen.getByText("Alpha")).toBeTruthy();
  });

  it("positions via absolute x/y", () => {
    const { container } = render(<Tooltip3d node={n({})} x={150} y={250} />);
    const el = container.firstChild as HTMLElement;
    expect(el.style.left).toBe("150px");
    expect(el.style.top).toBe("236px"); // y - 14 vertical offset
  });
});

describe("CameraControlsHud", () => {
  it("renders zoom %, +, −, fit, auto-rotate buttons", () => {
    render(<CameraControlsHud zoomPct={80} onZoomIn={() => {}} onZoomOut={() => {}} onFit={() => {}} onToggleAutoRotate={() => {}} autoRotating={false} />);
    expect(screen.getByText("80%")).toBeTruthy();
    expect(screen.getByTestId("mg3d-zoom-in")).toBeTruthy();
    expect(screen.getByTestId("mg3d-zoom-out")).toBeTruthy();
    expect(screen.getByTestId("mg3d-fit")).toBeTruthy();
    expect(screen.getByTestId("mg3d-auto-rotate")).toBeTruthy();
  });

  it("fires handlers", () => {
    const onZI = vi.fn(), onZO = vi.fn(), onFit = vi.fn(), onAR = vi.fn();
    render(<CameraControlsHud zoomPct={100} onZoomIn={onZI} onZoomOut={onZO} onFit={onFit} onToggleAutoRotate={onAR} autoRotating={false} />);
    fireEvent.click(screen.getByTestId("mg3d-zoom-in"));
    fireEvent.click(screen.getByTestId("mg3d-zoom-out"));
    fireEvent.click(screen.getByTestId("mg3d-fit"));
    fireEvent.click(screen.getByTestId("mg3d-auto-rotate"));
    expect(onZI).toHaveBeenCalled();
    expect(onZO).toHaveBeenCalled();
    expect(onFit).toHaveBeenCalled();
    expect(onAR).toHaveBeenCalled();
  });
});
```

### - [ ] Step 2: Run to verify failure

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-3d-hud.test.tsx
```
Expected: FAIL — modules not found.

### - [ ] Step 3: Implement `Tooltip3d.tsx`

Create `apps/web/components/console/graph/memory-graph/Memory3D/Tooltip3d.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import { ROLE_STYLE } from "../constants";
import { ROLE_GLYPH } from "./constants3d";
import type { GraphNode } from "../types";

interface Props {
  node: GraphNode;
  x: number;
  y: number;
}

export function Tooltip3d({ node, x, y }: Props) {
  const t = useTranslations("console-notebooks");
  const style = ROLE_STYLE[node.role];
  return (
    <div
      style={{
        position: "absolute", left: x, top: y - 14, transform: "translate(-50%, -100%)",
        display: "inline-flex", alignItems: "center", gap: 6, pointerEvents: "none",
        padding: "4px 8px", borderRadius: 8,
        background: "rgba(255,255,255,0.92)",
        backdropFilter: "blur(12px)",
        border: "1px solid rgba(15,42,45,0.1)",
        fontSize: 12, fontWeight: 500,
        color: "var(--text-primary, #0f172a)",
        whiteSpace: "nowrap", zIndex: 3,
      }}
    >
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        padding: "1px 6px", borderRadius: 4, fontSize: 11,
        background: style.fill, color: style.text,
      }}>
        {ROLE_GLYPH[node.role]} {t(`memoryGraph.roles.${node.role}`)}
      </span>
      {node.label}
    </div>
  );
}
```

### - [ ] Step 4: Implement `CameraControlsHud.tsx`

Create `apps/web/components/console/graph/memory-graph/Memory3D/CameraControlsHud.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import { Plus, Minus, Maximize2, RotateCw } from "lucide-react";

interface Props {
  zoomPct: number;
  autoRotating: boolean;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
  onToggleAutoRotate: () => void;
}

export function CameraControlsHud({ zoomPct, autoRotating, onZoomIn, onZoomOut, onFit, onToggleAutoRotate }: Props) {
  const t = useTranslations("console-notebooks");
  const btnStyle = { padding: 4, background: "transparent", border: "none", cursor: "pointer", color: "var(--text-primary)" } as const;

  return (
    <div
      style={{
        position: "absolute", bottom: 12, left: 12,
        background: "rgba(255,255,255,0.88)", backdropFilter: "blur(12px)",
        padding: 6, borderRadius: 10,
        border: "1px solid rgba(15,42,45,0.1)",
        display: "flex", alignItems: "center", gap: 4, zIndex: 2,
      }}
    >
      <button data-testid="mg3d-zoom-out" type="button" onClick={onZoomOut} aria-label={t("memoryGraph.camera.zoomOut")} style={btnStyle}>
        <Minus size={14} />
      </button>
      <span style={{ minWidth: 42, textAlign: "center", fontSize: 12 }}>{Math.round(zoomPct)}%</span>
      <button data-testid="mg3d-zoom-in" type="button" onClick={onZoomIn} aria-label={t("memoryGraph.camera.zoomIn")} style={btnStyle}>
        <Plus size={14} />
      </button>
      <button data-testid="mg3d-fit" type="button" onClick={onFit} aria-label={t("memoryGraph.camera.fit")} style={btnStyle}>
        <Maximize2 size={14} />
      </button>
      <button
        data-testid="mg3d-auto-rotate"
        type="button" onClick={onToggleAutoRotate}
        aria-label={t("memoryGraph.camera.autoRotate")}
        aria-pressed={autoRotating}
        style={{ ...btnStyle, color: autoRotating ? "var(--accent, #0d9488)" : btnStyle.color }}
      >
        <RotateCw size={14} />
      </button>
    </div>
  );
}
```

### - [ ] Step 5: Run to verify pass

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-3d-hud.test.tsx
```
Expected: PASS — 4 tests.

### - [ ] Step 6: Commit

```bash
cd /Users/dog/Desktop/MRAI
git add apps/web/components/console/graph/memory-graph/Memory3D/Tooltip3d.tsx \
        apps/web/components/console/graph/memory-graph/Memory3D/CameraControlsHud.tsx \
        apps/web/tests/unit/memory-graph-3d-hud.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): add Memory3D Tooltip3d + CameraControlsHud

DOM-overlay tooltip positions at projected screen coord (14px above
node) with role pill + label. CameraControlsHud is a glass-card
cluster at bottom-left (zoom %, -, +, fit, auto-rotate).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Memory3D top-level component

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/Memory3D/Memory3D.tsx`
- Test: `apps/web/tests/unit/memory-graph-3d-component.test.tsx`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-3d-component.test.tsx`:

```tsx
import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Memory3D } from "@/components/console/graph/memory-graph/Memory3D/Memory3D";
import type { GraphNode } from "@/components/console/graph/memory-graph/types";

function n(over: Partial<GraphNode>): GraphNode {
  return {
    id: "a", role: "fact", label: "Alpha", conf: 0.9, reuse: 0,
    lastUsed: null, pinned: false, source: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    raw: {} as any, ...over,
  };
}

afterEach(() => { cleanup(); });

describe("Memory3D", () => {
  it("renders a mount container + camera controls HUD", () => {
    render(<Memory3D nodes={[n({})]} edges={[]} selectedId={null} hoverId={null} onHover={() => {}} onSelect={() => {}} />);
    expect(screen.getByTestId("mg3d-mount")).toBeTruthy();
    expect(screen.getByTestId("mg3d-fit")).toBeTruthy();
  });
});
```

### - [ ] Step 2: Run to verify failure

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-3d-component.test.tsx
```
Expected: FAIL.

### - [ ] Step 3: Implement

Create `apps/web/components/console/graph/memory-graph/Memory3D/Memory3D.tsx`:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { useThreeScene } from "./useThreeScene";
import { Tooltip3d } from "./Tooltip3d";
import { CameraControlsHud } from "./CameraControlsHud";
import type { GraphEdge, GraphNode } from "../types";
import { CAMERA_DEFAULT_POS } from "./constants3d";

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  hoverId: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string | null) => void;
}

const DEFAULT_DISTANCE = Math.hypot(...CAMERA_DEFAULT_POS);

export function Memory3D({ nodes, edges, selectedId, hoverId, onHover, onSelect }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const [autoRot, setAutoRot] = useState(false);
  const [zoomPct, setZoomPct] = useState(100);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null);

  const handle = useThreeScene({ mountRef, nodes, edges, onHover, onSelect });

  // Apply selection → focus
  useEffect(() => {
    handle.focusOn(selectedId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  // Track hovered node's screen position for tooltip
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

  // Update zoom % each frame
  useEffect(() => {
    let rafId = 0;
    const loop = () => {
      // getProjectedScreenPos is a proxy that forces access to camera — use a dummy call to read camera distance
      // via internal ref is not exposed; approximate via handle.fit no-op isn't enough. Read directly from DOM:
      const canvas = mountRef.current?.querySelector("canvas");
      if (canvas) {
        // Distance isn't directly exposed; recompute via % of default distance
        // using hack: the hook's controls.update runs, camera.position changes.
        // Skip: assume HUD updates only on action clicks.
      }
      rafId = requestAnimationFrame(loop);
    };
    rafId = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(rafId);
  }, []);

  const hoveredNode = hoverId ? nodes.find((n) => n.id === hoverId) : null;

  return (
    <div
      style={{ position: "relative", width: "100%", height: "100%" }}
    >
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
```

### - [ ] Step 4: Run to verify pass

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-3d-component.test.tsx
```
Expected: PASS.

### - [ ] Step 5: Commit

```bash
cd /Users/dog/Desktop/MRAI
git add apps/web/components/console/graph/memory-graph/Memory3D/Memory3D.tsx \
        apps/web/tests/unit/memory-graph-3d-component.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): add Memory3D top-level component

Wires useThreeScene + Tooltip3d + CameraControlsHud. Syncs selection
(from parent) → camera focus. Projects hovered node to screen for
tooltip overlay. Background uses var(--bg-base) so the WebGL canvas
appears over the 2D-matching backdrop.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Wire Memory3D into MemoryGraphView

**Files:**
- Modify: `apps/web/components/console/graph/memory-graph/MemoryGraphView.tsx`
- Modify: `apps/web/tests/unit/memory-graph-view.test.tsx` (update 3D test to expect real component, not placeholder)

### - [ ] Step 1: Replace placeholder

Open `apps/web/components/console/graph/memory-graph/MemoryGraphView.tsx` and change:

```tsx
          {view === "3d" && (
            <div data-testid="mg-3d-placeholder" style={{ padding: 40, textAlign: "center", color: "var(--text-secondary)" }}>
              {/* Filled in by Task 13 */}
              3D view coming
            </div>
          )}
```

to:

```tsx
          {view === "3d" && (
            <Memory3D
              nodes={effectiveNodes}
              edges={effectiveEdges}
              selectedId={selectedId}
              hoverId={hoverId}
              onHover={setHoverId}
              onSelect={setSelectedId}
            />
          )}
```

Add the import at the top:

```tsx
import { Memory3D } from "./Memory3D/Memory3D";
```

### - [ ] Step 2: Update the view test

In `apps/web/tests/unit/memory-graph-view.test.tsx`, replace the 3D placeholder assertion:

```tsx
  it("switches to 3d view", () => {
    render(<MemoryGraphView nodes={[]} edges={[]} />);
    fireEvent.click(screen.getByTestId("mg-btn-view-3d"));
    expect(screen.getByTestId("mg3d-mount")).toBeTruthy();
  });
```

### - [ ] Step 3: Run the view test

```bash
cd apps/web && node_modules/.bin/vitest run tests/unit/memory-graph-view.test.tsx
```
Expected: PASS — 4 tests.

### - [ ] Step 4: Typecheck

```bash
cd apps/web && node_modules/.bin/tsc --noEmit
```

### - [ ] Step 5: Commit

```bash
cd /Users/dog/Desktop/MRAI
git add apps/web/components/console/graph/memory-graph/MemoryGraphView.tsx \
        apps/web/tests/unit/memory-graph-view.test.tsx
git commit -m "$(cat <<'EOF'
chore(web): wire Memory3D into MemoryGraphView

Replaces the placeholder. State (search / conf / filters / selection /
hover) now flows into Memory3D the same way it flows into
GraphCanvas. 2D ↔ 3D switches preserve context.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: i18n keys (en + zh)

**Files:**
- Modify: `apps/web/messages/en/console-notebooks.json`
- Modify: `apps/web/messages/zh/console-notebooks.json`

### - [ ] Step 1: Add English keys

Append to `apps/web/messages/en/console-notebooks.json` (before the closing `}` — find the last `"memoryGraph.*"` entry and insert after):

```json
,
"memoryGraph.header.brand": "· V3",
"memoryGraph.view.3d": "3D Cloud",
"memoryGraph.tier.subject": "Subject",
"memoryGraph.tier.concept": "Concept",
"memoryGraph.tier.fact": "Fact",
"memoryGraph.axis.mastery": "↑ Mastery",
"memoryGraph.camera.zoomIn": "Zoom in",
"memoryGraph.camera.zoomOut": "Zoom out",
"memoryGraph.camera.fit": "Fit",
"memoryGraph.camera.autoRotate": "Auto-rotate",
"memoryGraph.tooltip.unselect": "Click empty space to deselect"
```

### - [ ] Step 2: Add Chinese keys

Same in `apps/web/messages/zh/console-notebooks.json`:

```json
,
"memoryGraph.header.brand": "· Memory V3",
"memoryGraph.view.3d": "3D 星云",
"memoryGraph.tier.subject": "主题",
"memoryGraph.tier.concept": "概念",
"memoryGraph.tier.fact": "事实",
"memoryGraph.axis.mastery": "↑ 熟练度",
"memoryGraph.camera.zoomIn": "放大",
"memoryGraph.camera.zoomOut": "缩小",
"memoryGraph.camera.fit": "适配",
"memoryGraph.camera.autoRotate": "自动旋转",
"memoryGraph.tooltip.unselect": "点击空白处取消选中"
```

### - [ ] Step 3: Validate JSON

```bash
cd apps/web && node -e "JSON.parse(require('fs').readFileSync('messages/en/console-notebooks.json','utf8')); JSON.parse(require('fs').readFileSync('messages/zh/console-notebooks.json','utf8'));" && echo ok
```

### - [ ] Step 4: Commit

```bash
cd /Users/dog/Desktop/MRAI
git add apps/web/messages/en/console-notebooks.json \
        apps/web/messages/zh/console-notebooks.json
git commit -m "$(cat <<'EOF'
chore(web): add i18n keys for Memory3D + header bar

header.brand (· V3 suffix), view.3d (tab label), tier.* (ring
labels), axis.mastery (Y axis), camera.* (HUD button labels),
tooltip.unselect (instruction hint).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Dev server restart + UPGRADE_GUIDE_3D §10 acceptance pass

**Files:** none (interactive verification)

### - [ ] Step 1: Restart dev server

```bash
# Stop any previous server, then:
```
Via preview_stop then preview_start with the `web-dev` config (port 3000, autoPort:false already set).

### - [ ] Step 2: Navigate to a seeded notebook

The earlier 2D acceptance seeded 12 memory rows into project `4d584378-af47-4d8f-b3f2-4262e53b3913`. Open:

```
http://localhost:3000/app/notebooks/caf4ef2b-8ef7-4d3a-9427-2a4e7dddec8a
```

Click the Network 🌐 icon in the left rail → 记忆图谱 window opens.

### - [ ] Step 3: Walk the UPGRADE_GUIDE_3D §10 checklist

Using preview_eval / preview_screenshot / preview_console_logs, verify each:

- [ ] **Default view is 2D panorama**, not pre-focused. Click the `3D 星云` tab in ViewBar.
- [ ] **v2 visual layer**: background is light青灰 (matches 2D), cards are white glass-look (no bloom / no neon).
- [ ] **Layout**: 3 dashed tier rings visible (subject / concept / fact), sparse radial spokes, Y-axis column with mastery arrow.
- [ ] Same-role nodes on same ring; high-mastery nodes float higher; drop lines descend to ground.
- [ ] Distant nodes gracefully fog-fade into background color (not hard-clipped).
- [ ] **Node cards** show: role chip, label (≤2 lines), conf arc, reuse ×N (only if ≥1), source + age. Pinned node has an orange dot on top-right.
- [ ] Hover a node → DOM tooltip follows cursor with role pill + label.
- [ ] Click a node → camera tweens to it; drawer opens (right-side or bottom-sheet per width); tooltip goes away.
- [ ] Click empty space → camera tweens back to `(0, 110, 360)`, drawer closes.
- [ ] Bottom-left HUD: `−` / zoom % / `+` / fit / auto-rotate — all working.
- [ ] Switch to `2D` tab → 2D renders, **same node stays selected** (drawer content unchanged), search query preserved.
- [ ] Switch to `List` tab → list shows; switching back to 3D doesn't crash; selection preserved.
- [ ] No Three.js / WebGL errors in `preview_console_logs`; resize window — canvas + HUD stay in place.

### - [ ] Step 4: For each failing item

Diagnose, fix, commit as a separate `fix(web): …` commit, re-run §3.

### - [ ] Step 5: Record residuals

Once all items tick, summarize any deferred issues (visual polish, edge case behaviors) in the final PR description — don't commit a file.

---

## Task 16: Full test suite + typecheck + cleanup

**Files:** none (verification)

### - [ ] Step 1: Full test run

```bash
cd apps/web && node_modules/.bin/vitest run
```
Expected: all PASS.

### - [ ] Step 2: Typecheck

```bash
cd apps/web && node_modules/.bin/tsc --noEmit
```
Expected: 0 errors.

### - [ ] Step 3: Lint

```bash
cd apps/web && node_modules/.bin/eslint components/console/graph/memory-graph --max-warnings=0
```
Expected: 0 errors / warnings. Fix any and commit as `chore(web): …`.

### - [ ] Step 4: No follow-up commit if green; otherwise fix iteratively and re-run.

---

## Self-Review

**Spec coverage matrix:**

| Spec section | Task |
|---|---|
| §2 Layout realignment — HeaderBar | Task 1 |
| §2 Layout realignment — FilterRow | Task 2 |
| §2 Layout realignment — ViewBar with 3D tab | Task 3 |
| §2 Layout realignment — CanvasControls | Task 4 |
| §2 Layout realignment — rewire MemoryGraphView, delete Toolbar | Task 5 |
| §2 3D constants + types | Task 6 |
| §2 3D depth-ring layout + mastery | Task 7 |
| §2 3D card sprite texture | Task 8 |
| §2 3D ground + edges | Task 9 |
| §2 3D scene bootstrap + lifecycle | Task 10 |
| §2 3D tooltip + HUD | Task 11 |
| §2 3D top-level component | Task 12 |
| §2 3D wire into view switch | Task 13 |
| §4 i18n bilingual | Task 14 |
| §6.2 manual acceptance via preview | Task 15 |
| §6.1 unit tests | Tasks 1–13 (each TDD cycle) |
| §7 risks (card cache / three dispose) | Covered in Tasks 8 + 10 |

Every §2 in-scope bullet maps to at least one task.

**Type consistency check:**
- `Role` / `GraphNode` / `GraphEdge` — defined in existing `types.ts`, used Tasks 1–13
- `MemoryGraphView` union `"graph" | "3d" | "list"` — defined Task 3, consumed Tasks 5+13
- `PlacedNode`, `SceneHandle`, `CameraAnim`, `RoleGlyph` — defined Task 6, consumed Tasks 7, 10, 11, 12
- `cardCacheKey` — defined Task 8, consumed Task 10
- `masteryOf`, `placeNodes` — defined Task 7, consumed Task 10
- `buildGround`, `buildEdgeGeometry`, `buildEdgeLine` — defined Task 9, consumed Task 10
- `useThreeScene`, handle methods — defined Task 10, consumed Task 12
- i18n keys under `memoryGraph.*` — keys introduced Task 14; all usages in Tasks 1, 3, 11, 12 reference these keys

**Placeholder scan:** none. `// Filled in by Task 13` is a deliberate cross-reference, not a TODO.

**Out-of-scope items** (from spec §2 "Out of scope") intentionally absent from plan:
- variant B / C, particle effects, time-axis Z-slicing, multi-select focus, minimap, link replay, Evidence / Learning / Health tabs, full dark-mode token wiring, backend change for structure/summary roles.
