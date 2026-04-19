# Memory Graph Window — 2D Force-Directed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new `memory_graph` notebook window that renders the project's memory graph as an interactive 2D force-directed diagram (Verlet sim, 5-role palette, live via `useGraphData` + SSE), per `docs/superpowers/specs/2026-04-19-memory-graph-window-2d-design.md`.

**Architecture:** New folder `apps/web/components/console/graph/memory-graph/` holds the view internals (canvas, hook, drawer, toolbar, list). Window shell `apps/web/components/notebook/contents/MemoryGraphWindow.tsx` owns view state and uses existing `useGraphData(projectId)`. `WindowManager` gets a new window type, `WindowCanvas` routes to the new content, `NotebookSidebar` gets a new tab button. All filtering is client-side against existing `/api/v1/memory?project_id=…` endpoint — no backend changes.

**Tech Stack:** Next.js 16, TypeScript, React 19, vitest + @testing-library/react, next-intl, SVG (no d3-force — self-implement Verlet per guide §3), lucide-react icons.

**Test commands:**
- Unit run: `pnpm --filter web test:unit -- <path>` (runs once, CI-mode)
- Unit watch: `pnpm --filter web test:unit:watch`
- Typecheck: `pnpm --filter web tsc --noEmit`
- Lint: `pnpm --filter web lint`
- Dev server: `pnpm --filter web dev` (port 3000)

**Commit policy:** One commit per task. Use `feat(web): …` for new code, `chore(web): …` for registration/wiring, `test(web): …` if a task is test-only. Co-author line is mandatory.

---

## Task 1: Scaffold + types + constants

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/types.ts`
- Create: `apps/web/components/console/graph/memory-graph/constants.ts`
- Test: `apps/web/tests/unit/memory-graph-constants.test.ts`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-constants.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  ROLE_STYLE,
  EDGE_STYLE,
  FORCE_PARAMS,
  VIEWPORT_DEFAULTS,
} from "@/components/console/graph/memory-graph/constants";
import type { Role } from "@/components/console/graph/memory-graph/types";

describe("memory-graph constants", () => {
  it("exposes one ROLE_STYLE entry per role (5 total)", () => {
    const roles: Role[] = ["fact", "structure", "subject", "concept", "summary"];
    expect(Object.keys(ROLE_STYLE).sort()).toEqual([...roles].sort());
    for (const r of roles) {
      expect(ROLE_STYLE[r]).toMatchObject({
        fill: expect.any(String),
        stroke: expect.any(String),
        text: expect.any(String),
        dot: expect.any(String),
      });
    }
  });

  it("exposes one EDGE_STYLE entry per backend edge_type (11 total, plus fallback)", () => {
    const expected = [
      "parent", "center", "supersedes", "conflict", "prerequisite",
      "evidence", "summary", "related", "auto", "manual", "file",
      "__fallback__",
    ];
    expect(Object.keys(EDGE_STYLE).sort()).toEqual([...expected].sort());
    for (const key of expected) {
      expect(EDGE_STYLE[key]).toMatchObject({
        stroke: expect.any(String),
        width: expect.any(Number),
        style: expect.stringMatching(/^(solid|dashed)$/),
      });
    }
  });

  it("FORCE_PARAMS matches UPGRADE_GUIDE.md §3.2", () => {
    expect(FORCE_PARAMS).toEqual({
      linkDistance: 90,
      linkStrength: 0.06,
      charge: -340,
      centerStrength: 0.015,
      collide: 38,
      damping: 0.82,
      alphaInit: 1,
      alphaDecay: 0.985,
      alphaMin: 0.001,
    });
  });

  it("VIEWPORT_DEFAULTS has identity transform + MIN/MAX zoom", () => {
    expect(VIEWPORT_DEFAULTS).toEqual({
      k: 1, tx: 0, ty: 0, kMin: 0.4, kMax: 2.5,
    });
  });
});
```

### - [ ] Step 2: Run test to verify it fails

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-constants.test.ts
```
Expected: FAIL — `Cannot find module '.../memory-graph/constants'`.

### - [ ] Step 3: Create `types.ts`

Create `apps/web/components/console/graph/memory-graph/types.ts`:

```ts
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
```

### - [ ] Step 4: Create `constants.ts`

Create `apps/web/components/console/graph/memory-graph/constants.ts`:

```ts
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

export const FOCUS_PRIMARY = "#0D9488";         // teal, focused edge + node halo
export const OPACITY_NORMAL_NODE = 1;
export const OPACITY_NORMAL_EDGE = 0.65;
export const OPACITY_DIM_NODE = 0.38;
export const OPACITY_DIM_EDGE = 0.15;
export const OPACITY_SEARCH_MISS = 0.18;
export const TRANSITION_MS = 200;
export const LABEL_MAX_CHARS = 28;
```

### - [ ] Step 5: Run test to verify it passes

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-constants.test.ts
```
Expected: PASS — 4 tests.

### - [ ] Step 6: Typecheck

```bash
pnpm --filter web tsc --noEmit
```
Expected: 0 errors.

### - [ ] Step 7: Commit

```bash
git add apps/web/components/console/graph/memory-graph/types.ts \
        apps/web/components/console/graph/memory-graph/constants.ts \
        apps/web/tests/unit/memory-graph-constants.test.ts
git commit -m "$(cat <<'EOF'
feat(web): scaffold memory-graph types and constants

5-role palette (fact/structure/subject/concept/summary), 11+1 edge
styles, FORCE_PARAMS per UPGRADE_GUIDE.md §3.2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: humanize.ts — relative timestamp utility

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/humanize.ts`
- Test: `apps/web/tests/unit/memory-graph-humanize.test.ts`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-humanize.test.ts`:

```ts
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { humanizeRelativeTime } from "@/components/console/graph/memory-graph/humanize";

describe("humanizeRelativeTime", () => {
  const NOW = new Date("2026-04-19T12:00:00Z").getTime();

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => vi.useRealTimers());

  it("returns null for null/undefined/empty", () => {
    expect(humanizeRelativeTime(null)).toBeNull();
    expect(humanizeRelativeTime(undefined)).toBeNull();
    expect(humanizeRelativeTime("")).toBeNull();
  });

  it("returns null for unparseable strings", () => {
    expect(humanizeRelativeTime("not-a-date")).toBeNull();
  });

  it("formats minutes under an hour", () => {
    expect(humanizeRelativeTime(new Date(NOW - 30 * 60_000).toISOString())).toBe("30m");
    expect(humanizeRelativeTime(new Date(NOW - 1 * 60_000).toISOString())).toBe("1m");
    expect(humanizeRelativeTime(new Date(NOW - 0).toISOString())).toBe("0m");
  });

  it("formats hours under a day", () => {
    expect(humanizeRelativeTime(new Date(NOW - 2 * 3600_000).toISOString())).toBe("2h");
    expect(humanizeRelativeTime(new Date(NOW - 23 * 3600_000).toISOString())).toBe("23h");
  });

  it("formats days", () => {
    expect(humanizeRelativeTime(new Date(NOW - 3 * 86400_000).toISOString())).toBe("3d");
    expect(humanizeRelativeTime(new Date(NOW - 30 * 86400_000).toISOString())).toBe("30d");
  });

  it("floors future timestamps to 0m (do not display negative offsets)", () => {
    expect(humanizeRelativeTime(new Date(NOW + 5 * 60_000).toISOString())).toBe("0m");
  });
});
```

### - [ ] Step 2: Run test to verify it fails

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-humanize.test.ts
```
Expected: FAIL — `Cannot find module '.../humanize'`.

### - [ ] Step 3: Write minimal implementation

Create `apps/web/components/console/graph/memory-graph/humanize.ts`:

```ts
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function humanizeRelativeTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const ts = new Date(iso).getTime();
  if (!Number.isFinite(ts)) return null;
  const deltaMs = Math.max(0, Date.now() - ts);
  if (deltaMs < HOUR) return `${Math.floor(deltaMs / MINUTE)}m`;
  if (deltaMs < DAY) return `${Math.floor(deltaMs / HOUR)}h`;
  return `${Math.floor(deltaMs / DAY)}d`;
}
```

### - [ ] Step 4: Run test to verify it passes

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-humanize.test.ts
```
Expected: PASS — 6 tests.

### - [ ] Step 5: Commit

```bash
git add apps/web/components/console/graph/memory-graph/humanize.ts \
        apps/web/tests/unit/memory-graph-humanize.test.ts
git commit -m "$(cat <<'EOF'
feat(web): add humanizeRelativeTime utility for memory-graph

Converts ISO timestamps to "2h" / "3d" / "30m" form, nulls out on
bad input, floors future timestamps to 0m.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: adapter.ts — backend → GraphNode/GraphEdge mapping

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/adapter.ts`
- Test: `apps/web/tests/unit/memory-graph-adapter.test.ts`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-adapter.test.ts`:

