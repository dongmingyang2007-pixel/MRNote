# Memory Module UI Redesign - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the memory module UI as a three-column "Memory Library" with card/list/graph/3D views, Apple-style design, custom SVG icons, and shared selection state.

**Architecture:** Three-column layout (sidebar 240px + main flex + detail panel 360px) orchestrated by a rewritten `page.tsx`. Four view modes share selection, search, and filter state via a top-level state object. All data flows through the existing `useGraphData` hook unchanged. New components are small, focused files; the monolithic `MemoryGraph.tsx` (4109 lines) receives a visual refresh via CSS and config constants, not a full rewrite.

**Tech Stack:** Next.js 16 (React 18), TypeScript, D3.js (graph), Three.js (3D orbit), Tailwind CSS + custom CSS, framer-motion, next-intl

**Spec:** `docs/superpowers/specs/2026-04-08-memory-module-redesign.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `components/console/memory/MemoryIcons.tsx` | Custom SVG icon components (18x18, 1.5px stroke) |
| `components/console/memory/MemorySidebar.tsx` | Left sidebar: search, smart folders, categories, subjects |
| `components/console/memory/MemoryCardGrid.tsx` | Card view: grid of memory cards with hover/select |
| `components/console/memory/MemoryListTable.tsx` | List view: compact sortable table rows |
| `components/console/memory/MemoryDetailPanel.tsx` | Right panel: content, badges, stats, actions |
| `components/console/memory/MemoryToolbar.tsx` | Top bar: title, view switcher, filter pills, new button |
| `components/console/memory/MemoryNewDialog.tsx` | New memory creation popover |
| `components/console/memory/memory-types.ts` | Shared types, filter logic, sidebar folder definitions |

### Modified Files

| File | Changes |
|------|---------|
| `app/[locale]/workspace/memory/page.tsx` | Full rewrite: three-column layout, state orchestration |
| `components/console/graph/MemoryGraph.tsx` | Visual refresh: new color palette, node styling constants |
| `components/console/graph/MemoryGraphOrbitScene.tsx` | Palette alignment: warm tones -> purple tones |
| `styles/globals.css` (lines 14185-15627) | Replace all `.memory-*` classes with new design system |
| `messages/zh/console.json` | Add new sidebar/card/toolbar translation keys |
| `messages/en/console.json` | Same additions in English |

### Untouched Files

| File | Reason |
|------|--------|
| `hooks/useGraphData.ts` | Data layer unchanged |
| `components/console/graph/NodeDetail.tsx` | Replaced by MemoryDetailPanel, removed from imports |
| `components/console/graph/GraphContextMenu.tsx` | Still used by MemoryGraph internally |
| `components/console/graph/GraphControls.tsx` | Still used by MemoryGraph internally |
| `components/console/graph/GraphFilters.tsx` | Replaced by sidebar filters, kept for graph-specific use |
| `components/console/MemoryListView.tsx` | Replaced by MemoryCardGrid + MemoryListTable, can delete later |

---

## Task 1: Shared Types & Filter Logic

**Files:**
- Create: `apps/web/components/console/memory/memory-types.ts`

- [ ] **Step 1: Create the shared types file**

Contains: `MemoryViewMode`, `SmartFolder`, `SidebarSelection`, `FilterPill`, `MemoryPageState`, `INITIAL_PAGE_STATE`, `SMART_FOLDERS` array, `CATEGORIES` array, `filterNodes()`, `countByFolder()`, `countByKind()`, `countBySubject()`, `extractSubjects()`.

All types and filter functions used by sidebar, toolbar, and page orchestrator. Imports only from `@/hooks/useGraphData`.

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd apps/web && npx tsc --noEmit 2>&1 | grep "error" | head -5`

- [ ] **Step 3: Commit**

```bash
git add apps/web/components/console/memory/memory-types.ts
git commit -m "feat(memory): add shared types, filter logic, and sidebar definitions"
```

---

## Task 2: Custom SVG Icons

**Files:**
- Create: `apps/web/components/console/memory/MemoryIcons.tsx`

- [ ] **Step 1: Create the icon library**

All icons: 18x18 viewBox, 1.5px stroke, `currentColor`, no emoji. Each icon is a named React component returning an `<svg>` element with inline `<path>`/`<circle>`/`<rect>` children.

Icons needed:
- Smart folders: `CircleIcon`, `StarIcon`, `ClockIcon`, `PencilIcon`
- Categories: `PersonIcon`, `HeartIcon`, `TargetIcon`, `BookIcon`, `BubbleIcon`, `LayersIcon`
- Subjects: `LightningIcon`, `CupIcon`, `PlaneIcon`
- Actions: `PlusIcon`, `SearchIcon`, `GridIcon`, `ListIcon`, `GraphIcon`, `SphereIcon`, `CloseIcon`, `ChevronRightIcon`, `ExportIcon`

Plus a `MemoryIcon` lookup component: `<MemoryIcon name="star" />` resolves to the correct component.

- [ ] **Step 2: Verify TypeScript compiles**

