# Memory Module UI Redesign - Design Spec

**Date:** 2026-04-08
**Status:** Approved
**Approach:** Memory Library (Apple Notes/Photos style)

---

## 1. Overview

Redesign the memory module from scratch. Current three-view system (workbench/orbit/list) is retained but every view is redesigned. The module becomes an active management tool (not just a visualization), styled after Apple system apps (Notes, Photos) with clean lines, spatial animation, and restrained color.

**Scope:** Frontend UI only. Backend API, `useGraphData` hook, and data models are unchanged.

**Files to rewrite:**
- `apps/web/app/[locale]/workspace/memory/page.tsx`
- `apps/web/components/console/MemoryListView.tsx`
- `apps/web/components/console/graph/MemoryGraph.tsx`
- `apps/web/components/console/graph/MemoryGraphOrbitScene.tsx`
- Related CSS sections in `globals.css`

**Files to keep as-is:**
- `apps/web/hooks/useGraphData.ts`
- `apps/api/app/routers/memory.py`
- `apps/api/app/models/entities.py`

---

## 2. Information Architecture

### Page Layout: Three Columns

```
+------------------+------------------------+----------------+
|    Sidebar        |      Main Content       |   Detail Panel |
|    (240px)        |      (flex: 1)          |   (360px)      |
|    fixed          |      scrollable         |   on-demand    |
+------------------+------------------------+----------------+
```

### Sidebar Groups

**Smart Folders** (system-generated, read-only):
- All Memories (total count)
- Core Memories (pinned=true)
- Temporary Memories (type="temporary")
- Recently Modified (sorted by updated_at)

**Categories** (auto-grouped by memory_kind):
- Profile (个人档案)
- Preference (偏好习惯)
- Goal (目标计划)
- Knowledge (知识观点)
- Episodic (对话片段)

**Subjects** (dynamic, from subject nodes):
- Generated from subject-type memory nodes in the project
- Each shows a count badge

### Four View Modes

1. **Cards** (default) - grid of memory cards
2. **List** - compact single-row list
3. **Graph** - D3 force-directed graph
4. **3D** - Three.js orbit scene

All four views share selection state, search query, and filter criteria.

---

## 3. Visual Design Language

### Colors

| Token | Value | Usage |
|-------|-------|-------|
| brand | `#6f5bff` | buttons, selected state, accent |
| surface | `rgba(255,255,255,0.72)` + `backdrop-filter: blur(40px)` | sidebar, panels |
| background | `#f5f3ff` | page background |
| border | `rgba(128,102,255,0.08~0.14)` | all borders, hierarchy via opacity |
| text-primary | `#2d2546` | headings, card content |
| text-secondary | `#8b7cc8` | labels, metadata |
| text-tertiary | `#a094cc` | counts, timestamps |

### Memory Type Badges

| Type | Background | Text Color |
|------|-----------|------------|
| Permanent | `rgba(111,91,255,0.08)` | `#6f5bff` |
| Temporary | `rgba(59,130,246,0.08)` | `#3b82f6` |
| Pinned/Core | `rgba(245,158,11,0.08)` | `#d97706` |

### Border Radius

- Cards / Panels: `14px`
- Buttons / Badges: `8px`
- Filter pills: `20px`
- Small badges: `6px`

### Animation

- Detail panel slide-in: `0.25s ease`
- Card hover: `translateY(-2px)` + shadow deepen, `0.2s ease`
- View switch: crossfade `0.2s ease`
- All easing: `ease` or `ease-out`, never `linear`

### Icons

- All icons: custom SVG, 18x18, 1.5px stroke, `currentColor`
- No emoji anywhere in the UI
- Navigation icons: unique shape per category (person=profile, heart=preference, target=goal, book=knowledge, bubble=episodic)
- Subject icons: contextual (lightning=physics, cup=food, plane=travel)

### Typography

- System font stack: `-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", system-ui, sans-serif`
- No additional font imports

---

## 4. View Specifications

### 4.1 Card View (Default)

- Grid: `repeat(auto-fill, minmax(280px, 1fr))`, gap `12px`
- Card structure:
  - Category path (11px, secondary color)
  - Type badges (inline, right of category)
  - Content text (13px, 3-line clamp)
  - Meta row: citation count + last used time (11px, tertiary)