```ts
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { adaptGraphData } from "@/components/console/graph/memory-graph/adapter";
import type { MemoryNode, MemoryEdge } from "@/hooks/useGraphData";

function makeNode(overrides: Partial<MemoryNode> = {}): MemoryNode {
  const now = "2026-04-19T10:00:00Z";
  return {
    id: "n1",
    workspace_id: "w",
    project_id: "p",
    content: "hello",
    category: "fact",
    type: "permanent",
    confidence: 0.8,
    observed_at: null,
    valid_from: null,
    valid_to: null,
    last_confirmed_at: null,
    source_conversation_id: null,
    parent_memory_id: null,
    position_x: null,
    position_y: null,
    node_type: "fact",
    subject_kind: null,
    subject_memory_id: null,
    node_status: null,
    canonical_key: null,
    lineage_key: null,
    metadata_json: {},
    created_at: now,
    updated_at: now,
    ...overrides,
  };
}

function makeEdge(overrides: Partial<MemoryEdge> = {}): MemoryEdge {
  return {
    id: "e1",
    source_memory_id: "n1",
    target_memory_id: "n2",
    edge_type: "related",
    strength: 0.5,
    confidence: null,
    observed_at: null,
    valid_from: null,
    valid_to: null,
    metadata_json: {},
    created_at: "2026-04-19T10:00:00Z",
    ...overrides,
  };
}

describe("adaptGraphData — node role derivation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-19T12:00:00Z").getTime());
  });
  afterEach(() => vi.useRealTimers());

  it("maps fact nodes", () => {
    const { nodes } = adaptGraphData({ nodes: [makeNode({ node_type: "fact" })], edges: [] });
    expect(nodes[0].role).toBe("fact");
  });

  it("maps concept nodes", () => {
    const { nodes } = adaptGraphData({
      nodes: [makeNode({ node_type: "concept", metadata_json: { node_kind: "concept" } })],
      edges: [],
    });
    expect(nodes[0].role).toBe("concept");
  });

  it("maps subject nodes", () => {
    const { nodes } = adaptGraphData({
      nodes: [makeNode({ node_type: "subject", metadata_json: { node_kind: "subject" } })],
      edges: [],
    });
    expect(nodes[0].role).toBe("subject");
  });

  it("maps summary nodes", () => {
    const { nodes } = adaptGraphData({
      nodes: [makeNode({ metadata_json: { node_kind: "summary", memory_kind: "summary" } })],
      edges: [],
    });
    expect(nodes[0].role).toBe("summary");
  });

  it("maps structure nodes (category-path / structural_only)", () => {
    const { nodes } = adaptGraphData({
      nodes: [
        makeNode({
          metadata_json: { node_kind: "category-path", concept_source: "category_path", structural_only: true },
        }),
      ],
      edges: [],
    });
    expect(nodes[0].role).toBe("structure");
  });
});

describe("adaptGraphData — field mapping", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-19T12:00:00Z").getTime());
  });
  afterEach(() => vi.useRealTimers());

  it("truncates long content to LABEL_MAX_CHARS + ellipsis", () => {
    const long = "x".repeat(60);
    const { nodes } = adaptGraphData({ nodes: [makeNode({ content: long })], edges: [] });
    expect(nodes[0].label.length).toBeLessThanOrEqual(29); // 28 chars + "…"
    expect(nodes[0].label.endsWith("…")).toBe(true);
  });

  it("keeps short content intact", () => {
    const { nodes } = adaptGraphData({ nodes: [makeNode({ content: "hi" })], edges: [] });
    expect(nodes[0].label).toBe("hi");
  });

  it("falls back conf to 0.5 when confidence is null", () => {
    const { nodes } = adaptGraphData({ nodes: [makeNode({ confidence: null })], edges: [] });
    expect(nodes[0].conf).toBe(0.5);
  });

  it("reads reuse from metadata_json.retrieval_count (default 0)", () => {
    const { nodes } = adaptGraphData({
      nodes: [
        makeNode({ metadata_json: { retrieval_count: 7 } }),
        makeNode({ id: "n2", metadata_json: {} }),
      ],
      edges: [],
    });
    expect(nodes[0].reuse).toBe(7);
    expect(nodes[1].reuse).toBe(0);
  });

  it("humanizes metadata_json.last_used_at", () => {
    const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60_000).toISOString();
    const { nodes } = adaptGraphData({
      nodes: [makeNode({ metadata_json: { last_used_at: twoHoursAgo } })],
      edges: [],
    });
    expect(nodes[0].lastUsed).toBe("2h");
  });

  it("coerces pinned to boolean", () => {
    const { nodes } = adaptGraphData({
      nodes: [
        makeNode({ id: "a", metadata_json: { pinned: true } }),
        makeNode({ id: "b", metadata_json: { pinned: false } }),
        makeNode({ id: "c", metadata_json: {} }),
      ],
      edges: [],
    });
    expect(nodes[0].pinned).toBe(true);
    expect(nodes[1].pinned).toBe(false);
    expect(nodes[2].pinned).toBe(false);
  });

  it("reads source from metadata_json.category_label, falling back to node.category", () => {
    const { nodes } = adaptGraphData({
      nodes: [
        makeNode({ id: "a", category: "root.cat", metadata_json: { category_label: "Prettier" } }),
        makeNode({ id: "b", category: "root.cat", metadata_json: {} }),
      ],
      edges: [],
    });
    expect(nodes[0].source).toBe("Prettier");
    expect(nodes[1].source).toBe("root.cat");
  });

  it("drops nodes that are not display-type memory (center/file roles excluded)", () => {
    const { nodes } = adaptGraphData({
      nodes: [
        makeNode({ id: "a", node_type: "fact" }),
        makeNode({ id: "b", node_type: "root", metadata_json: { node_kind: "assistant-root" } }),
        makeNode({ id: "c", category: "file", metadata_json: { node_kind: "file" } }),
      ],
      edges: [],
    });
    expect(nodes.map((n) => n.id).sort()).toEqual(["a"]);
  });
});

describe("adaptGraphData — edges", () => {
  it("maps backend edge fields straight through", () => {
    const { edges } = adaptGraphData({
      nodes: [makeNode({ id: "a" }), makeNode({ id: "b" })],
      edges: [
        makeEdge({ id: "e1", source_memory_id: "a", target_memory_id: "b", edge_type: "evidence", strength: 0.8 }),
      ],
    });
    expect(edges).toEqual([{ a: "a", b: "b", rel: "evidence", w: 0.8 }]);
  });

  it("drops edges whose endpoints were filtered out", () => {
    const { edges } = adaptGraphData({
      nodes: [
        makeNode({ id: "a" }),
        makeNode({ id: "center", node_type: "root", metadata_json: { node_kind: "assistant-root" } }),
      ],
      edges: [makeEdge({ source_memory_id: "a", target_memory_id: "center" })],
    });
    expect(edges).toEqual([]);
  });
});
```

### - [ ] Step 2: Run test to verify it fails

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-adapter.test.ts
```
Expected: FAIL — `Cannot find module '.../adapter'`.

### - [ ] Step 3: Write implementation

Create `apps/web/components/console/graph/memory-graph/adapter.ts`:

```ts
import type { MemoryNode as BackendNode, MemoryEdge as BackendEdge } from "@/hooks/useGraphData";
import {
  getGraphNodeDisplayType,
  getMemoryNodeRole,
  isPinnedMemoryNode,
  getMemoryRetrievalCount,
  getMemoryLastUsedAt,
  getMemoryCategoryLabel,
} from "@/hooks/useGraphData";
import { LABEL_MAX_CHARS } from "./constants";
import { humanizeRelativeTime } from "./humanize";
import type { GraphEdge, GraphNode, Role } from "./types";

function truncateLabel(content: string): string {
  const trimmed = (content ?? "").trim();
  if (trimmed.length <= LABEL_MAX_CHARS) return trimmed;
  return trimmed.slice(0, LABEL_MAX_CHARS) + "…";
}

function resolveRole(node: BackendNode): Role | null {
  // getMemoryNodeRole returns "fact" | "structure" | "subject" | "concept" | "summary" | null
  const role = getMemoryNodeRole(node);
  return role;
}

function adaptNode(node: BackendNode): GraphNode | null {
  // Display-type gate: skip center (assistant root) + file nodes
  const displayType = getGraphNodeDisplayType(node);
  if (displayType !== "memory") return null;

  const role = resolveRole(node);
  if (!role) return null;

  const categoryLabel = getMemoryCategoryLabel(node);
  const source = categoryLabel || (typeof node.category === "string" ? node.category : null) || null;

  return {
    id: node.id,
    role,
    label: truncateLabel(node.content || ""),
    conf: typeof node.confidence === "number" && Number.isFinite(node.confidence) ? node.confidence : 0.5,
    reuse: getMemoryRetrievalCount(node),
    lastUsed: humanizeRelativeTime(getMemoryLastUsedAt(node)),
    pinned: isPinnedMemoryNode(node),
    source: source || null,
    raw: node,
  };
}

