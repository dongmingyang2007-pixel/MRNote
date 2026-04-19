# Memory Graph — 3D View + Layout Realignment (Design)

Date: 2026-04-19
Status: Draft — awaiting user review
Scope: Adds a third view mode (3D 星云) to the existing
`memory_graph` notebook window, plus a layout realignment of the
window header so the 2D / 3D / List view bar lives between a
top-level filter row (chips + conf slider + search) and the
canvas — matching the `index.html` prototype's `MemoryGraphWindow`
structure.

Builds on `2026-04-19-memory-graph-window-2d-design.md` (already
shipped). All shared concerns there — data adapter, useGraphData
SSE, role palette — apply unchanged.

## 1. Purpose

The 2D force-directed view ships in the existing `memory_graph`
window. Two follow-ups now:

1. The window's **layout** doesn't match the prototype the user
   reviewed and approved during product definition. Specifically,
   the prototype has:
   - Title bar inside the window: `记忆图谱 · Memory V3`
   - **Top filter row**: role chips + confidence slider + search,
     all in one bar
   - **View tab strip** below filters: `2D / 3D 星云 / List`
     (with node count per tab)
   - Canvas (graph or list) below tabs
   - Zoom indicator only in the bottom-left of the canvas
   The current shipped Toolbar mashes search + slider + chips +
   buttons + view tabs all into one horizontal flex row, which
   wraps badly on narrow windows and doesn't match the
   prototype's information hierarchy.

2. The 3D view itself doesn't exist. Per `UPGRADE_GUIDE_3D.md`
   and the prototype (`index.html` lines 1493–1709 + the
   `Memory3D` component), 3D is a glass-card visionOS-flavored
   space with concentric tier rings, a Y-axis mastery column,
   ground spokes, fog, and OrbitControls. Same data, additional
   spatial dimension.

## 2. Scope

### In scope

**Layout realignment (existing window):**
- Add a window-internal title row: `记忆图谱 · Memory V3` (en:
  `Memory Graph · V3`)
- Move conf slider + search input out of the Toolbar into a
  dedicated **filter row** alongside the chips. Order from left:
  5 role chips → conf slider → search input
- Replace the current Toolbar's "view tabs" segment with a
  full-width **view bar** below filters: `2D / 3D 星云 / List`,
  each with a node count badge (e.g., `2D 12`)
- `重排` and `适配` (rearrange / fit) buttons no longer live in
  the toolbar header. They move into the canvas as a small
  control cluster at the top-right of the canvas (only when 2D
  view is active — for 3D they're replaced by camera controls;
  see §3.4)
- Compact mode (existing <720px gate) still applies: chips
  collapse to a popover ▾ button, search shrinks, conf slider
  hides label

**3D view (`view === "3d"`):**
- New `Memory3D.tsx` component renders a Three.js scene inside the
  canvas slot
- Background uses `var(--bg-base)` (matches 2D, NOT prototype's
  sky gradient — per user direction). `WebGLRenderer({ alpha: true })`
  + container `background: var(--bg-base)` + fog color set to the
  resolved bg color
- Three concentric tier rings on the ground at `y = -90`:
  - subject (innermost, r=95, color `#10b981`)
  - concept (mid, r=175, color `#0d9488`)
  - fact (outer, r=245, color `#2563eb`)
  Each ring is a dashed `LineDashedMaterial` + a faint filled
  `RingGeometry` band
- 12 radial spokes every 30°, very faint (`0x9fb3c2`, opacity 0.18)
- Y-axis "mastery column" — vertical dashed line at origin
  (-90 to +90)
- Card sprites per node (per prototype lines 1587–1706):
  - 320×200 retina canvas
  - Glass gradient body + tinted radial corner wash + inner border
  - Type chip (top-left, type-color filled pill with glyph + label)
  - Reuse badge (top-right, only if `reuse > 0`)
  - Pinned dot (small orange circle next to reuse badge if pinned)
  - 2-line label (truncated)
  - Summary line (gray)
  - Conf arc (bottom-left, ¾ ring with conf-fill)
  - Source + age (bottom-right, mono)