- Interactions:
  - Click: select card, open detail panel
  - Hover: `translateY(-2px)`, border-color deepen, shadow increase
  - Multi-select: Cmd/Ctrl+click, toolbar shows bulk actions (delete, export)
- Selected state: brand color border + subtle outer glow

### 4.2 List View

- Single column, compact rows
- Row structure: category badge | content (single-line truncate) | type badge | citation count | time
- Click row: open detail panel (shared with card view)
- Sortable columns: citation count, time, category

### 4.3 Graph View

- D3 force-directed layout (retain core simulation logic from current `MemoryGraph.tsx`)
- Node visual redesign:
  - Center node (assistant): 56px circle, brand gradient `linear-gradient(135deg, #6f5bff, #9770ff)`
  - Category/Subject nodes: 36-40px, individual colors from palette
  - Memory nodes: 20px, color interpolated by retrieval count (light to deep purple)
  - File nodes: 16x20px rectangle
- Edge styling: `rgba(128,102,255,0.15)`, hover highlights to `0.4`
- Click node: opens shared detail panel
- Controls: zoom slider, center button, layout density slider

### 4.4 3D View

- Three.js orbit scene (retain core from `MemoryGraphOrbitScene.tsx`)
- Palette alignment: switch from current warm tones to purple-aligned palette
- Node sizing/coloring: same rules as graph view
- Interaction: drag-rotate, scroll-zoom, click-node opens detail panel

### 4.5 Cross-View Consistency

- `selectedMemoryId` state at page level drives all views
- Search query and filter criteria persist across view switches
- Detail panel open/close state persists across view switches

---

## 5. Detail Panel

### Trigger & Dismiss
- Opens: click any memory (card/row/node)
- Closes: close button or click outside panel
- Animation: slide-in from right, `0.25s ease`

### Content Blocks (top to bottom)

1. **Content** - full text, toggleable read/edit mode
2. **Category** - editable, dropdown or free-text input
3. **Badges** - type (permanent/temporary), core, pinned (read-only display)
4. **Statistics** - citation count, importance score, last used, created_at
5. **Source conversation** - clickable link to original chat
6. **Related memories** - list of linked memories, clickable navigation

### Action Bar (bottom, fixed)
- Edit button
- Promote button (temporary -> permanent)
- Delete button (danger style)

---

## 6. Toolbar & Global Actions

### Toolbar Layout
```
[Title] [Count Badge] ---- [Cards|List|Graph|3D] [+ New Memory]
```

### Filter Bar (below toolbar, cards/list views only)
- Pill-style toggles: All | Permanent | Temporary | Pinned | Summary

### New Memory Dialog
- Lightweight modal/popover
- Fields: content textarea + category dropdown
- Confirm creates via `createMemory()`

### Export/Import
- Export: sidebar or toolbar action, exports current filtered set as JSON
- Import: file upload, calls `createMemory()` for each entry

---

## 7. Data Flow

- **Data source:** `useGraphData(projectId, { includeTemporary: true })` (unchanged)
- **Card/List views:** render `data.nodes`, filtered by sidebar selection + filter bar
- **Graph/3D views:** render `data.nodes` + `data.edges`
- **CRUD:** `createMemory` / `updateMemory` / `deleteMemory` / `promoteMemory` from hook
- **Edge ops:** `createEdge` / `deleteEdge` from hook
- **File ops:** `attachFileToMemory` / `detachFileFromMemory` from hook
- **Selection:** single `selectedMemoryId` state at `page.tsx` level

---

## 8. Sidebar Filtering Logic

- **Smart folders:**
  - "All": no filter
  - "Core": `isPinnedMemoryNode(node) === true`
  - "Temporary": `node.type === "temporary"`
  - "Recently Modified": sort by `updated_at` descending, no filter
- **Categories:** filter by `getMemoryKind(node)` matching selected kind
- **Subjects:** filter by `node.subject_memory_id` matching selected subject node ID

---

## 9. What This Design Does NOT Include

- Backend API changes
- New database fields or migrations
- Mobile/responsive layout (desktop-first, mobile can follow later)
- Keyboard shortcuts beyond existing (can be added incrementally)
- Drag-and-drop reordering in card/list views (future enhancement)