function adaptEdge(edge: BackendEdge, nodeIds: Set<string>): GraphEdge | null {
  if (!nodeIds.has(edge.source_memory_id) || !nodeIds.has(edge.target_memory_id)) {
    return null;
  }
  return {
    a: edge.source_memory_id,
    b: edge.target_memory_id,
    rel: edge.edge_type,
    w: typeof edge.strength === "number" && Number.isFinite(edge.strength) ? edge.strength : 0.5,
  };
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export function adaptGraphData(raw: { nodes: BackendNode[]; edges: BackendEdge[] }): GraphData {
  const nodes: GraphNode[] = [];
  for (const bn of raw.nodes) {
    const gn = adaptNode(bn);
    if (gn) nodes.push(gn);
  }
  const ids = new Set(nodes.map((n) => n.id));
  const edges: GraphEdge[] = [];
  for (const be of raw.edges) {
    const ge = adaptEdge(be, ids);
    if (ge) edges.push(ge);
  }
  return { nodes, edges };
}
```

### - [ ] Step 4: Run test to verify it passes

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-adapter.test.ts
```
Expected: PASS — all cases green.

### - [ ] Step 5: Typecheck

```bash
pnpm --filter web tsc --noEmit
```
Expected: 0 errors.

### - [ ] Step 6: Commit

```bash
git add apps/web/components/console/graph/memory-graph/adapter.ts \
        apps/web/tests/unit/memory-graph-adapter.test.ts
git commit -m "$(cat <<'EOF'
feat(web): add memory-graph adapter (backend → GraphNode/GraphEdge)

5-role derivation via existing getMemoryNodeRole, label truncation,
conf/reuse/pinned/source fallbacks, edge filtering by live node set.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: useForceSim.ts — Verlet simulation hook

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/useForceSim.ts`
- Test: `apps/web/tests/unit/memory-graph-force-sim.test.ts`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-force-sim.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { tickOnce, seedCircle, shouldStop } from "@/components/console/graph/memory-graph/useForceSim";
import { FORCE_PARAMS } from "@/components/console/graph/memory-graph/constants";
import type { GraphNode, GraphEdge, Position } from "@/components/console/graph/memory-graph/types";

function makeGNode(id: string, overrides: Partial<GraphNode> = {}): GraphNode {
  return {
    id,
    role: "fact",
    label: id,
    conf: 0.8,
    reuse: 0,
    lastUsed: null,
    pinned: false,
    source: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    raw: {} as any,
    ...overrides,
  };
}

describe("seedCircle", () => {
  it("places N nodes evenly around a circle centered on (W/2, H/2)", () => {
    const nodes = [makeGNode("a"), makeGNode("b"), makeGNode("c"), makeGNode("d")];
    const positions = seedCircle(nodes, 400, 300);
    expect(positions.size).toBe(4);
    for (const p of positions.values()) {
      expect(p.vx).toBe(0);
      expect(p.vy).toBe(0);
      expect(p.fx).toBeNull();
      expect(p.fy).toBeNull();
      // Within bounds
      expect(p.x).toBeGreaterThanOrEqual(0);
      expect(p.x).toBeLessThanOrEqual(400);
      expect(p.y).toBeGreaterThanOrEqual(0);
      expect(p.y).toBeLessThanOrEqual(300);
    }
  });
});

describe("tickOnce", () => {
  it("advances alpha by the decay factor", () => {
    const positions = new Map<string, Position>();
    positions.set("a", { x: 100, y: 100, vx: 0, vy: 0, fx: null, fy: null });
    positions.set("b", { x: 200, y: 100, vx: 0, vy: 0, fx: null, fy: null });
    const nodes = [makeGNode("a"), makeGNode("b")];
    const edges: GraphEdge[] = [{ a: "a", b: "b", rel: "related", w: 1 }];

    const next = tickOnce({
      positions, nodes, edges, width: 400, height: 300,
      alpha: 1, params: FORCE_PARAMS,
    });
    expect(next.alpha).toBeCloseTo(FORCE_PARAMS.alphaDecay, 5);
  });

  it("fixes position when fx/fy are set (integrator skips them)", () => {
    const positions = new Map<string, Position>();
    positions.set("a", { x: 100, y: 100, vx: 0, vy: 0, fx: 300, fy: 150 });
    positions.set("b", { x: 200, y: 100, vx: 0, vy: 0, fx: null, fy: null });
    const nodes = [makeGNode("a"), makeGNode("b")];
    const edges: GraphEdge[] = [{ a: "a", b: "b", rel: "related", w: 1 }];

    tickOnce({
      positions, nodes, edges, width: 400, height: 300,
      alpha: 1, params: FORCE_PARAMS,
    });
    const a = positions.get("a")!;
    expect(a.x).toBe(300);
    expect(a.y).toBe(150);
    expect(a.vx).toBe(0);
    expect(a.vy).toBe(0);
  });

  it("keeps positions clamped inside viewport with 24px pad", () => {
    const positions = new Map<string, Position>();
    positions.set("a", { x: 5, y: 5, vx: -100, vy: -100, fx: null, fy: null });
    const nodes = [makeGNode("a")];

    tickOnce({
      positions, nodes, edges: [], width: 400, height: 300,
      alpha: 1, params: FORCE_PARAMS,
    });
    const p = positions.get("a")!;
    expect(p.x).toBeGreaterThanOrEqual(24);
    expect(p.y).toBeGreaterThanOrEqual(24);
  });
});

describe("shouldStop", () => {
  it("is true when alpha < alphaMin", () => {
    expect(shouldStop(0.0005, FORCE_PARAMS)).toBe(true);
    expect(shouldStop(FORCE_PARAMS.alphaMin, FORCE_PARAMS)).toBe(false);
    expect(shouldStop(1, FORCE_PARAMS)).toBe(false);
  });
});
```

### - [ ] Step 2: Run test to verify it fails

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-force-sim.test.ts
```
Expected: FAIL — module not found.

### - [ ] Step 3: Write the hook

Create `apps/web/components/console/graph/memory-graph/useForceSim.ts`:

```ts
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
  const positionsRef = useRef<Map<string, Position>>(new Map());
  const alphaRef = useRef<number>(params.alphaInit);
  const rafRef = useRef<number | null>(null);
  const sigRef = useRef<string>("");
  const [, forceRender] = useState(0);

  // Eager seed during render when structural signature changes (nodes/edges count or viewport size).
  // Running synchronously in the render path ensures the first paint of GraphCanvas has positions.
  const sig = `${opts.nodes.length}:${opts.edges.length}:${opts.width}:${opts.height}`;
  if (sigRef.current !== sig) {
    positionsRef.current = seedCircle(opts.nodes, opts.width, opts.height);
    alphaRef.current = params.alphaInit;
    sigRef.current = sig;
  }

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
```

### - [ ] Step 4: Run test to verify it passes

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-force-sim.test.ts
```
Expected: PASS — all unit cases green (tests target pure functions, not the hook).

### - [ ] Step 5: Commit

```bash
git add apps/web/components/console/graph/memory-graph/useForceSim.ts \
        apps/web/tests/unit/memory-graph-force-sim.test.ts
git commit -m "$(cat <<'EOF'
feat(web): implement Verlet force simulation hook for memory-graph

Pure tickOnce + seedCircle + shouldStop helpers (unit-tested), plus
useForceSim React hook wrapping a RAF loop with drag-fix (fx/fy),
reheat, and rearrange. Per UPGRADE_GUIDE.md §3.3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Register `memory_graph` window type

**Files:**
- Modify: `apps/web/components/notebook/WindowManager.tsx` (lines 21, 61-69)
- Modify: `apps/web/tests/unit/window-manager-persistence.test.tsx` (if any hard-coded WindowType exhaustiveness check exists — verify first)

### - [ ] Step 1: Inspect existing tests for WindowType coverage

```bash
grep -n "memory_graph\|WindowType" apps/web/tests/unit/window-manager-persistence.test.tsx apps/web/tests/unit/window-persistence.test.ts
```
Note any assertions on the set of types.

### - [ ] Step 2: Update `WindowType` union

Modify `apps/web/components/notebook/WindowManager.tsx` line 21:

```ts
export type WindowType = "note" | "ai_panel" | "file" | "memory" | "memory_graph" | "study" | "digest" | "search";
```

### - [ ] Step 3: Add default size

Modify the `DEFAULT_SIZES` object (same file, ~line 61):

```ts
const DEFAULT_SIZES: Record<WindowType, { width: number; height: number }> = {
  note: { width: 780, height: 600 },
  ai_panel: { width: 480, height: 620 },
  file: { width: 700, height: 500 },
  memory: { width: 500, height: 600 },
  memory_graph: { width: 1100, height: 720 },
  study: { width: 600, height: 500 },
  digest: { width: 520, height: 620 },
  search: { width: 680, height: 720 },
};
```

### - [ ] Step 4: Run existing window-manager tests

```bash
pnpm --filter web test:unit -- tests/unit/window-manager-persistence.test.tsx tests/unit/window-persistence.test.ts
```
Expected: PASS. If any test fails because of missing `memory_graph` in a fixture or exhaustive check, add `memory_graph` to that fixture to make the test green.

### - [ ] Step 5: Typecheck

```bash
pnpm --filter web tsc --noEmit
```
Expected: 0 errors.

### - [ ] Step 6: Commit

```bash
git add apps/web/components/notebook/WindowManager.tsx
git commit -m "$(cat <<'EOF'
chore(web): register memory_graph window type

Adds memory_graph to WindowType union and DEFAULT_SIZES (1100x720).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: i18n keys

**Files:**
- Modify: `apps/web/messages/en/console-notebooks.json`
- Modify: `apps/web/messages/zh/console-notebooks.json`

### - [ ] Step 1: Add English keys

Add the following entries to `apps/web/messages/en/console-notebooks.json` (flat keys — insert alphabetically near existing `memory.*` entries, and add `sidebar.openMemoryGraph` near other `sidebar.*`):

```json
"sidebar.openMemoryGraph": "Open Memory Graph",
"sidebar.openMemoryGraphShort": "Memory Graph",
"memoryGraph.title": "Memory Graph",
"memoryGraph.searchPlaceholder": "Search nodes…",
"memoryGraph.confSlider.label": "Min confidence",
"memoryGraph.rearrange": "Rearrange",
"memoryGraph.fit": "Fit",
"memoryGraph.view.graph": "Graph",
"memoryGraph.view.list": "List",
"memoryGraph.legend.title": "Legend",
"memoryGraph.roles.fact": "Fact",
"memoryGraph.roles.structure": "Structure",
"memoryGraph.roles.subject": "Subject",
"memoryGraph.roles.concept": "Concept",
"memoryGraph.roles.summary": "Summary",
"memoryGraph.drawer.summary": "Summary",
"memoryGraph.drawer.neighbors": "Neighbors",
"memoryGraph.drawer.neighborsCount": "{count, plural, =0 {No neighbors} one {1 neighbor} other {# neighbors}}",
"memoryGraph.drawer.lifecycle": "Lifecycle",
"memoryGraph.drawer.lifecycle.observe": "Observe",
"memoryGraph.drawer.lifecycle.consolidate": "Consolidate",
"memoryGraph.drawer.lifecycle.reuse": "Reuse",
"memoryGraph.drawer.lifecycle.reinforce": "Reinforce",
"memoryGraph.drawer.meta.source": "Source",
"memoryGraph.drawer.meta.reuse": "Reuse",
"memoryGraph.drawer.meta.lastUsed": "Last used",
"memoryGraph.drawer.pinned": "Pinned",
"memoryGraph.empty.title": "No memory yet",
"memoryGraph.empty.body": "As you chat and take notes, your memory graph will fill in here.",
"memoryGraph.loading": "Loading graph…",
"memoryGraph.list.columns.label": "Node",
"memoryGraph.list.columns.role": "Role",
"memoryGraph.list.columns.conf": "Conf",
"memoryGraph.list.columns.reuse": "Reuse",
"memoryGraph.list.columns.lastUsed": "Last used",
```

### - [ ] Step 2: Add Chinese keys

Add to `apps/web/messages/zh/console-notebooks.json` — same keys, translated:

```json
"sidebar.openMemoryGraph": "打开记忆图谱",
"sidebar.openMemoryGraphShort": "记忆图谱",
"memoryGraph.title": "记忆图谱",
"memoryGraph.searchPlaceholder": "搜索节点…",
"memoryGraph.confSlider.label": "最低置信度",
"memoryGraph.rearrange": "重排",
"memoryGraph.fit": "适配",
"memoryGraph.view.graph": "图谱",
"memoryGraph.view.list": "列表",
"memoryGraph.legend.title": "图例",
"memoryGraph.roles.fact": "事实",
"memoryGraph.roles.structure": "结构",
"memoryGraph.roles.subject": "主题",
"memoryGraph.roles.concept": "概念",
"memoryGraph.roles.summary": "摘要",
"memoryGraph.drawer.summary": "摘要",
"memoryGraph.drawer.neighbors": "邻居",
"memoryGraph.drawer.neighborsCount": "{count, plural, =0 {无邻居} other {# 个邻居}}",
"memoryGraph.drawer.lifecycle": "生命周期",
"memoryGraph.drawer.lifecycle.observe": "观察",
"memoryGraph.drawer.lifecycle.consolidate": "巩固",
"memoryGraph.drawer.lifecycle.reuse": "复用",
"memoryGraph.drawer.lifecycle.reinforce": "强化",
"memoryGraph.drawer.meta.source": "来源",
"memoryGraph.drawer.meta.reuse": "复用",
"memoryGraph.drawer.meta.lastUsed": "最近",
"memoryGraph.drawer.pinned": "固定",
"memoryGraph.empty.title": "还没有记忆",
"memoryGraph.empty.body": "随着你继续对话和记录笔记，记忆图谱会在这里生长起来。",
"memoryGraph.loading": "正在加载图谱…",
"memoryGraph.list.columns.label": "节点",
"memoryGraph.list.columns.role": "角色",
"memoryGraph.list.columns.conf": "置信度",
"memoryGraph.list.columns.reuse": "复用",
"memoryGraph.list.columns.lastUsed": "最近",
```

### - [ ] Step 3: Validate JSON parses

```bash
node -e "JSON.parse(require('fs').readFileSync('apps/web/messages/en/console-notebooks.json', 'utf8'))"
node -e "JSON.parse(require('fs').readFileSync('apps/web/messages/zh/console-notebooks.json', 'utf8'))"
```
Expected: no output (means valid JSON).

### - [ ] Step 4: Commit

```bash
git add apps/web/messages/en/console-notebooks.json \
        apps/web/messages/zh/console-notebooks.json
git commit -m "$(cat <<'EOF'
chore(web): add i18n keys for memory-graph window

English + Chinese translations for window title, toolbar, legend,
drawer sections, list columns, and sidebar open-trigger label.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: LegendAndZoom sub-component

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/LegendAndZoom.tsx`
- Test: `apps/web/tests/unit/memory-graph-legend.test.tsx`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-legend.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NextIntlClientProvider } from "next-intl";
import en from "@/messages/en/console-notebooks.json";
import { LegendAndZoom } from "@/components/console/graph/memory-graph/LegendAndZoom";

function wrap(ui: React.ReactNode) {
  return (
    <NextIntlClientProvider locale="en" messages={{ "console-notebooks": en }}>
      {ui}
    </NextIntlClientProvider>
  );
}

describe("LegendAndZoom", () => {
  it("renders 5 legend dots, one per role", () => {
    render(wrap(<LegendAndZoom zoom={1} onZoomIn={() => {}} onZoomOut={() => {}} onFit={() => {}} />));
    expect(screen.getByText("Fact")).toBeInTheDocument();
    expect(screen.getByText("Structure")).toBeInTheDocument();
    expect(screen.getByText("Subject")).toBeInTheDocument();
    expect(screen.getByText("Concept")).toBeInTheDocument();
    expect(screen.getByText("Summary")).toBeInTheDocument();
  });

  it("shows zoom % formatted to integer", () => {
    render(wrap(<LegendAndZoom zoom={1.23} onZoomIn={() => {}} onZoomOut={() => {}} onFit={() => {}} />));
    expect(screen.getByTestId("mg-zoom-indicator")).toHaveTextContent("123%");
  });

  it("calls handlers on +/−/fit buttons", () => {
    const onZoomIn = vi.fn();
    const onZoomOut = vi.fn();
    const onFit = vi.fn();
    render(wrap(<LegendAndZoom zoom={1} onZoomIn={onZoomIn} onZoomOut={onZoomOut} onFit={onFit} />));
    fireEvent.click(screen.getByTestId("mg-zoom-in"));
    fireEvent.click(screen.getByTestId("mg-zoom-out"));
    fireEvent.click(screen.getByTestId("mg-zoom-fit"));
    expect(onZoomIn).toHaveBeenCalledTimes(1);
    expect(onZoomOut).toHaveBeenCalledTimes(1);
    expect(onFit).toHaveBeenCalledTimes(1);
  });
});
```

### - [ ] Step 2: Run test to verify it fails

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-legend.test.tsx
```
Expected: FAIL — module not found.

### - [ ] Step 3: Implement the component

Create `apps/web/components/console/graph/memory-graph/LegendAndZoom.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import { Plus, Minus, Maximize2 } from "lucide-react";
import { ROLE_STYLE } from "./constants";
import type { Role } from "./types";

interface Props {
  zoom: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
}

const ORDERED_ROLES: Role[] = ["fact", "structure", "subject", "concept", "summary"];

export function LegendAndZoom({ zoom, onZoomIn, onZoomOut, onFit }: Props) {
  const t = useTranslations("console-notebooks");
  return (
    <>
      <div
        className="mg-legend"
        style={{
          position: "absolute", top: 12, left: 12,
          background: "rgba(255,255,255,0.88)",
          backdropFilter: "blur(12px)",
          padding: "10px 12px", borderRadius: 10,
          border: "1px solid rgba(15,42,45,0.1)",
          fontSize: 12, lineHeight: 1.5, zIndex: 2,
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 6 }}>
          {t("memoryGraph.legend.title")}
        </div>
        {ORDERED_ROLES.map((r) => (
          <div key={r} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span
              aria-hidden="true"
              style={{
                width: 10, height: 10, borderRadius: "50%",
                background: ROLE_STYLE[r].dot, display: "inline-block",
              }}
            />
            {t(`memoryGraph.roles.${r}`)}
          </div>
        ))}
      </div>
      <div
        className="mg-zoom"
        style={{
          position: "absolute", bottom: 12, left: 12,
          background: "rgba(255,255,255,0.88)",
          backdropFilter: "blur(12px)",
          padding: 6, borderRadius: 10,
          border: "1px solid rgba(15,42,45,0.1)",
          display: "flex", alignItems: "center", gap: 4, zIndex: 2,
        }}
      >
        <button type="button" onClick={onZoomOut} data-testid="mg-zoom-out"
          aria-label="Zoom out" style={{ padding: 4 }}>
          <Minus size={14} />
        </button>
        <span data-testid="mg-zoom-indicator" style={{ minWidth: 42, textAlign: "center", fontSize: 12 }}>
          {Math.round(zoom * 100)}%
        </span>
        <button type="button" onClick={onZoomIn} data-testid="mg-zoom-in"
          aria-label="Zoom in" style={{ padding: 4 }}>
          <Plus size={14} />
        </button>
        <button type="button" onClick={onFit} data-testid="mg-zoom-fit"
          aria-label="Fit" style={{ padding: 4 }}>
          <Maximize2 size={14} />
        </button>
      </div>
    </>
  );
}
```

### - [ ] Step 4: Run test to verify it passes

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-legend.test.tsx
```
Expected: PASS — 3 tests.

### - [ ] Step 5: Commit

```bash
git add apps/web/components/console/graph/memory-graph/LegendAndZoom.tsx \
        apps/web/tests/unit/memory-graph-legend.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): add LegendAndZoom overlay for memory-graph

5-role legend (top-left) and zoom indicator + controls (bottom-left)
with glass-morphism surface.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Toolbar sub-component

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/Toolbar.tsx`
- Test: `apps/web/tests/unit/memory-graph-toolbar.test.tsx`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-toolbar.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NextIntlClientProvider } from "next-intl";
import en from "@/messages/en/console-notebooks.json";
import { Toolbar } from "@/components/console/graph/memory-graph/Toolbar";
import type { Role } from "@/components/console/graph/memory-graph/types";