- Drop line per node — thin vertical line from card position down
  to `y = -90` (the ground plane), opacity 0.22 — gives a sense
  of height
- Node placement (variant A — depth ring layout, the only
  variant for v1):
  - Bucket nodes by role
  - Place each role's nodes evenly around its tier ring
  - Y position = `(masteryOf(n) - 0.5) × 140` so high-mastery
    nodes float higher
  - Stable hash jitter on angle and radius (same node always
    lands in same spot across remounts)
- Edges:
  - All edges as `QuadraticBezierCurve3` (mid point lifted by
    +14 in Y for arc) — same algorithm as prototype
  - Skeleton edges always shown faint (`#475569`, opacity 0.42)
  - Semantic edges colored by `EDGE_STYLE[rel].stroke`, opacity
    follows focus state
  - Focus mode (1-hop / 2-hop dimming) per guide §6.3 +
    prototype
- Lights: AmbientLight 0.8 + warm sun DirectionalLight (0.7) +
  cool fill DirectionalLight (0.35)
- Camera: PerspectiveCamera (FoV 45, position (0,110,360))
- OrbitControls with `enableDamping`, polar clamps to keep above
  horizon, `minDistance=140`, `maxDistance=820`
- Interactions:
  - mouse drag = orbit (handled by OrbitControls)
  - wheel = zoom (handled by OrbitControls)
  - Hover node → DOM tooltip follows (small floating chip with
    type pill + label)
  - Click node → focus mode (camera tweens toward node, 1-hop
    nodes brighten, 2-hop dim, others very dim) + opens drawer
  - Click empty space → exits focus mode
  - "Rearrange" button → re-seeds layout (same hash, just
    reapplies — useful after data refresh)
  - "Fit" button → tweens camera back to default (0,110,360)
- HUD chrome inside canvas (DOM overlays, not WebGL):
  - Bottom-left: zoom percentage (computed from camera distance)
    + `+ / − / ⛶ fit / ↻ auto-rotate` cluster
- Resize observer drives renderer.setSize when container changes
- Cleanup on unmount: dispose all geometries, materials, textures,
  cancel RAF, remove canvas from DOM

**i18n (bilingual, en + zh):**
- All new copy gets keys under `memoryGraph.*` namespace in both
  `messages/en/console-notebooks.json` and
  `messages/zh/console-notebooks.json`
- New keys for: `header.brand` (the `· V3` suffix), tab label `3d`,
  axis label `axis.mastery`, ring labels (`tier.subject` /
  `tier.concept` / `tier.fact`), camera control labels
  (`camera.zoomIn` / `camera.zoomOut` / `camera.fit` /
  `camera.autoRotate`), tooltip role label fallback

### Out of scope (explicit)

- **Variant B (analog clock)** and **Variant C (focused 2-hop
  cluster as standalone view)** from the prototype — both shipped
  as toggles in the original; v1 ships only depth-ring (variant A)
  with focus-mode triggered by click.
- **Particle effects** (the prototype has rotating sparkles
  around playbook nodes) — skip; visual noise without info value.
- **Time-axis layering**, **multi-select focus**, **minimap**,
  **link replay** — UPGRADE_GUIDE_3D.md §11 explicitly future.
- **Sky gradient + fog atmosphere** — prototype uses light青灰
  gradient sky, but per user direction we use the same flat
  `var(--bg-base)` as 2D so dark mode (when project gains it)
  works coherently across both views.
- **Tier mapping for structure / summary roles** — backend filters
  these out before they reach the frontend (verified during 2D
  acceptance; see `apps/api/app/routers/memory.py:1191`). The 3
  tier rings cover the 3 roles that actually arrive. If backend
  later sends 5 roles, ring set extends to 5 — easy follow-up.
- **`Evidence / Learning / Health` tabs** from the prototype's
  6-tab strip — these are placeholders for future memory
  inspection features, not part of this PR.

## 3. Architecture

### 3.1 Component reorganization

Current files (already shipped, refactored here):