- [ ] **Step 3: Commit**

```bash
git add apps/web/components/console/memory/MemoryIcons.tsx
git commit -m "feat(memory): add custom SVG icon library for memory module"
```

---

## Task 3: CSS Design System

**Files:**
- Modify: `apps/web/styles/globals.css` (lines 14185-15627)

- [ ] **Step 1: Replace all `.memory-*` CSS classes with new `.mem-*` classes**

Uses `mem-` prefix to avoid collision during transition. Key class groups:

- `.mem-page` (flex layout, 100% height)
- `.mem-sidebar`, `.mem-sidebar-header`, `.mem-sidebar-nav`, `.mem-sidebar-item` (glassmorphism surface)
- `.mem-main`, `.mem-content` (flex column, scrollable)
- `.mem-toolbar`, `.mem-view-switcher`, `.mem-view-btn` (toolbar with view toggle)
- `.mem-filter-bar`, `.mem-filter-pill` (pill-style toggles)
- `.mem-card-grid`, `.mem-card` (grid + hover/select effects)
- `.mem-list-table`, `.mem-list-row`, `.mem-list-header` (compact table)
- `.mem-detail`, `.mem-detail-header`, `.mem-detail-body`, `.mem-detail-actions` (slide-in panel)
- `.mem-badge` with `.is-permanent`, `.is-temporary`, `.is-pinned`, `.is-summary` variants
- `.mem-new-dialog`, `.mem-dialog-backdrop` (creation popover)
- `.mem-empty-state`, `.mem-loading` (empty/loading states)

Design tokens: brand `#6f5bff`, surface `rgba(255,255,255,0.72)` + blur(40px), bg `#f5f3ff`, text-primary `#2d2546`, text-secondary `#8b7cc8`, text-tertiary `#a094cc`. Cards 14px radius, buttons 8px, pills 20px. Animations 0.2-0.25s ease.

- [ ] **Step 2: Verify page loads without CSS parse errors**

- [ ] **Step 3: Commit**

```bash
git add apps/web/styles/globals.css
git commit -m "feat(memory): add new Memory Library CSS design system"
```

---

## Task 4: Sidebar Component

**Files:**
- Create: `apps/web/components/console/memory/MemorySidebar.tsx`

- [ ] **Step 1: Create the sidebar component**

Props: `nodes`, `assistantName`, `selection`, `search`, `onSelect`, `onSearchChange`. Renders: header (title + search), smart folders section, categories section, subjects section. Each item shows icon + label + count badge. Active state highlights via `is-active` class.

- [ ] **Step 2: Verify TypeScript compiles**

- [ ] **Step 3: Commit**

```bash
git add apps/web/components/console/memory/MemorySidebar.tsx
git commit -m "feat(memory): add sidebar with smart folders, categories, and subjects"
```

---

## Task 5: Memory Card Grid

**Files:**
- Create: `apps/web/components/console/memory/MemoryCardGrid.tsx`

- [ ] **Step 1: Create the card grid component**

Props: `nodes`, `selectedId`, `onSelect`. Renders: CSS grid of cards, each showing category path, type badges, content (3-line clamp), meta row (citation count + relative time). Click selects, hover lifts. Empty state if no nodes.

- [ ] **Step 2: Verify TypeScript compiles**

- [ ] **Step 3: Commit**

```bash
git add apps/web/components/console/memory/MemoryCardGrid.tsx
git commit -m "feat(memory): add card grid view component"
```

---

## Task 6: Memory List Table

**Files:**
- Create: `apps/web/components/console/memory/MemoryListTable.tsx`

- [ ] **Step 1: Create the list table component**

Props: `nodes`, `selectedId`, `onSelect`. Renders: header row with sortable columns (category, content, type, retrieval count, time), data rows. Sort state managed internally. Click selects row.

- [ ] **Step 2: Verify TypeScript compiles**

- [ ] **Step 3: Commit**

```bash
git add apps/web/components/console/memory/MemoryListTable.tsx
git commit -m "feat(memory): add compact sortable list table view"
```

---

## Task 7: Detail Panel

**Files:**
- Create: `apps/web/components/console/memory/MemoryDetailPanel.tsx`

- [ ] **Step 1: Create the detail panel component**

Props: `node`, `allNodes`, `edges`, `onClose`, `onUpdate`, `onDelete`, `onPromote`, `onSelect`. Renders: header with close button, content (read/edit toggle), category (editable), badges, statistics table, source conversation link, related memories list, action bar (edit/promote/delete). Slides in from right with 0.25s ease animation. Click-outside-to-close via mousedown listener.

- [ ] **Step 2: Verify TypeScript compiles**

- [ ] **Step 3: Commit**

```bash
git add apps/web/components/console/memory/MemoryDetailPanel.tsx
git commit -m "feat(memory): add detail panel with edit, promote, delete actions"
```

---

## Task 8: Toolbar & New Memory Dialog

**Files:**
- Create: `apps/web/components/console/memory/MemoryToolbar.tsx`
- Create: `apps/web/components/console/memory/MemoryNewDialog.tsx`