const ALL_ROLES: Role[] = ["fact", "structure", "subject", "concept", "summary"];

function wrap(ui: React.ReactNode) {
  return (
    <NextIntlClientProvider locale="en" messages={{ "console-notebooks": en }}>
      {ui}
    </NextIntlClientProvider>
  );
}

function defaults() {
  return {
    search: "",
    confMin: 0.6,
    filters: Object.fromEntries(ALL_ROLES.map((r) => [r, true])) as Record<Role, boolean>,
    view: "graph" as "graph" | "list",
    counts: Object.fromEntries(ALL_ROLES.map((r) => [r, 3])) as Record<Role, number>,
    onSearch: vi.fn(),
    onConfMin: vi.fn(),
    onToggleFilter: vi.fn(),
    onRearrange: vi.fn(),
    onFit: vi.fn(),
    onViewChange: vi.fn(),
  };
}

describe("Toolbar", () => {
  it("fires onSearch as user types", () => {
    const props = defaults();
    render(wrap(<Toolbar {...props} />));
    const input = screen.getByTestId("mg-search-input");
    fireEvent.change(input, { target: { value: "grad" } });
    expect(props.onSearch).toHaveBeenCalledWith("grad");
  });

  it("fires onConfMin when slider moves", () => {
    const props = defaults();
    render(wrap(<Toolbar {...props} />));
    const slider = screen.getByTestId("mg-conf-slider");
    fireEvent.change(slider, { target: { value: "0.8" } });
    expect(props.onConfMin).toHaveBeenCalledWith(0.8);
  });

  it("renders one chip per role with count", () => {
    const props = defaults();
    render(wrap(<Toolbar {...props} />));
    for (const r of ALL_ROLES) {
      expect(screen.getByTestId(`mg-chip-${r}`)).toBeInTheDocument();
    }
  });

  it("fires onToggleFilter with role on chip click", () => {
    const props = defaults();
    render(wrap(<Toolbar {...props} />));
    fireEvent.click(screen.getByTestId("mg-chip-fact"));
    expect(props.onToggleFilter).toHaveBeenCalledWith("fact");
  });

  it("fires onRearrange / onFit / onViewChange on buttons", () => {
    const props = defaults();
    render(wrap(<Toolbar {...props} />));
    fireEvent.click(screen.getByTestId("mg-btn-rearrange"));
    fireEvent.click(screen.getByTestId("mg-btn-fit"));
    fireEvent.click(screen.getByTestId("mg-btn-view-list"));
    expect(props.onRearrange).toHaveBeenCalled();
    expect(props.onFit).toHaveBeenCalled();
    expect(props.onViewChange).toHaveBeenCalledWith("list");
  });
});
```

### - [ ] Step 2: Run test to verify it fails

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-toolbar.test.tsx
```
Expected: FAIL — module not found.

### - [ ] Step 3: Implement

Create `apps/web/components/console/graph/memory-graph/Toolbar.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import { RotateCcw, Maximize2 } from "lucide-react";
import { ROLE_STYLE } from "./constants";
import type { Role } from "./types";

const ALL_ROLES: Role[] = ["fact", "structure", "subject", "concept", "summary"];

interface Props {
  search: string;
  confMin: number;
  filters: Record<Role, boolean>;
  view: "graph" | "list";
  counts: Record<Role, number>;
  onSearch: (value: string) => void;
  onConfMin: (value: number) => void;
  onToggleFilter: (role: Role) => void;
  onRearrange: () => void;
  onFit: () => void;
  onViewChange: (view: "graph" | "list") => void;
}

export function Toolbar(p: Props) {
  const t = useTranslations("console-notebooks");
  return (
    <div
      className="mg-toolbar"
      style={{
        display: "flex", alignItems: "center", gap: 10, padding: "8px 12px",
        borderBottom: "1px solid var(--border, rgba(15,42,45,0.08))",
        flexWrap: "wrap",
      }}
    >
      <input
        data-testid="mg-search-input"
        type="search"
        placeholder={t("memoryGraph.searchPlaceholder")}
        value={p.search}
        onChange={(e) => p.onSearch(e.target.value)}
        style={{
          flex: "0 1 220px", padding: "6px 10px", borderRadius: 8,
          border: "1px solid var(--border, rgba(15,42,45,0.1))",
          background: "var(--bg-raised, #fff)", fontSize: 13,
        }}
      />
      <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
        <span>{t("memoryGraph.confSlider.label")}</span>
        <input
          data-testid="mg-conf-slider"
          type="range" min={0.6} max={0.99} step={0.01}
          value={p.confMin}
          onChange={(e) => p.onConfMin(Number(e.target.value))}
          style={{ width: 120 }}
        />
        <span style={{ minWidth: 30, fontFamily: "monospace" }}>{p.confMin.toFixed(2)}</span>
      </label>
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
      <div style={{ flex: 1 }} />
      <button data-testid="mg-btn-rearrange" type="button" onClick={p.onRearrange}
        style={{ padding: "4px 8px", fontSize: 12 }}>
        <RotateCcw size={12} style={{ marginRight: 4, verticalAlign: "middle" }} />
        {t("memoryGraph.rearrange")}
      </button>
      <button data-testid="mg-btn-fit" type="button" onClick={p.onFit}
        style={{ padding: "4px 8px", fontSize: 12 }}>
        <Maximize2 size={12} style={{ marginRight: 4, verticalAlign: "middle" }} />
        {t("memoryGraph.fit")}
      </button>
      <div role="tablist" style={{ display: "flex", gap: 2, marginLeft: 6 }}>
        <button
          data-testid="mg-btn-view-graph"
          type="button" role="tab" aria-selected={p.view === "graph"}
          onClick={() => p.onViewChange("graph")}
          style={{ padding: "4px 10px", fontSize: 12, fontWeight: p.view === "graph" ? 600 : 400 }}
        >
          {t("memoryGraph.view.graph")}
        </button>
        <button
          data-testid="mg-btn-view-list"
          type="button" role="tab" aria-selected={p.view === "list"}
          onClick={() => p.onViewChange("list")}
          style={{ padding: "4px 10px", fontSize: 12, fontWeight: p.view === "list" ? 600 : 400 }}
        >
          {t("memoryGraph.view.list")}
        </button>
      </div>
    </div>
  );
}
```

### - [ ] Step 4: Run test to verify it passes

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-toolbar.test.tsx
```
Expected: PASS — 5 tests.

### - [ ] Step 5: Commit

```bash
git add apps/web/components/console/graph/memory-graph/Toolbar.tsx \
        apps/web/tests/unit/memory-graph-toolbar.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): add memory-graph Toolbar (search + conf + chips + view)