```
apps/web/components/console/graph/memory-graph/
  MemoryGraphView.tsx     ← restructured layout
  Toolbar.tsx              ← split into FilterRow + ViewBar
```

New files added by this spec:

```
apps/web/components/console/graph/memory-graph/
  HeaderBar.tsx            # title + brand suffix
  FilterRow.tsx            # chips + conf slider + search (replaces parts of Toolbar)
  ViewBar.tsx              # 2D / 3D / List tabs with counts
  CanvasControls.tsx       # 重排/适配 floating button cluster (top-right of 2D canvas)
  Memory3D/
    Memory3D.tsx           # top-level 3D component
    scene.ts               # Three.js scene bootstrap (renderer/lights/controls)
    layout3d.ts            # node placement (depth-ring layout)
    cardSprite.ts          # makeNodeCard — Canvas 2D card texture builder
    edges3d.ts             # bezier curve geometry + edge mesh helpers
    ground.ts              # tier rings + spokes + Y axis + ground disc
    constants3d.ts         # TIER_RADIUS, RING_COLORS, CARD_W, fog/light values
    useThreeScene.ts       # React hook wrapping scene lifecycle (mount, resize, cleanup)
    Tooltip3d.tsx          # DOM tooltip overlay (follows hovered card's screen pos)
    CameraControlsHud.tsx  # +/-/fit/autoRotate cluster
```

Toolbar.tsx is **deleted** at the end of this PR. Its responsibilities
move to FilterRow + ViewBar + CanvasControls. Existing tests for
Toolbar are rewritten against the new components.

### 3.2 New layout (matches prototype)

```
┌─────────────────────────────────────────────────────────────┐
│  🧠 记忆图谱 · Memory V3                          [─] [□] [✕] │  ← Window titlebar (existing)
├─────────────────────────────────────────────────────────────┤
│  HeaderBar                                                  │  ← NEW
├─────────────────────────────────────────────────────────────┤
│  ●Fact ●Structure ●Subject ●Concept ●Summary               │
│              置信度 ≥ ●━━━━ 0.70    🔍 搜索记忆…           │  ← FilterRow (chips + slider + search)
├─────────────────────────────────────────────────────────────┤
│  ⊞ 2D 12   ⌇ 3D 星云 12   ☰ List 12                        │  ← ViewBar (tabs with counts)
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   (canvas — graph SVG / Three.js / list table)              │
│                                                  [↻] [⛶]   │  ← CanvasControls (top-right)
│                                                             │
│   [legend]                                                  │  ← LegendAndZoom (existing, only in 2D)
│                                              [-] 100% [+]   │  ← Zoom (only in 2D / 3D)
└─────────────────────────────────────────────────────────────┘
```

In compact mode (<720px), FilterRow collapses: chips → ▾ popover,
slider hides label, search shrinks. ViewBar stays full-width.
Canvas controls + legend behave per existing logic.

### 3.3 View routing

`MemoryGraphView` switches the canvas slot based on `view` state:

| view | Component | Notes |
|---|---|---|
| `"graph"` (2D) | `<GraphCanvas>` + `<LegendAndZoom>` + `<CanvasControls>` | unchanged from PR #1 |
| `"3d"` | `<Memory3D>` + `<Tooltip3d>` + `<CameraControlsHud>` | new |
| `"list"` | `<ListView>` | unchanged |

State that is **shared** across views (lives in MemoryGraphView):
- `search`, `confMin`, `filters`, `selectedId`, `hoverId`
- `effectiveNodes`, `effectiveEdges`, `searchMatches`, `counts` —
  derived from above

State **owned by 2D only**: `viewport: { k, tx, ty }`
State **owned by 3D only**: `cameraTarget`, `cameraPos` (managed
by OrbitControls + a `cameraAnimRef` for tween animations)

This means switching from 2D to 3D preserves selection, search,
filter state — only the rendering changes. Per UPGRADE_GUIDE_3D §1
("无缝切换" — seamless switching).

### 3.4 3D scene composition

Per prototype lines 1709–1900-ish (full bootstrap inside `m3E`
useEffect). Adapted for our codebase:

1. `scene.background = null` (transparent — let CSS bg show through)
2. `scene.fog = new THREE.Fog(<resolvedBgColor>, 380, 1100)` — fog
   color reads CSS `--bg-base` once at mount, falls back to
   `0xf8fafc`
3. Lights: AmbientLight + warm sun + cool fill (per prototype)
4. OrbitControls with damping
5. Ground group: disc + 3 tier rings + spokes + Y column + ring
   labels (DOM-style sprite labels per prototype)
6. Edge group: bezier lines (semantic style) + skeleton lines
7. Node group: card sprites + drop lines
8. Raycaster for hover/click on nodes
9. RAF loop: `controls.update()` + `renderer.render()` +
   tooltip projection (project hovered node world → screen)

### 3.5 Card sprite generation (`cardSprite.ts`)

Pure function `makeNodeCard(node: GraphNode, cfg: TierStyle): THREE.Sprite`.
Returns a sprite with `THREE.CanvasTexture(canvas)` material. Caller
disposes texture on remove.

Cache key: `${id}:${conf}:${reuse}:${pinned}` — re-create only when
display-affecting props change. The cache is component-local
(Map in `useThreeScene`).

Card layout matches prototype exactly. Adaptations:
- Type label / chip color from `ROLE_STYLE` (5-role palette,
  re-uses 2D constants)