- [ ] **Step 1: Create the toolbar component**

Props: `title`, `count`, `view`, `filter`, `showFilters`, `onViewChange`, `onFilterChange`, `onNewMemory`, `onExport`. Renders: title + count badge, spacer, view switcher (4 icon buttons), export button, primary "new memory" button. Below toolbar: filter pill bar (conditionally shown for cards/list views).

- [ ] **Step 2: Create the new memory dialog**

Props: `open`, `onClose`, `onCreate`. Renders: backdrop + centered dialog with content textarea, category input, cancel/save buttons. Calls `onCreate` on submit.

- [ ] **Step 3: Verify TypeScript compiles**

- [ ] **Step 4: Commit**

```bash
git add apps/web/components/console/memory/MemoryToolbar.tsx apps/web/components/console/memory/MemoryNewDialog.tsx
git commit -m "feat(memory): add toolbar with view switcher, filter pills, and new memory dialog"
```

---

## Task 9: Page Orchestration (Rewrite page.tsx)

**Files:**
- Rewrite: `apps/web/app/[locale]/workspace/memory/page.tsx`

- [ ] **Step 1: Rewrite the page component**

Three-column layout: `<MemorySidebar>` | `<main>` with toolbar + content area | `<MemoryDetailPanel>` (conditional). State: `MemoryPageState` object with view, sidebar, filter, search, selectedId. Renders four views conditionally: cards (MemoryCardGrid), list (MemoryListTable), graph/orbit (MemoryGraph with renderMode prop). All callbacks wired to useGraphData hook.

- [ ] **Step 2: Verify the page loads at http://localhost:3000/app/memory**

- [ ] **Step 3: Commit**

```bash
git add apps/web/app/[locale]/workspace/memory/page.tsx
git commit -m "feat(memory): rewrite memory page with three-column Memory Library layout"
```

---

## Task 10: Graph & Orbit Visual Refresh

**Files:**
- Modify: `apps/web/components/console/graph/MemoryGraph.tsx` (color constants only)
- Modify: `apps/web/components/console/graph/MemoryGraphOrbitScene.tsx` (palette only)

- [ ] **Step 1: Update graph color palette**

In `MemoryGraph.tsx`, find the `COLORS` object (~line 175-186) and replace with purple-aligned palette:
- `permanent: "#6f5bff"`, `temporary: "#3b82f6"`, `core: "#7c5cfc"`, `structure: "#9b8ec4"`, `subject: "#8b6fff"`, `concept: "#a78bfa"`, `summary: "#d97706"`, `file: "#8b7cc8"`, `centerGradStart: "#6f5bff"`, `centerGradEnd: "#9770ff"`

- [ ] **Step 2: Update orbit scene palette**

In `MemoryGraphOrbitScene.tsx`, find `ORBIT_PALETTE` (~line 80-101) and update warm tones to purple:
- `background: "#f5f3ff"`, `fog: "#ede8ff"`, `stage: "#ece6ff"`, `centerNode: "#6f5bff"`, `centerHalo: "#d4c0ff"`, edge colors aligned to brand purples.

- [ ] **Step 3: Verify both views render correctly**

- [ ] **Step 4: Commit**

```bash
git add apps/web/components/console/graph/MemoryGraph.tsx apps/web/components/console/graph/MemoryGraphOrbitScene.tsx
git commit -m "feat(memory): update graph and orbit color palettes to purple design system"
```

---

## Task 11: Translation Keys

**Files:**
- Modify: `apps/web/messages/zh/console.json`
- Modify: `apps/web/messages/en/console.json`

- [ ] **Step 1: Add any missing translation keys**

Review component usage. Add if missing:
- `memory.workspaceTitle`: "智能文件夹" / "Smart Folders"
- `memory.usedCount`: "引用" / "Used"
- `memory.selectToView`: "记忆详情" / "Memory Detail"

- [ ] **Step 2: Verify no missing translation console warnings**

- [ ] **Step 3: Commit**

```bash
git add apps/web/messages/zh/console.json apps/web/messages/en/console.json
git commit -m "feat(memory): add missing translation keys for Memory Library UI"
```

---

## Task 12: Integration Verification & Cleanup

- [ ] **Step 1: Full page walkthrough**

Visit http://localhost:3000/app/memory and verify:
1. Sidebar renders with smart folders, categories, subjects
2. Card view shows memory cards with hover/select effects
3. List view shows sortable rows
4. Clicking a card/row opens detail panel from right
5. Graph view renders with new purple color palette
6. 3D orbit view renders with updated palette
7. Search filters cards in real-time
8. Filter pills work (all/permanent/temporary/pinned/summary)
9. New Memory dialog creates a memory
10. Detail panel edit/save works
11. Detail panel delete works
12. View switching preserves selection state

- [ ] **Step 2: Remove old unused files (optional, can defer)**

Check if `list-preview/page.tsx` still references `MemoryListView.tsx`. If not, mark for deletion.

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat(memory): Memory Library UI redesign complete"
```