Controlled-component toolbar with search, confidence slider (0.6-0.99),
5 role filter chips with counts, rearrange/fit buttons, graph/list
view tabs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: NodeDetailDrawer sub-component

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/NodeDetailDrawer.tsx`
- Test: `apps/web/tests/unit/memory-graph-drawer.test.tsx`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-drawer.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NextIntlClientProvider } from "next-intl";
import en from "@/messages/en/console-notebooks.json";
import { NodeDetailDrawer } from "@/components/console/graph/memory-graph/NodeDetailDrawer";
import type { GraphNode } from "@/components/console/graph/memory-graph/types";

function makeGraphNode(overrides: Partial<GraphNode> = {}): GraphNode {
  return {
    id: "n1",
    role: "fact",
    label: "Gradient Descent",
    conf: 0.97,
    reuse: 28,
    lastUsed: "30m",
    pinned: true,
    source: "§3.1",
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    raw: { content: "A lot of longer summary text describing the node." } as any,
    ...overrides,
  };
}

function wrap(ui: React.ReactNode) {
  return (
    <NextIntlClientProvider locale="en" messages={{ "console-notebooks": en }}>
      {ui}
    </NextIntlClientProvider>
  );
}

describe("NodeDetailDrawer", () => {
  it("renders role pill + conf + pinned marker", () => {
    const node = makeGraphNode();
    render(wrap(<NodeDetailDrawer node={node} neighbors={[]} onSelectNeighbor={() => {}} onClose={() => {}} />));
    expect(screen.getByText("Fact")).toBeInTheDocument();
    expect(screen.getByText("Gradient Descent")).toBeInTheDocument();
    expect(screen.getByText("0.97")).toBeInTheDocument();
    expect(screen.getByText("Pinned")).toBeInTheDocument();
  });

  it("renders 3 meta columns (source / reuse / last used)", () => {
    const node = makeGraphNode();
    render(wrap(<NodeDetailDrawer node={node} neighbors={[]} onSelectNeighbor={() => {}} onClose={() => {}} />));
    expect(screen.getByText("§3.1")).toBeInTheDocument();
    expect(screen.getByText("28")).toBeInTheDocument();
    expect(screen.getByText("30m")).toBeInTheDocument();
  });

  it("renders summary from raw.content", () => {
    const node = makeGraphNode();
    render(wrap(<NodeDetailDrawer node={node} neighbors={[]} onSelectNeighbor={() => {}} onClose={() => {}} />));
    expect(screen.getByText(/A lot of longer summary text/)).toBeInTheDocument();
  });

  it("renders neighbors list and fires onSelectNeighbor on click", () => {
    const neighbors = [
      { id: "n2", rel: "evidence", node: makeGraphNode({ id: "n2", label: "Backprop", role: "subject" }) },
    ];
    const onSelect = vi.fn();
    render(wrap(
      <NodeDetailDrawer
        node={makeGraphNode()}
        neighbors={neighbors}
        onSelectNeighbor={onSelect}
        onClose={() => {}}
      />,
    ));
    fireEvent.click(screen.getByTestId("mg-drawer-neighbor-n2"));
    expect(onSelect).toHaveBeenCalledWith("n2");
  });

  it("renders 4 lifecycle stages, 3 filled", () => {
    render(wrap(<NodeDetailDrawer node={makeGraphNode()} neighbors={[]} onSelectNeighbor={() => {}} onClose={() => {}} />));
    expect(screen.getAllByTestId(/^mg-lifecycle-stage-/).length).toBe(4);
    expect(screen.getAllByTestId(/^mg-lifecycle-stage-.*-done$/).length).toBe(3);
  });
});
```

### - [ ] Step 2: Run test to verify it fails

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-drawer.test.tsx
```
Expected: FAIL — module not found.

### - [ ] Step 3: Implement

Create `apps/web/components/console/graph/memory-graph/NodeDetailDrawer.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import { X, Pin } from "lucide-react";
import { ROLE_STYLE } from "./constants";
import type { GraphNode } from "./types";

export interface DrawerNeighbor {
  id: string;
  rel: string;
  node: GraphNode;
}

interface Props {
  node: GraphNode;
  neighbors: DrawerNeighbor[];
  onSelectNeighbor: (id: string) => void;
  onClose: () => void;
}

const LIFECYCLE_STAGES: ReadonlyArray<{ id: string; done: boolean }> = [
  { id: "observe",     done: true  },
  { id: "consolidate", done: true  },
  { id: "reuse",       done: true  },
  { id: "reinforce",   done: false },
];

export function NodeDetailDrawer({ node, neighbors, onSelectNeighbor, onClose }: Props) {
  const t = useTranslations("console-notebooks");
  const style = ROLE_STYLE[node.role];
  const summary = node.raw?.content ?? "";

  return (
    <aside
      role="complementary"
      aria-label="Node detail"
      className="mg-drawer"
      style={{
        width: 300, height: "100%", flexShrink: 0,
        background: "var(--bg-surface, #fff)",
        borderLeft: "1px solid var(--border, rgba(15,42,45,0.08))",
        padding: 16, overflowY: "auto", fontSize: 13, lineHeight: 1.5,
        display: "flex", flexDirection: "column", gap: 12,
      }}
    >
      <header style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          style={{
            padding: "2px 8px", borderRadius: 999, fontSize: 11, fontWeight: 600,
            background: style.fill, color: style.text, border: `1px solid ${style.stroke}`,
          }}
        >
          {t(`memoryGraph.roles.${node.role}`)}
        </span>
        {node.pinned && (
          <span aria-label={t("memoryGraph.drawer.pinned")} title={t("memoryGraph.drawer.pinned")}
            style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, color: "#f97316" }}>
            <Pin size={12} />
            {t("memoryGraph.drawer.pinned")}
          </span>
        )}
        <div style={{ flex: 1 }} />
        <span style={{ fontFamily: "monospace", fontSize: 12, color: "var(--text-secondary)" }}>
          {node.conf.toFixed(2)}
        </span>
        <button aria-label="Close" onClick={onClose} type="button"
          style={{ padding: 2, background: "transparent", border: "none", cursor: "pointer" }}>
          <X size={14} />
        </button>
      </header>

      <h2 style={{ fontSize: 14, fontWeight: 700, margin: 0, color: "var(--text-primary)" }}>{node.label}</h2>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6 }}>
        <MetaBlock label={t("memoryGraph.drawer.meta.source")} value={node.source ?? "—"} />
        <MetaBlock label={t("memoryGraph.drawer.meta.reuse")} value={String(node.reuse)} />
        <MetaBlock label={t("memoryGraph.drawer.meta.lastUsed")} value={node.lastUsed ?? "—"} />
      </div>

      <div aria-label="Confidence bar" style={{ height: 4, borderRadius: 2, background: "rgba(15,42,45,0.08)" }}>
        <div style={{ width: `${Math.round(node.conf * 100)}%`, height: "100%", borderRadius: 2, background: style.stroke }} />
      </div>

      <section>
        <SectionLabel>{t("memoryGraph.drawer.summary")}</SectionLabel>
        <p style={{ margin: 0, color: "var(--text-primary)" }}>{summary}</p>
      </section>

      <section>
        <SectionLabel>
          {t("memoryGraph.drawer.neighbors")} {neighbors.length}
        </SectionLabel>
        {neighbors.length === 0 && (
          <p style={{ margin: 0, color: "var(--text-secondary)" }}>—</p>
        )}
        {neighbors.map((n) => {
          const nStyle = ROLE_STYLE[n.node.role];
          return (
            <button
              key={n.id}
              data-testid={`mg-drawer-neighbor-${n.id}`}
              type="button"
              onClick={() => onSelectNeighbor(n.id)}
              style={{
                display: "flex", width: "100%", alignItems: "center", gap: 6,
                padding: "4px 0", background: "transparent", border: "none",
                cursor: "pointer", textAlign: "left", fontSize: 12,
              }}
            >
              <span style={{
                fontFamily: "monospace", fontSize: 10, color: "var(--text-secondary)",
                border: "1px solid var(--border, rgba(15,42,45,0.12))",
                padding: "0 4px", borderRadius: 4,
              }}>
                {n.rel}
              </span>
              <span aria-hidden style={{
                width: 8, height: 8, borderRadius: "50%", background: nStyle.dot,
              }} />
              <span>{n.node.label}</span>
            </button>
          );
        })}
      </section>

      <section>
        <SectionLabel>{t("memoryGraph.drawer.lifecycle")}</SectionLabel>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {LIFECYCLE_STAGES.map((s) => (
            <div
              key={s.id}
              data-testid={`mg-lifecycle-stage-${s.id}${s.done ? "-done" : ""}`}
              style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4, flex: 1 }}
            >
              <span style={{
                width: 10, height: 10, borderRadius: "50%",
                background: s.done ? "#0d9488" : "transparent",
                border: `1.5px solid #0d9488`,
              }} />
              <span style={{ fontSize: 10, color: "var(--text-secondary)" }}>
                {t(`memoryGraph.drawer.lifecycle.${s.id}`)}
              </span>
            </div>
          ))}
        </div>
      </section>
    </aside>
  );
}

function MetaBlock({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      padding: 8, borderRadius: 8, background: "rgba(15,42,45,0.04)",
      display: "flex", flexDirection: "column", gap: 2,
    }}>
      <span style={{ fontSize: 10, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </span>
      <span style={{ fontSize: 13, fontWeight: 500, color: "var(--text-primary)" }}>{value}</span>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 10, fontWeight: 600, letterSpacing: 0.6,
      textTransform: "uppercase", color: "var(--text-secondary)", marginBottom: 6,
    }}>
      {children}
    </div>
  );
}
```

### - [ ] Step 4: Run test to verify it passes

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-drawer.test.tsx
```
Expected: PASS — 5 tests.

### - [ ] Step 5: Commit

```bash
git add apps/web/components/console/graph/memory-graph/NodeDetailDrawer.tsx \
        apps/web/tests/unit/memory-graph-drawer.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): add NodeDetailDrawer for memory-graph

300px right-side drawer showing role pill, pinned marker, confidence,
3-column meta (source/reuse/last-used), summary, clickable neighbors,
and 4-stage lifecycle indicator (3/4 static per spec §4.1).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: ListView sub-component

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/ListView.tsx`
- Test: `apps/web/tests/unit/memory-graph-list.test.tsx`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-list.test.tsx`:

```tsx
import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NextIntlClientProvider } from "next-intl";
import en from "@/messages/en/console-notebooks.json";
import { ListView } from "@/components/console/graph/memory-graph/ListView";
import type { GraphNode } from "@/components/console/graph/memory-graph/types";

function makeNode(over: Partial<GraphNode>): GraphNode {
  return {
    id: "n",
    role: "fact",
    label: "Node",
    conf: 0.8,
    reuse: 0,
    lastUsed: null,
    pinned: false,
    source: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    raw: {} as any,
    ...over,
  };
}

function wrap(ui: React.ReactNode) {
  return (
    <NextIntlClientProvider locale="en" messages={{ "console-notebooks": en }}>
      {ui}
    </NextIntlClientProvider>
  );
}