- Glyph: simple ASCII mapped per role (`◇` fact, `⬢` subject,
  `◈` concept; structure / summary use `▣` / `▤` even though
  they don't reach frontend currently)

### 3.6 Tier ring config (`constants3d.ts`)

```ts
export const TIER_RADIUS: Record<Role, number> = {
  subject:   95,
  concept:   175,
  fact:      245,
  // structure/summary not reached by current backend; reserve room
  structure: 60,   // (unused for now — innermost if it ever ships)
  summary:   310,  // (unused for now — outermost)
};

export const RING_COLORS: Record<Role, number> = {
  subject:   0x10b981,
  concept:   0x0d9488,
  fact:      0x2563eb,
  structure: 0x7c3aed,
  summary:   0xf59e0b,
};
```

Only `subject / concept / fact` rings are added to the scene
(`structure / summary` skipped because no nodes ever land there).

### 3.7 Camera animation

`useThreeScene` exposes `focusOn(nodeId | null)`. Implementation:

- Read node's world position
- Set `cameraAnim.current = { fromTarget, toTarget, fromPos, toPos, t:0, dur:0.9 }` where `toPos = nodePos + (0, 60, 180)`
- RAF loop interpolates with ease-in-out
- When `nodeId === null`, target = origin, pos = `(0, 110, 360)`

Per `UPGRADE_GUIDE_3D §6.4`.

### 3.8 Tooltip overlay (`Tooltip3d.tsx`)

Pure DOM element, absolutely positioned within the canvas
container. Updates each RAF tick from `useThreeScene` via:

```ts
const v = node.position.clone().project(camera);
const x = (v.x * 0.5 + 0.5) * rect.width;
const y = (-v.y * 0.5 + 0.5) * rect.height;
setTooltip({ id: node.userData.id, x, y });
```

Renders only when `hoveredId !== null`. Pill-shaped with type chip
+ label. Same i18n as 2D drawer header.

### 3.9 Camera controls HUD (`CameraControlsHud.tsx`)

Bottom-left DOM cluster, glass-card styled. Buttons:

- `+` → `controls.dollyOut(1.2)`
- `−` → `controls.dollyIn(1.2)`
- `⛶ fit` → `focusOn(null)` (resets to default camera)
- `↻ autoRotate` → toggle `controls.autoRotate`

Zoom percent is computed from `camera.position.length() / DEFAULT_DISTANCE`.

## 4. i18n (bilingual)

New keys added to **both** `messages/en/console-notebooks.json`
and `messages/zh/console-notebooks.json`:

```
memoryGraph.header.brand              " · V3" / " · Memory V3"
memoryGraph.view.3d                   "3D Cloud" / "3D 星云"
memoryGraph.view.countSuffix          (none — suffix is just the number)
memoryGraph.tier.subject              "Subject" / "主题"
memoryGraph.tier.concept              "Concept" / "概念"
memoryGraph.tier.fact                 "Fact" / "事实"
memoryGraph.axis.mastery              "↑ Mastery" / "↑ 熟练度"
memoryGraph.camera.zoomIn             "Zoom in" / "放大"
memoryGraph.camera.zoomOut            "Zoom out" / "缩小"
memoryGraph.camera.fit                "Fit" / "适配"
memoryGraph.camera.autoRotate         "Auto-rotate" / "自动旋转"
memoryGraph.tooltip.unselect          "Click empty space to deselect" / "点击空白处取消选中"
```

(Existing `memoryGraph.view.graph` ("Graph" / "图谱") stays for
the 2D tab; the 3D tab uses `view.3d`.)

## 5. Backend: no changes

3D view consumes the same `useGraphData` hook + `adaptGraphData`
adapter as 2D. No new API endpoint, no new fields.

## 6. Testing

### 6.1 Unit tests

- `cardSprite.test.ts` — `makeNodeCard` returns a sprite with a
  CanvasTexture; tests one node per role + tests pinned + tests
  reuse badge appears when `reuse > 0`
- `layout3d.test.ts` — `placeNodes` returns correct ring per role,
  Y position matches `masteryOf` formula, jitter is deterministic
  (same id → same position across runs)
- `Memory3D.test.tsx` — smoke test: renders, mounts a canvas,
  unmounts cleanly (no RAF leaks). Use `vi.useFakeTimers()` and
  mock requestAnimationFrame
- Tests for new layout: `FilterRow.test.tsx`, `ViewBar.test.tsx`,
  `CanvasControls.test.tsx` — keep coverage of search/conf/filter
  toggle, view tab switching, button clicks (port from existing
  Toolbar tests)
- Update `MemoryGraphView.test.tsx` — verify 3D tab switches to
  Memory3D component (skip rendering the actual Three.js — mock
  Memory3D as a stub div with data-testid="memory-3d-stub")

### 6.2 Manual acceptance (preview-driven)

A new acceptance pass against `UPGRADE_GUIDE_3D §10` checklist
(13 items). I drive it via preview tools, same workflow as 2D §7.

## 7. Risks & open questions

- **Three.js bundle size**: three@0.183 is already installed
  (used by existing `MemoryGraphOrbitScene.tsx` we kept around).
  No new dep, no new bundle hit.
- **Card texture memory**: 320×200 × 2 (DPR) × 4 bytes = ~512KB
  per node. For 200 nodes = 100MB — too much. Mitigation: cap
  at 100 visible nodes, render the rest as fallback dot sprites
  (small `SphereGeometry` or untextured circle sprite). Trigger
  threshold via `effectiveNodes.length > 100`. If user's graph
  is currently 8 nodes (per acceptance), we're fine; document
  the cap for future scaling.
- **Three-Card cache invalidation**: when a node's `conf` changes
  via SSE, we must regenerate that one card. The cache key
  `${id}:${conf}:${reuse}:${pinned}` handles this; old textures
  must be `dispose()`d to avoid GPU leaks. Cleanup happens on
  cache replacement and on node removal.
- **OrbitControls vs node drag**: prototype only allows orbit
  (no node dragging in 3D). We follow that — node drag is 2D-only.
- **Hydration / SSR**: the existing `<Window>` + `<Rnd>` wrapper
  has known hydration quirks (we hit them during 2D acceptance).
  Memory3D is pure client code (`"use client";` + everything
  inside `useEffect`). Safe.

## 8. Follow-ups (not this PR)

- Variant B (analog clock) + Variant C (focused 2-hop standalone)
- Particle effects on playbook tier
- Time-axis Z-slicing
- Multi-focus (Shift+click)
- Minimap
- Link replay animation
- `Evidence / Learning / Health` view tabs (separate spec)
- Backend change to send `structure` + `summary` roles for full
  5-tier 3D view
- Dark mode token wiring (project-wide)
