# Memory Graph Window — 2D Force-Directed (Design)

Date: 2026-04-19
Status: Draft — awaiting user review
Scope: New notebook window type rendering the project's memory
graph as an interactive 2D force-directed diagram. First of two
PRs — 3D visionOS cloud view follows in a separate spec (tracks
`UPGRADE_GUIDE_3D.md`).

## 1. Purpose

Users today can browse memory through two surfaces:

1. `/workspace/notebooks/[notebookId]/memory/page.tsx` — a card grid
   (`MemoryCardGrid`) for reading memory content one card at a time.
2. The existing `components/console/graph/MemoryGraph.tsx` (133KB,
   d3-force) — a full-screen graph page, not embedded in the
   notebook's windowed workspace.

Neither surface lets a user **explore the shape of their memory
graph inside the notebook itself**: which facts cluster together,
which concepts feed which summaries, where confidence thresholds
cut the graph in half, which pinned playbook-style nodes sit at
the center. That exploratory view is what `UPGRADE_GUIDE.md`
describes.

This spec adds a dedicated **`memory_graph` window type** to the
notebook's free-canvas windowed workspace. Opening the window
renders a force-directed 2D graph driven by the same `useGraphData`
hook the rest of the notebook uses, so the view is live (SSE-fed)
and consistent with what cards show.

The existing `MemoryGraph.tsx` + memory page route are NOT touched.
Short-term they coexist: the new window is the in-notebook
exploration tool, the old page stays for users who land on the
route directly. A later cleanup PR can migrate the route to the
new component, but that is out of scope here.

## 2. Scope

### In scope

**New window type:**
- Register `"memory_graph"` in `WindowType` union
  (`apps/web/components/notebook/WindowManager.tsx:21`)
- Add default size `{ width: 1100, height: 720 }` in
  `DEFAULT_SIZES`
- Route rendering in `WindowCanvas.tsx` switch to new
  `MemoryGraphWindow` content component
- Open trigger button in `NotebookSidebar.tsx` ("记忆图谱" /
  "Memory Graph"), sibling to the existing memory button
- i18n keys under `notebook.memoryGraph.*` (zh + en)

**Graph rendering:**
- SVG canvas with viewport transform (`translate(tx, ty) scale(k)`),
  drag-to-pan on empty space, wheel-to-zoom anchored at cursor,
  zoom range `0.4 – 2.5×`
- Node drag fixes `fx/fy` during drag, releases on pointerup so
  the node re-enters the simulation
- Self-implemented Verlet force simulation per
  `UPGRADE_GUIDE.md §3.2–3.3` (`useForceSim` hook)
- 5-role color palette (see §4.2 below) — expanded from the
  guide's 4-type palette to match the actual backend taxonomy