describe("ListView", () => {
  it("renders one row per node", () => {
    const nodes = [
      makeNode({ id: "a", label: "Alpha" }),
      makeNode({ id: "b", label: "Beta" }),
    ];
    render(wrap(<ListView nodes={nodes} onSelect={() => {}} selectedId={null} />));
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
  });

  it("fires onSelect with node id on row click", () => {
    const onSelect = vi.fn();
    const nodes = [makeNode({ id: "x", label: "Xenon" })];
    render(wrap(<ListView nodes={nodes} onSelect={onSelect} selectedId={null} />));
    fireEvent.click(screen.getByTestId("mg-list-row-x"));
    expect(onSelect).toHaveBeenCalledWith("x");
  });

  it("highlights selectedId", () => {
    const nodes = [makeNode({ id: "y", label: "Ytterbium" })];
    render(wrap(<ListView nodes={nodes} onSelect={() => {}} selectedId="y" />));
    const row = screen.getByTestId("mg-list-row-y");
    expect(row).toHaveAttribute("aria-selected", "true");
  });

  it("sorts by conf descending when clicking conf header", () => {
    const nodes = [
      makeNode({ id: "a", label: "Lo", conf: 0.6 }),
      makeNode({ id: "b", label: "Hi", conf: 0.95 }),
    ];
    render(wrap(<ListView nodes={nodes} onSelect={() => {}} selectedId={null} />));
    // Initial order preserved (as-passed)
    const initialRows = screen.getAllByTestId(/^mg-list-row-/);
    expect(initialRows[0].textContent).toMatch(/Lo/);
    // Click conf header
    fireEvent.click(screen.getByTestId("mg-list-header-conf"));
    const sortedRows = screen.getAllByTestId(/^mg-list-row-/);
    expect(sortedRows[0].textContent).toMatch(/Hi/);
  });
});
```

### - [ ] Step 2: Run test to verify it fails

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-list.test.tsx
```
Expected: FAIL — module not found.

### - [ ] Step 3: Implement

Create `apps/web/components/console/graph/memory-graph/ListView.tsx`:

```tsx
"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { ROLE_STYLE } from "./constants";
import type { GraphNode } from "./types";

type SortKey = "label" | "role" | "conf" | "reuse" | "lastUsed";
type SortDir = "asc" | "desc";

interface Props {
  nodes: GraphNode[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function ListView({ nodes, selectedId, onSelect }: Props) {
  const t = useTranslations("console-notebooks");
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir } | null>(null);

  const sorted = useMemo(() => {
    if (!sort) return nodes;
    const arr = [...nodes];
    arr.sort((a, b) => {
      let av: string | number = "";
      let bv: string | number = "";
      switch (sort.key) {
        case "label": av = a.label; bv = b.label; break;
        case "role": av = a.role; bv = b.role; break;
        case "conf": av = a.conf; bv = b.conf; break;
        case "reuse": av = a.reuse; bv = b.reuse; break;
        case "lastUsed": av = a.lastUsed ?? ""; bv = b.lastUsed ?? ""; break;
      }
      if (av < bv) return sort.dir === "asc" ? -1 : 1;
      if (av > bv) return sort.dir === "asc" ? 1 : -1;
      return 0;
    });
    return arr;
  }, [nodes, sort]);

  const clickHeader = (key: SortKey) => {
    setSort((prev) => {
      if (!prev || prev.key !== key) return { key, dir: "desc" };
      return { key, dir: prev.dir === "desc" ? "asc" : "desc" };
    });
  };

  const headers: Array<{ key: SortKey; id: string }> = [
    { key: "label", id: "label" },
    { key: "role", id: "role" },
    { key: "conf", id: "conf" },
    { key: "reuse", id: "reuse" },
    { key: "lastUsed", id: "lastUsed" },
  ];

  return (
    <div style={{ height: "100%", overflow: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead style={{ position: "sticky", top: 0, background: "var(--bg-surface, #fff)", zIndex: 1 }}>
          <tr>
            {headers.map((h) => (
              <th
                key={h.key}
                data-testid={`mg-list-header-${h.id}`}
                onClick={() => clickHeader(h.key)}
                style={{
                  textAlign: "left", padding: "8px 10px",
                  borderBottom: "1px solid var(--border, rgba(15,42,45,0.08))",
                  fontWeight: 600, cursor: "pointer", userSelect: "none",
                }}
              >
                {t(`memoryGraph.list.columns.${h.id}`)}
                {sort?.key === h.key ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((n) => {
            const selected = n.id === selectedId;
            const style = ROLE_STYLE[n.role];
            return (
              <tr
                key={n.id}
                data-testid={`mg-list-row-${n.id}`}
                onClick={() => onSelect(n.id)}
                aria-selected={selected}
                style={{
                  cursor: "pointer",
                  background: selected ? "rgba(13,148,136,0.08)" : undefined,
                }}
              >
                <td style={{ padding: "6px 10px" }}>{n.label}</td>
                <td style={{ padding: "6px 10px" }}>
                  <span style={{
                    padding: "2px 6px", borderRadius: 4, fontSize: 11,
                    background: style.fill, color: style.text, border: `1px solid ${style.stroke}`,
                  }}>
                    {t(`memoryGraph.roles.${n.role}`)}
                  </span>
                </td>
                <td style={{ padding: "6px 10px", fontFamily: "monospace" }}>{n.conf.toFixed(2)}</td>
                <td style={{ padding: "6px 10px", fontFamily: "monospace" }}>{n.reuse}</td>
                <td style={{ padding: "6px 10px", color: "var(--text-secondary)" }}>{n.lastUsed ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
```

### - [ ] Step 4: Run test to verify it passes

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-list.test.tsx
```
Expected: PASS — 4 tests.

### - [ ] Step 5: Commit

```bash
git add apps/web/components/console/graph/memory-graph/ListView.tsx \
        apps/web/tests/unit/memory-graph-list.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): add ListView for memory-graph

Sortable table (label/role/conf/reuse/lastUsed) with selection
highlight, sticky header, role pills per row.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: GraphCanvas — SVG + viewport + drag/pan/zoom

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/GraphCanvas.tsx`
- Test: `apps/web/tests/unit/memory-graph-canvas.test.tsx`

Testing strategy: GraphCanvas is hard to exercise with full RAF in jsdom. The test covers pure-logic concerns (viewport transform, wheel delta math, pointer-event wiring via props) without asserting visual layout.

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-canvas.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GraphCanvas, clampZoom, nextZoom } from "@/components/console/graph/memory-graph/GraphCanvas";
import type { GraphNode, GraphEdge, Position } from "@/components/console/graph/memory-graph/types";
import { VIEWPORT_DEFAULTS } from "@/components/console/graph/memory-graph/constants";

describe("clampZoom / nextZoom", () => {
  it("clampZoom keeps values inside [kMin, kMax]", () => {
    expect(clampZoom(0.1, VIEWPORT_DEFAULTS)).toBe(VIEWPORT_DEFAULTS.kMin);
    expect(clampZoom(99,  VIEWPORT_DEFAULTS)).toBe(VIEWPORT_DEFAULTS.kMax);
    expect(clampZoom(1.2, VIEWPORT_DEFAULTS)).toBe(1.2);
  });
  it("nextZoom multiplies/divides by 1.2 for +/- actions", () => {
    expect(nextZoom(1, "in",  VIEWPORT_DEFAULTS)).toBeCloseTo(1.2);
    expect(nextZoom(1, "out", VIEWPORT_DEFAULTS)).toBeCloseTo(1 / 1.2);
  });
});

function makeNode(over: Partial<GraphNode> = {}): GraphNode {
  return {
    id: "n1", role: "fact", label: "Alpha",
    conf: 0.8, reuse: 0, lastUsed: null,
    pinned: false, source: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    raw: {} as any, ...over,
  };
}

function makePositions(ids: string[]): Map<string, Position> {
  const m = new Map<string, Position>();
  ids.forEach((id, i) => m.set(id, { x: 100 + i * 50, y: 100, vx: 0, vy: 0, fx: null, fy: null }));
  return m;
}

const ALL_FILTERS = { fact: true, structure: true, subject: true, concept: true, summary: true } as const;

describe("GraphCanvas render", () => {
  it("renders an SVG with one <g.mg-node> per node", () => {
    const nodes = [makeNode({ id: "a" }), makeNode({ id: "b" })];
    const edges: GraphEdge[] = [];
    render(
      <GraphCanvas
        nodes={nodes} edges={edges} positions={makePositions(["a", "b"])}
        width={400} height={300}
        viewport={{ k: 1, tx: 0, ty: 0 }}
        hoverId={null} selectedId={null} searchMatches={new Set()}
        filters={{ ...ALL_FILTERS }}
        onViewportChange={() => {}}
        onHover={() => {}}
        onSelect={() => {}}
        onDragStart={() => {}}
        onDrag={() => {}}
        onDragEnd={() => {}}
      />,
    );
    expect(screen.getAllByTestId(/^mg-node-/)).toHaveLength(2);
  });

  it("fires onHover with id on pointerenter over node", () => {
    const nodes = [makeNode({ id: "a" })];
    const onHover = vi.fn();
    render(
      <GraphCanvas
        nodes={nodes} edges={[]} positions={makePositions(["a"])}
        width={400} height={300}
        viewport={{ k: 1, tx: 0, ty: 0 }}
        hoverId={null} selectedId={null} searchMatches={new Set()}
        filters={{ ...ALL_FILTERS }}
        onViewportChange={() => {}}
        onHover={onHover}
        onSelect={() => {}}
        onDragStart={() => {}}
        onDrag={() => {}}
        onDragEnd={() => {}}
      />,
    );
    fireEvent.pointerEnter(screen.getByTestId("mg-node-a"));
    expect(onHover).toHaveBeenCalledWith("a");
  });

  it("fires onSelect on click and onHover(null) on pointerleave", () => {
    const nodes = [makeNode({ id: "a" })];
    const onSelect = vi.fn();
    const onHover = vi.fn();
    render(
      <GraphCanvas
        nodes={nodes} edges={[]} positions={makePositions(["a"])}
        width={400} height={300}
        viewport={{ k: 1, tx: 0, ty: 0 }}
        hoverId={null} selectedId={null} searchMatches={new Set()}
        filters={{ ...ALL_FILTERS }}
        onViewportChange={() => {}}
        onHover={onHover}
        onSelect={onSelect}
        onDragStart={() => {}}
        onDrag={() => {}}
        onDragEnd={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("mg-node-a"));
    fireEvent.pointerLeave(screen.getByTestId("mg-node-a"));
    expect(onSelect).toHaveBeenCalledWith("a");
    expect(onHover).toHaveBeenLastCalledWith(null);
  });
});
```

### - [ ] Step 2: Run test to verify it fails

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-canvas.test.tsx
```
Expected: FAIL — module not found.

### - [ ] Step 3: Implement the canvas

GraphCanvas is a **pure presentational SVG** — it does NOT own the simulation. Positions come in as a prop (computed by `useForceSim` one level up). This keeps a single sim instance shared by canvas (for rendering) and view (for `rearrange()/setFixed()`).

Create `apps/web/components/console/graph/memory-graph/GraphCanvas.tsx`:

```tsx
"use client";

import { useCallback, useMemo, useRef } from "react";
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
    // Anchor zoom at cursor: world point under cursor stays under cursor
    const tx = cx - ((cx - p.viewport.tx) * kNext) / p.viewport.k;
    const ty = cy - ((cy - p.viewport.ty) * kNext) / p.viewport.k;
    p.onViewportChange({ k: kNext, tx, ty });
  }, [p]);

  const handleBackgroundPointerDown: React.PointerEventHandler<SVGRectElement> = (e) => {
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    dragRef.current.panStart = {
      x: e.clientX, y: e.clientY, tx: p.viewport.tx, ty: p.viewport.ty,
    };
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
  // Compute 1-hop set for focus dimming
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
      style={{ display: "block", userSelect: "none", cursor: dragRef.current.panStart ? "grabbing" : "default" }}
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
```

### - [ ] Step 4: Run test to verify it passes

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-canvas.test.tsx
```
Expected: PASS — 5 tests.

### - [ ] Step 5: Typecheck

```bash
pnpm --filter web tsc --noEmit
```
Expected: 0 errors.

### - [ ] Step 6: Commit

```bash
git add apps/web/components/console/graph/memory-graph/GraphCanvas.tsx \
        apps/web/tests/unit/memory-graph-canvas.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): add GraphCanvas SVG renderer for memory-graph

Viewport transform + wheel-anchored zoom + background pan + per-node
pointer events (hover/click/drag). Uses useForceSim for positions,
applies role/edge palette, focus dimming, search dim, filter hide,
pinned halo with glow.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: MemoryGraphView — assemble sub-components

**Files:**
- Create: `apps/web/components/console/graph/memory-graph/MemoryGraphView.tsx`
- Create: `apps/web/components/console/graph/memory-graph/index.ts`
- Test: `apps/web/tests/unit/memory-graph-view.test.tsx`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-view.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NextIntlClientProvider } from "next-intl";
import en from "@/messages/en/console-notebooks.json";
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

function wrap(ui: React.ReactNode) {
  return (
    <NextIntlClientProvider locale="en" messages={{ "console-notebooks": en }}>
      {ui}
    </NextIntlClientProvider>
  );
}

describe("MemoryGraphView", () => {
  it("renders toolbar + canvas + legend, no drawer until a node is selected", () => {
    const nodes: GraphNode[] = [makeNode({ id: "a", label: "Alpha" })];
    const edges: GraphEdge[] = [];
    render(wrap(<MemoryGraphView nodes={nodes} edges={edges} />));
    expect(screen.getByTestId("mg-search-input")).toBeInTheDocument();
    expect(screen.getByTestId("mg-svg")).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Node detail" })).not.toBeInTheDocument();
  });

  it("opens drawer when a node is clicked", () => {
    const nodes: GraphNode[] = [makeNode({ id: "a", label: "Alpha" })];
    render(wrap(<MemoryGraphView nodes={nodes} edges={[]} />));
    fireEvent.click(screen.getByTestId("mg-node-a"));
    expect(screen.getByRole("complementary", { name: "Node detail" })).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
  });

  it("switches to ListView when List tab clicked", () => {
    const nodes: GraphNode[] = [makeNode({ id: "a", label: "Alpha" })];
    render(wrap(<MemoryGraphView nodes={nodes} edges={[]} />));
    fireEvent.click(screen.getByTestId("mg-btn-view-list"));
    expect(screen.getByTestId("mg-list-row-a")).toBeInTheDocument();
    expect(screen.queryByTestId("mg-svg")).not.toBeInTheDocument();
  });
});
```

### - [ ] Step 2: Run test to verify it fails

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-view.test.tsx
```
Expected: FAIL — module not found.

### - [ ] Step 3: Implement the view

Create `apps/web/components/console/graph/memory-graph/MemoryGraphView.tsx`:

```tsx
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Toolbar } from "./Toolbar";
import { GraphCanvas, clampZoom, nextZoom } from "./GraphCanvas";
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

  // Resize observer → canvas dimensions
  useEffect(() => {
    if (!containerRef.current) return;
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

  // Counts by role (pre-filter, post-conf, post-search): guide §7 chip shows count
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
  const sim = useForceSim({
    nodes: effectiveNodes, edges: effectiveEdges,
    width: box.w - (isNarrow ? 0 : (selectedId ? 300 : 0)),
    height: box.h - 52 - (isNarrow && selectedId ? Math.floor(box.h * 0.6) : 0),
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

  // Drag handlers bridge to the sim
  const handleDragStart = useCallback((id: string) => {
    // pointer capture is done in canvas; sim does not need a signal yet
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
        />
        <div style={{ position: "relative", flex: 1, minHeight: 0 }}>
          {view === "graph" ? (
            <>
              <GraphCanvas
                nodes={effectiveNodes} edges={effectiveEdges}
                positions={positions}
                width={box.w - (isNarrow ? 0 : (selectedNode ? 300 : 0))}
                height={box.h - 52 /* toolbar */ - (isNarrow && selectedNode ? Math.floor(box.h * 0.6) : 0)}
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
        />
      )}
    </div>
  );
}
```

### - [ ] Step 4: Create barrel export

Create `apps/web/components/console/graph/memory-graph/index.ts`:

```ts
export { MemoryGraphView } from "./MemoryGraphView";
export { adaptGraphData } from "./adapter";
export type { GraphNode, GraphEdge, Role } from "./types";
```

### - [ ] Step 5: Run test to verify it passes

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-view.test.tsx
```
Expected: PASS — 3 tests.

### - [ ] Step 6: Commit

```bash
git add apps/web/components/console/graph/memory-graph/MemoryGraphView.tsx \
        apps/web/components/console/graph/memory-graph/index.ts \
        apps/web/tests/unit/memory-graph-view.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): assemble MemoryGraphView from sub-components

Owns search/conf/filters/selection/viewport state. Applies confMin
as hard filter, role filters as opacity-only (stable layout), wires
drag/reheat to useForceSim, switches graph/list views, collapses
drawer under 960px to keep it usable in narrow windows.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: MemoryGraphWindow — window content wrapper

**Files:**
- Create: `apps/web/components/notebook/contents/MemoryGraphWindow.tsx`
- Test: `apps/web/tests/unit/memory-graph-window.test.tsx`

### - [ ] Step 1: Look up notebook → projectId resolution pattern

Read the existing memory page route to see how projectId is fetched from notebookId:

```bash
grep -n "project_id\|projectId" apps/web/app/\[locale\]/workspace/notebooks/\[notebookId\]/memory/page.tsx apps/web/components/notebook/contents/MemoryWindow.tsx 2>&1 | head -30
```

Based on patterns in this codebase, the window will call `apiGet<{ project_id: string }>('/api/v1/notebooks/${notebookId}')` to resolve.

### - [ ] Step 2: Write the failing test

Create `apps/web/tests/unit/memory-graph-window.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { NextIntlClientProvider } from "next-intl";
import en from "@/messages/en/console-notebooks.json";
import MemoryGraphWindow from "@/components/notebook/contents/MemoryGraphWindow";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));
vi.mock("@/lib/env", () => ({ getApiHttpBaseUrl: () => "http://localhost" }));

import { apiGet } from "@/lib/api";

function wrap(ui: React.ReactNode) {
  return (
    <NextIntlClientProvider locale="en" messages={{ "console-notebooks": en }}>
      {ui}
    </NextIntlClientProvider>
  );
}

beforeEach(() => {
  vi.mocked(apiGet).mockReset();
});

describe("MemoryGraphWindow", () => {
  it("renders loading state initially", () => {
    vi.mocked(apiGet).mockImplementation(() => new Promise(() => {})); // never resolves
    render(wrap(<MemoryGraphWindow notebookId="nb1" />));
    expect(screen.getByText(/Loading graph/i)).toBeInTheDocument();
  });

  it("resolves projectId from notebook endpoint and then loads graph", async () => {
    vi.mocked(apiGet).mockImplementation((url: string) => {
      if (url.startsWith("/api/v1/notebooks/")) {
        return Promise.resolve({ project_id: "p1" });
      }
      if (url.startsWith("/api/v1/memory?")) {
        return Promise.resolve({ nodes: [], edges: [] });
      }
      return Promise.reject(new Error(`unexpected: ${url}`));
    });
    render(wrap(<MemoryGraphWindow notebookId="nb1" />));
    await waitFor(() => {
      expect(screen.getByText(/No memory yet/i)).toBeInTheDocument();
    });
  });
});
```

### - [ ] Step 3: Run test to verify it fails

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-window.test.tsx
```
Expected: FAIL — module not found.

### - [ ] Step 4: Implement

Create `apps/web/components/notebook/contents/MemoryGraphWindow.tsx`:

```tsx
"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { apiGet } from "@/lib/api";
import { useGraphData } from "@/hooks/useGraphData";
import { MemoryGraphView, adaptGraphData } from "@/components/console/graph/memory-graph";

interface Props {
  notebookId: string;
}

export default function MemoryGraphWindow({ notebookId }: Props) {
  const t = useTranslations("console-notebooks");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [resolveError, setResolveError] = useState<string | null>(null);

  useEffect(() => {
    if (!notebookId) return;
    let cancelled = false;
    apiGet<{ project_id: string }>(`/api/v1/notebooks/${notebookId}`)
      .then((nb) => {
        if (!cancelled) setProjectId(nb.project_id ?? null);
      })
      .catch((err: Error) => {
        if (!cancelled) setResolveError(err.message || "resolve failed");
      });
    return () => { cancelled = true; };
  }, [notebookId]);

  const { data, loading } = useGraphData(projectId || "");

  const graph = useMemo(() => adaptGraphData(data), [data]);
  const loadingProject = projectId == null && !resolveError;

  if (loadingProject || (loading && graph.nodes.length === 0)) {
    return (
      <div style={{ padding: 24, fontSize: 14, color: "var(--text-secondary)" }}>
        {t("memoryGraph.loading")}
      </div>
    );
  }

  if (graph.nodes.length === 0) {
    return (
      <div style={{ padding: 32, textAlign: "center" }}>
        <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>
          {t("memoryGraph.empty.title")}
        </div>
        <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>
          {t("memoryGraph.empty.body")}
        </div>
      </div>
    );
  }

  return <MemoryGraphView nodes={graph.nodes} edges={graph.edges} />;
}
```

### - [ ] Step 5: Run test to verify it passes

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-window.test.tsx
```
Expected: PASS — 2 tests.

### - [ ] Step 6: Commit

```bash
git add apps/web/components/notebook/contents/MemoryGraphWindow.tsx \
        apps/web/tests/unit/memory-graph-window.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): add MemoryGraphWindow notebook content component

Resolves projectId from notebookId, wires useGraphData + adapter to
MemoryGraphView, shows loading / empty states.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Register memory_graph in WindowCanvas switch

**Files:**
- Modify: `apps/web/components/notebook/WindowCanvas.tsx`

### - [ ] Step 1: Add import + switch case

Modify `apps/web/components/notebook/WindowCanvas.tsx` imports (near line 13) to add:

```ts
import MemoryGraphWindow from "./contents/MemoryGraphWindow";
```

Modify the `WindowContent` switch (after the `case "memory":` block around line 45), add:

```ts
    case "memory_graph":
      return (
        <MemoryGraphWindow
          notebookId={windowState.meta.notebookId || ""}
        />
      );
```

### - [ ] Step 2: Typecheck

```bash
pnpm --filter web tsc --noEmit
```
Expected: 0 errors (WindowType union now includes "memory_graph" from Task 5, switch exhaustively handles it).

### - [ ] Step 3: Lint

```bash
pnpm --filter web lint --max-warnings=0 --no-cache components/notebook/WindowCanvas.tsx
```
Expected: no errors/warnings.

### - [ ] Step 4: Commit

```bash
git add apps/web/components/notebook/WindowCanvas.tsx
git commit -m "$(cat <<'EOF'
chore(web): route memory_graph window type to MemoryGraphWindow

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: NotebookSidebar — add Memory Graph tab

**Files:**
- Modify: `apps/web/components/console/NotebookSidebar.tsx`
- Test: `apps/web/tests/unit/memory-graph-sidebar.test.tsx`

### - [ ] Step 1: Write the failing test

Create `apps/web/tests/unit/memory-graph-sidebar.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NextIntlClientProvider } from "next-intl";
import en from "@/messages/en/console-notebooks.json";
import enConsole from "@/messages/en/console.json";
import NotebookSidebar from "@/components/console/NotebookSidebar";