- Node radius: `r = 8 + (conf − 0.7) × 14`; `pinned: true` nodes
  get +3 radius, a dashed halo, and an SVG glow filter (the
  guide's "playbook" visual treatment applied to any pinned node)
- Edge base: `#94a3b8`, width 1; edges touching the focused node
  (hover > selection) switch to `#0D9488` (primary), width 1.8;
  a pill-shaped relation label appears at the midpoint of focused
  edges
- Opacity rules per guide §1.4 (normal / focus-mode dim / search
  miss), all transitions 200ms

**Controls:**
- Search box (realtime; non-matches fade to 0.18 opacity)
- Confidence slider `0.6 – 0.99`; nodes below threshold and
  their edges are removed from the scene entirely
- Type chip filter (5 chips, one per role); toggles visibility
- "重排" / "Rearrange" button — re-seeds circular layout and
  reheats the simulation (`alpha = 1`)
- "适配" / "Fit" button — resets viewport to `{ k: 1, tx: 0,
  ty: 0 }`
- Zoom indicator bottom-left showing current percentage + `+` /
  `−` buttons
- Type legend top-left

**Right detail drawer (300px, full window height):**
- Header: role pill + pinned marker + confidence value
- Node title (label, up to 2 lines)
- 3-column meta grid: source / reuse count / last used (humanized)
- Confidence progress bar
- Summary section (content body)
- Neighbors list (1-hop, computed from the live graph), each row
  clickable to select that neighbor
- Lifecycle indicator — four static stages (observe / consolidate
  / reuse / reinforce), showing 3 of 4 done. Real event stream
  is out of scope (§10).

**List view:** an alternative tab that shows the same filtered
node set as a sortable table (by label / type / conf / reuse /
lastUsed). Reuses the same header filter controls.

**Dark mode:** canvas background and drawer surfaces swap to
dark-mode equivalents via the existing `--bg-*` CSS variables.
Node fills and strokes stay the same (they're already chosen to
survive both backgrounds per the guide).

**Responsive:** under 960px window width, drawer collapses to a
bottom sheet (60% window height) instead of a right sidebar.

### Out of scope (explicit)

- **3D star-cloud view** — separate PR, tracks `UPGRADE_GUIDE_3D.md`
  (expected as `2026-XX-XX-memory-graph-3d-design.md`)
- **Real lifecycle events** — backend has no `memory_events` table
  yet; the lifecycle widget renders static 3/4 done as the guide
  permits in §4.3. When the backend ships `MemoryEvent[]`, a
  follow-up wires it in.
- **New `/memory-graph` endpoint** — the view uses the existing
  `GET /api/v1/memory?project_id=...` endpoint. Guide §6.1's
  proposed dedicated endpoint with `?focus=&minConf=` server-side
  filtering is not built; the frontend does filtering client-side.
  The data volume (20–200 nodes) comfortably supports this.
- **Migration of `MemoryGraph.tsx` / memory page route** — stays
  on the old implementation.
- **Edit operations inside the graph** — read-only view. Creating,
  renaming, deleting nodes/edges stays on existing surfaces
  (cards, inline editors). Drawer's "Neighbors" rows are
  navigation only, not mutation.
- **Keyboard shortcuts** — arrow keys, `/` to focus search, Esc
  to close drawer. Deferred to a polish pass; not blocking
  acceptance.
- **Graph-wide analytics** (avg degree, connected components,
  betweenness) — interesting but not requested.

## 3. Architecture

### 3.1 Data flow

```
┌────────────────────────────────┐
│  NotebookSidebar               │
│  └─ "Memory Graph" button      │── openWindow({ type:"memory_graph", meta:{projectId}})
└───────────────┬────────────────┘
                │
                ▼
┌────────────────────────────────┐
│  WindowManager / WindowCanvas  │── renders content based on window.type
└───────────────┬────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────┐
│  MemoryGraphWindow  (notebook/contents/)                   │
│  ├─ useGraphData(projectId)   → { nodes, edges, loading }  │
│  ├─ adaptGraphData(raw)       → { gNodes, gEdges }         │── 5-role
│  ├─ state: filters/search/confMin/selectedId/hoverId/view  │
│  └─ renders <MemoryGraphView ...> (console/graph/…)        │
└───────────────┬────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────┐
│  MemoryGraphView  (console/graph/memory-graph/)            │
│  ├─ Toolbar     (search, conf slider, type chips, btns)    │
│  ├─ LegendAndZoom (top-left legend + bottom-left zoom)     │
│  ├─ GraphCanvas                                            │
│  │    └─ useForceSim → positions                           │
│  │    └─ SVG nodes/edges/labels with drag/pan/zoom         │
│  ├─ NodeDetailDrawer (right side or bottom sheet)          │
│  └─ ListView (alternative tab)                             │
└────────────────────────────────────────────────────────────┘
```

### 3.2 File layout

```
apps/web/components/notebook/contents/
  MemoryGraphWindow.tsx            # window content wrapper; owns state

apps/web/components/console/graph/memory-graph/
  index.ts                         # re-exports (MemoryGraphView, types)
  types.ts                         # GraphNode, GraphEdge (internal)
  constants.ts                     # ROLE_STYLE, EDGE_STYLE, FORCE_PARAMS,
                                   #   RELATION_LABELS, VIEWPORT_DEFAULTS
  adapter.ts                       # backend MemoryNode/MemoryEdge → GraphNode/GraphEdge
  humanize.ts                      # timestamp → "2h" / "3d"
  useForceSim.ts                   # Verlet loop hook
  MemoryGraphView.tsx              # top-level 2D view
  GraphCanvas.tsx                  # SVG + viewport + drag/pan/zoom + raycast
  Toolbar.tsx                      # search / conf / chips / buttons
  LegendAndZoom.tsx                # legend (top-left) + zoom indicator (bottom-left)
  NodeDetailDrawer.tsx             # right drawer / bottom sheet
  ListView.tsx                     # table view
```

The internal pieces live under `console/graph/memory-graph/` —
same neighborhood as the existing `MemoryGraph.tsx` /
`MemoryGraphOrbitScene.tsx` — so a future 3D PR and a future
migration of the old page can both reach them cleanly.

### 3.3 State ownership

`MemoryGraphWindow` owns all view state and passes it down:

| State | Type | Purpose |
|---|---|---|
| `filters` | `Record<Role, boolean>` | which of the 5 roles are visible |
| `search` | `string` | fuzzy-matched against `label` |
| `confMin` | `number` (0.6–0.99) | nodes with `conf < confMin` removed |
| `selectedId` | `string \| null` | selected node → drawer content |
| `hoverId` | `string \| null` | hover overrides selection for focus |
| `view` | `"graph" \| "list"` | tab |
| `viewport` | `{ k, tx, ty }` | pan + zoom |

None of this persists across window close/reopen in this PR —
the notebook's existing window persistence layer only remembers
position/size, not window-specific state.

## 4. Data model

### 4.1 Backend shape (unchanged)

`useGraphData(projectId)` returns, from `/api/v1/memory?project_id=…`:

```ts
MemoryNode {
  id: string
  content: string           // raw memory text
  category: string
  type: "permanent" | "temporary"
  confidence: number | null
  node_type: string | null  // "fact" | "concept" | "subject" | "summary" | "root" | …
  metadata_json: {
    node_kind?, pinned?, retrieval_count?, last_used_at?,
    category_label?, structural_only?, ...
  }
  ...
}

MemoryEdge {
  id, source_memory_id, target_memory_id
  edge_type: "auto" | "manual" | "related" | "summary" | "file" | "center"
           | "parent" | "prerequisite" | "evidence" | "supersedes" | "conflict"
  strength: number
}
```

### 4.2 Internal shape (adapter output)

```ts
type Role = "fact" | "structure" | "subject" | "concept" | "summary"

type GraphNode = {
  id: string
  role: Role                // derived via getMemoryNodeRole() — 5 classes
  label: string             // content truncated to ~28 chars
  conf: number              // confidence ?? 0.5
  reuse: number             // metadata_json.retrieval_count ?? 0
  lastUsed: string | null   // humanize(metadata_json.last_used_at) → "2h" / "3d" / null
  pinned: boolean           // metadata_json.pinned === true
  source: string | null     // metadata_json.category_label ?? category
  raw: MemoryNode           // full object for drawer's summary + other reads
}

type GraphEdge = {
  a: string                 // source_memory_id
  b: string                 // target_memory_id
  rel: string               // edge_type (verbatim; guide §2.3 "tolerate any string")
  w: number                 // strength, used in link spring
}
```

### 4.3 Role palette (5 roles)

The guide's 4-type palette is extended to 5, using MRNote's teal
brand color for the new `concept` tier and a neutral violet for
`structure` (category hierarchy / organizational "skeleton"):

| role | fill | stroke | text | dot |
|---|---|---|---|---|
| `fact` | `#dbeafe` | `#2563eb` | `#1e40af` | `#2563eb` |
| `structure` | `#ede9fe` | `#7c3aed` | `#5b21b6` | `#7c3aed` |
| `subject` | `#d1fae5` | `#10b981` | `#047857` | `#10b981` |
| `concept` | `#ccfbf1` | `#0d9488` | `#0f766e` | `#0d9488` |
| `summary` | `#fef3c7` | `#f59e0b` | `#b45309` | `#f59e0b` |

Colors live in `constants.ts` as static literals. They are
deliberately not wired through Tailwind theme tokens — they're
domain-specific and shouldn't pollute the design-token space.

### 4.4 Edge styling (per backend `edge_type`)

Following guide §2.3's "tolerate any string" rule, all 11 backend
edge types get a concrete visual. Unknown strings fall back to
the `related` style.

| edge_type | stroke | width | style | semantic intent |
|---|---|---|---|---|
| `parent`, `center` | `#64748b` | 1.4 | solid | structural backbone |
| `supersedes` | `#ef4444` | 1.2 | solid | version replacement |
| `conflict` | `#ef4444` | 1.2 | dashed | contradiction |
| `prerequisite` | `#2563eb` | 1.2 | solid | dependency |
| `evidence` | `#10b981` | 1.2 | solid | support |
| `summary` | `#f59e0b` | 1.2 | dashed | derivation |
| `related`, `auto`, `manual` | `#94a3b8` | 1.0 | solid | weak/generic |
| `file` | `#6366f1` | 1.0 | dashed | attachment |

Edge width under focus: +0.8, stroke switches to `#0D9488`
(MRNote primary teal) per guide §1.3.

### 4.5 Node filtering

Nodes are dropped from the graph (not just dimmed) when:

- `node_status === "superseded" || "archived"` — already stripped
  by `useGraphData`'s `augmentGraphDataWithCategoryBranches`,
  so no action needed
- `isSyntheticGraphNode(node) === true` — also already stripped
- `conf < confMin` (user's slider) — removed client-side in
  `MemoryGraphWindow`, including orphaned edges

Nodes are dimmed (opacity change, stay rendered) when:

- `filters[role] === false` (opacity 0)
- No `search` match (opacity 0.18)
- Focus mode and not focus/neighbor (opacity 0.38)

## 5. Force simulation

### 5.1 Parameters

Copied from guide §3.2:

```ts
const FORCE_PARAMS = {
  linkDistance:   90,
  linkStrength:   0.06,
  charge:        -340,
  centerStrength: 0.015,
  collide:        38,
  damping:        0.82,
  alphaInit:      1,
  alphaDecay:     0.985,
  alphaMin:       0.001,
};
```

### 5.2 Tick algorithm

Per guide §3.3:

1. N² charge (Coulomb-style repulsion, scaled by α)
2. Link spring (Hooke, scaled by `w × α`)
3. Center gravity toward `(W/2, H/2)`
4. Collision resolution at `2 × collide`
5. Integrate velocity with `damping`, clamp to viewport with
   `pad = 24`
6. `α *= alphaDecay`; stop when `α < alphaMin`

Uses `requestAnimationFrame`. The hook depends on
`[nodesLength, edgesLength, viewport.width, viewport.height]` —
filtering changes don't restart the sim, just change which
nodes/edges are rendered.

Dragged nodes have their `fx / fy` written into the positions
array; the integrator skips them. On pointerup, `fx / fy` are
cleared and `alpha` is re-heated to `0.3` so the graph settles.

### 5.3 Performance

20–200 nodes, which is well inside the budget for an unoptimized
O(N²) charge pass at 60 Hz. No quadtree. If a future project
grows beyond this (unlikely for a single notebook's memory), a
follow-up can swap in spatial hashing.

## 6. Interactions

Complete mapping of guide §1.5:

| Action | Behavior |
|---|---|
| Hover node | focus = hover; 1-hop neighbors stay at opacity 1, others → 0.38; focused edges switch to primary teal + show relation pill label at midpoint |
| Click node | `selectedId = id`; drawer opens |
| Drag node | set `fx, fy`; node sticks to cursor while dragging |
| Release drag | clear `fx, fy`; `alpha = 0.3` to resettle |
| Drag empty canvas | update viewport `(tx, ty)` |
| Wheel | update viewport `k`, anchored to cursor; range 0.4–2.5 |
| Search input | realtime fuzzy match against `label`; non-matches → 0.18 |
| Conf slider | `confMin` — nodes below threshold removed; orphaned edges also removed |
| Type chip | toggle `filters[role]`; `filters === false` → opacity 0 |
| Rearrange button | re-seed circular positions; `alpha = 1`; clear all `fx, fy` |
| Fit button | `viewport = { k: 1, tx: 0, ty: 0 }` |
| Drawer neighbor row | `selectedId = neighborId` — navigates drawer to that neighbor |
| Zoom `+` / `−` | step `k` by `× 1.2` / `÷ 1.2`, clamp to range |

## 7. Integration with the notebook window system

### 7.1 Window registration

`WindowManager.tsx:21` currently has:

```ts
type WindowType = "note" | "ai_panel" | "file" | "memory"
                | "study" | "digest" | "search";
```

Change to:

```ts
type WindowType = "note" | "ai_panel" | "file" | "memory"
                | "memory_graph"
                | "study" | "digest" | "search";
```

`DEFAULT_SIZES` (same file): add
`memory_graph: { width: 1100, height: 720 }`.

`WindowCanvas.tsx` switch: add a case that renders
`<MemoryGraphWindow projectId={meta.projectId} notebookId={meta.notebookId} />`.

### 7.2 Open trigger

`NotebookSidebar.tsx` currently has an entry that opens the
existing `"memory"` window type. Add a sibling entry:

```ts
{
  icon: <GraphIcon />,           // e.g. a small force-graph glyph
  label: t("notebook.sidebar.memoryGraph"),
  onClick: () =>
    openWindow({
      type: "memory_graph",
      title: t("notebook.memoryGraph.title"),
      meta: { projectId, notebookId },
    }),
}
```

The exact placement in the sidebar (above / below the existing
memory entry) is a minor layout call made in the implementation
plan — not worth pre-deciding here.

### 7.3 i18n keys

New keys under `notebook.memoryGraph.*`:

- `title` — window title bar text
- `search.placeholder`
- `confSlider.label`
- `rearrange` / `fit` / `list` / `graph`
- `drawer.sections.summary` / `.neighbors` / `.lifecycle`
- `drawer.lifecycle.stages.observe` / `.consolidate` / `.reuse` / `.reinforce`
- `legend.title`
- `roles.fact` / `.structure` / `.subject` / `.concept` / `.summary`

Both `zh` and `en` filled. No existing keys are reused —
`notebook.memory.*` is the card view's namespace, conceptually
separate.

## 8. Testing

### 8.1 Unit tests

- `adapter.test.ts` — backend `MemoryNode` → `GraphNode` for each
  of the 5 roles; handles missing `confidence`, missing
  `metadata_json.retrieval_count`, null `last_used_at`,
  `pinned` coercion, truncation of long `content`
- `humanize.test.ts` — `"2h" / "30m" / "3d"` output for common
  offsets; edge cases around daylight saving / future timestamps
  (floor to `"0m"`)
- `useForceSim.test.ts` — `alpha` reaches `alphaMin` within ~3s
  for a 20-node graph; `fx/fy` respected by integrator; drag
  release clears and reheats

### 8.2 Component tests

- `MemoryGraphWindow.test.tsx` — mounts and unmounts cleanly
  (RAF cleanup; no lingering timers; no SSE leaks inherited
  from `useGraphData`)
- Filter chips toggle opacity, not node removal
- Conf slider removes nodes and orphaned edges
- Drawer opens on node click, closes on outside click / Esc

### 8.3 Manual acceptance

Full checklist from `UPGRADE_GUIDE.md §7` — 15 items. Adapted
line 1 from "fact/method/outcome/playbook" to the 5-role palette
per this spec's §4.3.

## 9. Risks & open questions

- **Label truncation heuristic** — 28 chars works for English;
  Chinese labels might need a different cutoff since a single
  character is semantically denser. Plan picks a value during
  implementation based on visual testing.
- **`useGraphData` already strips `"structural_only"` category
  branch nodes via `augmentGraphDataWithCategoryBranches`.** If
  the user wants the full structural skeleton visible, the
  adapter would need to re-add them. For this PR we follow the
  existing behavior (strip them); follow-up can expose a "show
  structural skeleton" toggle.
- **SSE-driven refresh while user is interacting** — the sim
  will reheat when the node set changes, which is mildly
  disruptive if it happens while the user is dragging. If it
  turns out to annoy users, debounce incoming SSE updates
  while a drag is in progress. Not pre-optimized.
- **Dark-mode node legibility** — a future design pass may want
  darker fills. For this PR we lean on the guide's assertion
  that the palette works on both backgrounds, and verify by eye
  in the acceptance checklist.

## 10. Follow-ups (not this PR)

- PR #2 — 3D visionOS cloud view (per `UPGRADE_GUIDE_3D.md`);
  adds a tab switcher inside the same window
- PR #3 — real lifecycle events backed by a new `memory_events`
  table
- PR #4 — migrate the existing `/memory` page route to use this
  component (retire `MemoryGraph.tsx` + `MemoryGraphOrbitScene.tsx`)
- Later — keyboard shortcuts, graph analytics overlay, "show
  structural skeleton" toggle