vi.mock("@/lib/api", () => ({ apiGet: vi.fn().mockResolvedValue({ items: [] }) }));
vi.mock("@/hooks/useDigestUnreadCount", () => ({ useDigestUnreadCount: () => 0 }));
vi.mock("@/hooks/useBillingMe", () => ({ useBillingMe: () => null }));

const openSpy = vi.fn();
vi.mock("@/components/notebook/WindowManager", () => ({
  useWindowManager: () => ({ openWindow: openSpy }),
  useWindows: () => [],
}));
vi.mock("@/components/notebook/MinimizedTray", () => ({ default: () => null }));
vi.mock("next/navigation", () => ({ usePathname: () => "/app/notebooks/nb1" }));

function wrap(ui: React.ReactNode) {
  return (
    <NextIntlClientProvider
      locale="en"
      messages={{ "console-notebooks": en, console: enConsole }}
    >
      {ui}
    </NextIntlClientProvider>
  );
}

describe("NotebookSidebar — memory_graph tab", () => {
  it("renders the memory_graph tab button", () => {
    render(wrap(<NotebookSidebar notebookId="nb1" />));
    expect(screen.getByTestId("sidebar-tab-memory_graph")).toBeInTheDocument();
  });

  it("opens the memory_graph window on click", () => {
    render(wrap(<NotebookSidebar notebookId="nb1" />));
    fireEvent.click(screen.getByTestId("sidebar-tab-memory_graph"));
    expect(openSpy).toHaveBeenCalledWith({
      type: "memory_graph",
      title: "Open Memory Graph",
      meta: { notebookId: "nb1" },
    });
  });
});
```

### - [ ] Step 2: Run test to verify it fails

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-sidebar.test.tsx
```
Expected: FAIL — `testid sidebar-tab-memory_graph` not found.

### - [ ] Step 3: Modify sidebar

Modify `apps/web/components/console/NotebookSidebar.tsx`:

**Import a graph icon** (add to existing lucide-react import block, line 7-16):

```ts
import {
  ArrowLeft,
  Bell,
  FileText,
  Sparkles,
  Brain,
  BookOpen,
  Settings,
  Search,
  Network,
} from "lucide-react";
```

**Extend `SideTab` union** (line 23):

```ts
type SideTab = "pages" | "ai_panel" | "memory" | "memory_graph" | "learn" | "digest" | "search" | null;
```

**Add to TABS array** (insert after the `"memory"` tab entry around line 33):

```ts
const TABS = [
  { id: "pages" as const, Icon: FileText, key: "nav.pages" },
  { id: "search" as const, Icon: Search, key: "nav.search" },
  { id: "ai_panel" as const, Icon: Sparkles, key: "nav.aiPanel" },
  { id: "memory" as const, Icon: Brain, key: "nav.memory" },
  { id: "memory_graph" as const, Icon: Network, key: "nav.memoryGraph" },
  { id: "learn" as const, Icon: BookOpen, key: "nav.learn" },
  { id: "digest" as const, Icon: Bell, key: "nav.digest" },
] as const;
```

**Extend `handleTabClick` switch** (after the `"memory"` branch around line 106):

```ts
      if (tabId === "memory") {
        openWindow({
          type: "memory",
          title: tn("sidebar.openMemory"),
          meta: { notebookId },
        });
      } else if (tabId === "memory_graph") {
        openWindow({
          type: "memory_graph",
          title: tn("sidebar.openMemoryGraph"),
          meta: { notebookId },
        });
      } else if (tabId === "learn") {
```

### - [ ] Step 4: Add i18n key for `nav.memoryGraph` in console (not console-notebooks)

The `title` attribute uses `t(tab.key)` which reads from the `console` namespace (line 40: `const t = useTranslations("console")`). Add to `apps/web/messages/en/console.json`:

```json
"nav.memoryGraph": "Memory Graph",
```

And `apps/web/messages/zh/console.json`:

```json
"nav.memoryGraph": "记忆图谱",
```

(Insert near other `nav.*` entries.)

### - [ ] Step 5: Run test to verify it passes

```bash
pnpm --filter web test:unit -- tests/unit/memory-graph-sidebar.test.tsx
```
Expected: PASS — 2 tests.

### - [ ] Step 6: Typecheck + lint

```bash
pnpm --filter web tsc --noEmit
pnpm --filter web lint --max-warnings=0 --no-cache components/console/NotebookSidebar.tsx
```
Expected: 0 errors.

### - [ ] Step 7: Commit

```bash
git add apps/web/components/console/NotebookSidebar.tsx \
        apps/web/messages/en/console.json \
        apps/web/messages/zh/console.json \
        apps/web/tests/unit/memory-graph-sidebar.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): add Memory Graph tab to NotebookSidebar

Network icon between Brain and BookOpen; opens memory_graph window
with notebookId meta. Adds nav.memoryGraph i18n key (en + zh).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Manual acceptance pass (guide §7 + spec §2)

**Files:** (none — this is a verification task)

### - [ ] Step 1: Run the full test suite

```bash
pnpm --filter web test:unit
pnpm --filter web tsc --noEmit
pnpm --filter web lint
```
Expected: all green.

### - [ ] Step 2: Start the dev server

```bash
pnpm --filter web dev
```
Wait for "Ready on http://localhost:3000".

### - [ ] Step 3: Walk the acceptance checklist with a seeded notebook

Open an existing notebook that has memory data (the sidebar should already have had memory extracted). Click the "Memory Graph" icon (Network glyph).

Verify each of the following. For any fail, read the offending file, fix the issue, re-run tests, and commit separately as `fix(web): …`.

- [ ] Window opens at 1100×720, centered in cascade position
- [ ] Within 2–3s the simulation settles (no runaway jitter)
- [ ] Role colors: fact=blue, structure=violet, subject=emerald, concept=teal, summary=amber
- [ ] Node radius visibly tracks `conf` (a 0.95-conf node is obviously larger than a 0.72-conf one)
- [ ] `pinned: true` nodes show a dashed halo + SVG glow
- [ ] Drag a node — it sticks to the cursor; release — it re-enters the simulation and nudges neighbors
- [ ] Drag empty canvas — whole graph pans; wheel — zoom anchored at cursor; range 0.4–2.5
- [ ] Hover a node — non-neighbor nodes fade to 0.38 opacity; focused edges turn teal + show relation pill
- [ ] Search "foo" — non-matches fade to 0.18 opacity; matches stay full-opacity
- [ ] Confidence slider dragged to 0.9 — low-conf nodes disappear along with their edges
- [ ] Each role chip toggles on/off; toggled-off nodes become invisible but the graph doesn't reflow
- [ ] "Rearrange" button re-seeds a circular layout and reheats; "Fit" resets `k=1, tx=ty=0`
- [ ] Click a node — drawer appears on right (or bottom sheet under 960px) with pill + pinned + conf + summary + neighbors + lifecycle
- [ ] Clicking a neighbor row in drawer navigates to that neighbor (selection changes, drawer updates)
- [ ] List tab shows same filtered/searched node set; clicking a column header sorts; clicking a row selects + opens drawer
- [ ] Legend top-left shows 5 role dots; zoom indicator bottom-left shows % + `+/−/⛶` buttons
- [ ] Dark mode (system preference or toggle via OS) — canvas background swaps; labels + drawer stay readable
- [ ] Resize window below 960px width — drawer becomes a bottom sheet; toolbar wraps; canvas remains usable

### - [ ] Step 4: Record residual issues

If any items above fail, do NOT mark the task complete. Open follow-up fixes (one commit each) and re-run this checklist. Only move on when every box ticks.

### - [ ] Step 5: Final commit of acceptance notes

Create a short note in the PR description (not a repo file) listing any known-but-deferred minor items found during acceptance. No commit needed for this step.

---

## Self-Review (plan author)

**Spec coverage:**

| Spec item | Plan task |
|---|---|
| New `memory_graph` window type in WindowManager | Task 5 |
| New window content `MemoryGraphWindow` | Task 13 |
| WindowCanvas switch routing | Task 14 |
| NotebookSidebar trigger button + i18n | Task 15 |
| 5-role palette (constants.ts) | Task 1 |
| 11+1 edge styles | Task 1 |
| Verlet force sim per guide §3.2/3.3 | Task 4 |
| Adapter (5-role derivation + field mapping) | Task 3 |
| Humanize utility | Task 2 |
| GraphCanvas (SVG, drag/pan/zoom, hover, search, filter) | Task 11 |
| Toolbar (search, conf slider, chips, view) | Task 8 |
| NodeDetailDrawer (header, meta, summary, neighbors, lifecycle) | Task 9 |
| ListView | Task 10 |
| LegendAndZoom overlay | Task 7 |
| View assembly + state + responsive | Task 12 |
| i18n keys | Tasks 6, 15 |
| Acceptance walkthrough (guide §7) | Task 16 |

All 16 spec in-scope bullets covered.

**Type consistency check (cross-task symbols):**
- `GraphNode`, `GraphEdge`, `Role`, `Position`, `ViewportState`, `ForceParams` → defined in Task 1 `types.ts`, referenced by Tasks 3, 4, 7–13 ✓
- `ROLE_STYLE`, `EDGE_STYLE`, `FORCE_PARAMS`, `VIEWPORT_DEFAULTS`, `LABEL_MAX_CHARS` → defined Task 1 `constants.ts`, consumed Tasks 3, 7–12 ✓
- `adaptGraphData` → defined Task 3, consumed Task 13 ✓
- `humanizeRelativeTime` → defined Task 2, consumed Task 3 ✓
- `useForceSim`, `tickOnce`, `seedCircle`, `shouldStop`, `ForceSimHandle` → defined Task 4, consumed Tasks 11, 12 ✓
- `clampZoom`, `nextZoom` → defined Task 11, consumed Task 12 ✓
- `MemoryGraphView`, `DrawerNeighbor` → defined Tasks 12, 9, consumed Task 13 ✓
- i18n keys `memoryGraph.*` + `sidebar.openMemoryGraph` → defined Task 6, consumed Tasks 7–10, 13, 15 ✓

No placeholder language, no "TODO" / "TBD" / "similar to". Every code step shows complete, compilable code.

**Out-of-scope items from spec that are NOT in the plan (by design):**
- 3D star cloud view (PR #2)
- Real lifecycle events (static 3/4 is in Task 9)
- New `/memory-graph` endpoint (using existing `/api/v1/memory`)
- Migration of existing `/memory` page route
- Keyboard shortcuts
- Edit operations in graph
- Graph-wide analytics

These match the spec's §2 "Out of scope" list exactly.
