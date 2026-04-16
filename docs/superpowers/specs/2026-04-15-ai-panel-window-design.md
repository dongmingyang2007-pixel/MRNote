# S3 — AI Panel Windowization (Design)

Date: 2026-04-15
Status: Approved for implementation
Scope: Sub-project S3 of the MRAI notebook upgrade (see
`MRAI_notebook_ai_os_build_spec.md` §6.3, §19.4).

## 1. Purpose

Currently the "AI panel" in the notebook workspace is rendered as the
body of a `chat` window type (`contents/ChatWindow.tsx` just wraps
`AIPanel.tsx`). Spec §6.3 requires a dedicated `ai_panel` window type
whose first-class structure is a tabbed page-bound surface
(Ask / Summary / Related / Memory / Study / Trace), with §19.4
explicitly calling out that "多个 AI 窗口（绑定不同页面上下文）" must
be allowed.

S3 promotes the AI panel to a proper window type, adds a tabbed view
with the four tabs whose backends already exist (Ask, Summary, Memory,
Trace), gives users two ways to open it (note title-bar button +
sidebar icon), and persists the whole window layout to localStorage so
refreshing the workspace brings the layout back.

Related and Study tabs are explicitly out of scope — they depend on
backend work scheduled for S7 and S4 respectively.

## 2. Scope

### In scope

- Rename `WindowType` value `"chat"` to `"ai_panel"` across the
  frontend (WindowManager, Window, WindowCanvas, MinimizedTray).
- Delete `contents/ChatWindow.tsx`; add `contents/AIPanelWindow.tsx`
  that renders a tab bar + 4 tab panels.
- Four tabs wired to existing backends:
  - **Ask** — renders the existing `AIPanel.tsx` component
    (notebook AI `/ask` endpoint + retrieval orchestration).
  - **Summary** — calls `/api/v1/ai/notebook/page-action` with
    `action_type="summarize"` and shows the streamed result.
  - **Memory** — calls `/api/v1/pages/{page_id}/memory/links` and
    reuses the existing `MemoryLinksPanel.tsx`.
  - **Trace** — reuses the S1 `AIActionsList.tsx`.
- Two open triggers:
  - Button in the Note window's title bar (Sparkles icon) that
    opens an AI Panel bound to that note's `pageId`.
  - Icon in the notebook sidebar that opens an AI Panel for the
    currently-focused Note window; no-op (with tooltip) if no
    note window is focused.
- Multi-instance: one AI Panel per page, but multiple AI Panels
  (each bound to a different page) may coexist on the canvas.
- localStorage-based layout persistence, keyed per notebook.
- Playwright smoke tests for the four key flows.

### Out of scope (explicit)

- Related and Study tabs.
- Standalone `code` and `canvas` window types.
- Cross-notebook AI panel sharing.
- URL-based shareable layouts.
- Tab-state persistence (refresh always lands on Ask).
- Changes to the Ask backend or AIPanel internals.

## 3. Architecture

```
┌─ NotebookSidebar ───────────────┐
│  [✨ AI]  ─── dispatch ──────┐   │
│                              ▼   │
│  WindowManagerProvider ──── openWindow({type:"ai_panel",meta})
│    ▲                             │
│    │ title-bar button (Sparkles) │
│    │ injected via titlebarExtras │
│    │                             │
│  [Note window]                   │
│                                  │
│  [AI Panel window] ──┐           │
│    ├── Tab bar       │           │
│    └── Active tab    │           │
│         ├── Ask      (AIPanel.tsx)
│         ├── Summary  (existing /page-action)
│         ├── Memory   (MemoryLinksPanel.tsx)
│         └── Trace    (AIActionsList.tsx, S1)
└──────────────────────────────────┘
         │
         ▼
   localStorage
     key: mrai.windows.{notebookId}
     value: { v: 1, windows: [...] }
```

All four tabs operate on a single `pageId` passed from the parent
window's `meta`. The AI Panel window is always opened bound to a page
— it cannot exist without one.

## 4. Component-by-Component Changes

### 4.1 `WindowManager.tsx`

```ts
export type WindowType = "note" | "ai_panel" | "file" | "memory" | "study";
//                                ^^^^^^^^ was "chat"
```

`supportsMultiOpen` becomes `type === "note" || type === "file" ||
type === "ai_panel"`, so multiple AI panels (bound to different pages)
can coexist. De-duplication for existing AI panel windows is handled
by the existing `JSON.stringify(w.meta) === JSON.stringify(meta)` check
in the `OPEN_WINDOW` branch — since multi-open is allowed, duplicate
detection is skipped entirely for `ai_panel`. Opening a second panel
with the same `pageId` creates a second window (user's explicit
choice per brainstorming).

`DEFAULT_SIZES["ai_panel"] = { width: 480, height: 620 }` (taller than
chat was, to accommodate the tab bar).

New responsibility: **layout persistence**. A `notebookId` prop is
added to `WindowManagerProvider`. On mount the provider reads
`localStorage["mrai.windows." + notebookId]`, validates the `v: 1`
envelope, and uses the stored window list as the reducer's initial
state. A `useEffect` watches `windows` and debounces writes (500 ms)
back to the same key.

```tsx
export function WindowManagerProvider({
  children,
  notebookId,
}: { children: ReactNode; notebookId: string }) {
  const [windows, dispatch] = useReducer(
    windowReducer,
    undefined,
    () => loadPersistedLayout(notebookId),   // hydrate once
  );
  useDebouncedPersist(notebookId, windows);  // save on change
  // ... rest unchanged
}
```

Persistence details:
- **Storage key**: `"mrai.windows." + notebookId`.
- **Envelope**: `{ v: 1, windows: WindowState[] }`.
- **Load failures** (JSON parse error, wrong version, missing envelope)
  → return `[]`. Never throw.
- **SSR safety**: `typeof window === "undefined"` → return `[]`
  without touching localStorage.
- **Persist failure** (e.g., quota exceeded) → `console.warn`, don't
  crash the reducer.
- **Version 1** is the only version; future migrations will bump and
  gate on `v`.

### 4.2 `Window.tsx`

- `WINDOW_ICONS["ai_panel"] = Sparkles` (replaces `chat: MessageSquare`).
- New optional prop `titlebarExtras?: React.ReactNode` rendered inside
  the title-bar control cluster, **before** the standard min / max /
  close buttons. This is the extension point that lets note windows
  project an "Open AI Panel" button without coupling `Window.tsx` to
  any specific window type.

```tsx
interface WindowProps {
  windowState: WindowState;
  children: React.ReactNode;
  titlebarExtras?: React.ReactNode;   // NEW
}
```

### 4.3 `WindowCanvas.tsx`

Switches on `windowState.type` to render content. The existing `chat`
branch becomes `ai_panel` and renders `<AIPanelWindow ... />`. For
note windows, it passes a `titlebarExtras` prop to `Window.tsx`
containing the Sparkles button:

```tsx
// Inside WindowCanvas' render loop, for each w in windows:
const extras = w.type === "note" && w.meta.pageId ? (
  <button
    type="button"
    className="wm-titlebar-btn"
    onClick={(e) => {
      e.stopPropagation();
      openWindow({
        type: "ai_panel",
        title: `AI · ${w.title}`,
        meta: { pageId: w.meta.pageId, notebookId },
      });
    }}
    title="Open AI Panel"
    data-testid="note-open-ai-panel"
  >
    <Sparkles size={14} />
  </button>
) : undefined;

return (
  <Window key={w.id} windowState={w} titlebarExtras={extras}>
    {renderContentForWindow(w)}
  </Window>
);
```

`WindowCanvas` already reads `notebookId` from each window's
`meta.notebookId` (see existing `NoteWindow` / `FileWindow` render
branches). The Sparkles handler reuses that same source — no new
prop, no new context.

### 4.4 `MinimizedTray.tsx`

`MinimizedTray.tsx` keeps its own `TRAY_ICONS: Record<WindowType, ...>`
map (it does not share with `Window.tsx`). Update the key from `chat`
to `ai_panel` and swap the `MessageSquare` icon for `Sparkles`. No
other changes.

### 4.5 `contents/AIPanelWindow.tsx` (new, ~130 lines)

```tsx
"use client";

import { useState } from "react";
import AskTab from "./ai-panel-tabs/AskTab";
import SummaryTab from "./ai-panel-tabs/SummaryTab";
import MemoryTab from "./ai-panel-tabs/MemoryTab";
import TraceTab from "./ai-panel-tabs/TraceTab";

type TabKey = "ask" | "summary" | "memory" | "trace";

interface Props {
  notebookId: string;
  pageId: string;
}

const TABS: { key: TabKey; label: string }[] = [
  { key: "ask", label: "Ask" },
  { key: "summary", label: "Summary" },
  { key: "memory", label: "Memory" },
  { key: "trace", label: "Trace" },
];

export default function AIPanelWindow({ notebookId, pageId }: Props) {
  const [tab, setTab] = useState<TabKey>("ask");

  return (
    <div className="ai-panel-window">
      <div className="ai-panel-window__tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            data-testid={`ai-panel-tab-${t.key}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="ai-panel-window__body">
        {tab === "ask" && <AskTab notebookId={notebookId} pageId={pageId} />}
        {tab === "summary" && <SummaryTab pageId={pageId} />}
        {tab === "memory" && <MemoryTab pageId={pageId} />}
        {tab === "trace" && <TraceTab pageId={pageId} />}
      </div>
    </div>
  );
}
```

CSS lives in a new `ai-panel-window.css` imported at the component
top; styles follow the existing `wm-*` family (neutral, minimalist).

### 4.6 Tab components (new)

- **`ai-panel-tabs/AskTab.tsx`** (≈15 lines): thin wrapper that
  renders the existing `AIPanel.tsx` component with `notebookId`,
  `pageId`, and a no-op `onClose` (the parent Window already owns
  close). No changes to `AIPanel.tsx` itself.
- **`ai-panel-tabs/SummaryTab.tsx`** (≈100 lines): a single
  "Generate summary" button; on click, POSTs to
  `/api/v1/ai/notebook/page-action` with
  `{ page_id, action_type: "summarize" }` and streams the SSE
  response into a markdown-rendered area. Re-runnable. Stores the
  last result in local component state (not persisted).
- **`ai-panel-tabs/MemoryTab.tsx`** (≈30 lines): thin wrapper
  that renders the existing `MemoryLinksPanel.tsx` keyed by
  `pageId`. No changes to `MemoryLinksPanel.tsx` itself.
- **`ai-panel-tabs/TraceTab.tsx`** (≈15 lines): thin wrapper that
  renders the existing `AIActionsList.tsx` with `pageId`. No changes
  to `AIActionsList.tsx`.

### 4.7 `NotebookSidebar.tsx`

Adds a new sidebar icon (Sparkles, labeled "AI") in the nav-tab group,
positioned **immediately after** the existing "Memory" icon and
before the sidebar settings section. Uses the sidebar's existing
`<button className="notebook-sidebar-nav-btn">` pattern — no new
styling rules. Click handler:

```tsx
const handleOpenAIPanel = () => {
  // Find the focused note window (highest zIndex, type === "note")
  const focusedNote = [...windows]
    .filter((w) => w.type === "note" && !w.minimized && w.meta.pageId)
    .sort((a, b) => b.zIndex - a.zIndex)[0];

  if (!focusedNote) {
    // UI feedback: a small tooltip banner. For S3 we use alert() as a
    // placeholder — upgrade to a toast system later.
    console.warn("ai-panel: no focused note window; open a page first");
    return;
  }
  openWindow({
    type: "ai_panel",
    title: `AI · ${focusedNote.title}`,
    meta: {
      pageId: focusedNote.meta.pageId,
      notebookId: focusedNote.meta.notebookId,
    },
  });
};
```

### 4.8 `NoteEditor.tsx`

Remove the S1 Trace footer (`<details>` block inside the return
JSX) and the `AIActionsList` import. Trace now lives in the AI
Panel window, not inline with the editor.

## 5. Error / Boundary Handling

- **Orphaned AI panel** (its `pageId` was deleted): each tab
  surfaces the backend's 404. Ask and Summary render an inline
  error; Memory and Trace render an empty list with a "Page no
  longer exists" hint.
- **Sidebar click without a focused note**: no-op + `console.warn`
  for S3 (see §4.7). A proper toast belongs to a later UX polish
  sub-project.
- **localStorage quota exceeded**: the debounced persist helper
  catches `DOMException`, logs once per session, and continues with
  in-memory state.
- **Multiple AI Panels on the same page**: allowed by design
  (spec §19.4). The cascade offset in `WindowManager`'s
  `cascadePosition` already handles overlapping placement.
- **Stream interrupted by window close**: Ask tab's internal
  `apiStream` helper owns the AbortController. Closing the window
  unmounts the tab, which aborts the fetch. No special plumbing.

## 6. Testing Strategy

Target ≥80% behavioral coverage on the new/changed units.

### 6.1 Unit — `apps/web/tests/unit/window-persistence.test.ts`

Runs under `vitest` (add to `apps/web/package.json` devDeps if not
present). Exercises the pure persistence helpers extracted from
`WindowManager.tsx`:

| # | Case | Asserts |
|---|---|---|
| 1 | `loadPersistedLayout("nb1")` with no entry → `[]` | returns empty |
| 2 | round-trip save / load → equal | windows array restored |
| 3 | malformed JSON in storage → `[]` | no throw |
| 4 | wrong `v` field → `[]` | no throw |
| 5 | save during SSR (`window` undefined) → no-op | no throw |
| 6 | save with quota error → swallow | no throw |

### 6.2 Playwright — `apps/web/tests/s3-ai-panel.spec.ts`

Backend is stubbed at the network layer where needed (`page.route`).

| # | Flow | Asserts |
|---|---|---|
| 1 | Open notebook → click Sparkles in note title-bar → AI Panel window appears with Ask tab active | new window visible, tab-ask is selected |
| 2 | Open two notes, open AI Panel from each → two AI Panel windows coexist | count = 2, titles reference respective pages |
| 3 | Click Summary tab → request fires → result area populated | request seen, result text non-empty |
| 4 | Click Memory tab → GET /pages/{id}/memory/links request fires | request seen |
| 5 | Click Trace tab → AIActionsList renders | `ai-actions-list` testid visible |
| 6 | Open AI Panel, resize, refresh page → window state restored from localStorage | size / position preserved |
| 7 | Click sidebar AI icon with no focused note → nothing opens, warning logged | window count unchanged |

### 6.3 Regression guards

- The existing `tests/notebook-ai-trace.spec.ts` smoke test from S1
  updates to navigate through the new Trace tab instead of the
  inline footer.
- No Python tests change for S3 (pure frontend work).

## 7. File Plan

### New files

- `apps/web/components/notebook/contents/AIPanelWindow.tsx`
- `apps/web/components/notebook/contents/ai-panel-tabs/AskTab.tsx`
- `apps/web/components/notebook/contents/ai-panel-tabs/SummaryTab.tsx`
- `apps/web/components/notebook/contents/ai-panel-tabs/MemoryTab.tsx`
- `apps/web/components/notebook/contents/ai-panel-tabs/TraceTab.tsx`
- `apps/web/components/notebook/window-persistence.ts` (pure helpers,
  unit-testable without React)
- `apps/web/styles/ai-panel-window.css`
- `apps/web/tests/unit/window-persistence.test.ts`
- `apps/web/tests/s3-ai-panel.spec.ts`

### Modified files

- `apps/web/components/notebook/WindowManager.tsx`
- `apps/web/components/notebook/Window.tsx`
- `apps/web/components/notebook/WindowCanvas.tsx`
- `apps/web/components/notebook/MinimizedTray.tsx`
- `apps/web/components/console/NotebookSidebar.tsx`
- `apps/web/components/console/editor/NoteEditor.tsx`
- `apps/web/tests/notebook-ai-trace.spec.ts` (S1 smoke regression-guard)
- `apps/web/package.json` (if vitest not already present)

### Deleted files

- `apps/web/components/notebook/contents/ChatWindow.tsx`

## 8. Persistence Schema

```ts
// apps/web/components/notebook/window-persistence.ts

export const STORAGE_KEY_PREFIX = "mrai.windows.";
export const CURRENT_SCHEMA_VERSION = 1 as const;

interface PersistedLayoutV1 {
  v: 1;
  windows: WindowState[];
}

export function loadPersistedLayout(notebookId: string): WindowState[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY_PREFIX + notebookId);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (
      !parsed ||
      typeof parsed !== "object" ||
      (parsed as { v?: unknown }).v !== CURRENT_SCHEMA_VERSION ||
      !Array.isArray((parsed as { windows?: unknown }).windows)
    ) {
      return [];
    }
    return (parsed as PersistedLayoutV1).windows;
  } catch {
    return [];
  }
}

export function savePersistedLayout(
  notebookId: string,
  windows: WindowState[],
): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      STORAGE_KEY_PREFIX + notebookId,
      JSON.stringify({ v: CURRENT_SCHEMA_VERSION, windows }),
    );
  } catch (err) {
    console.warn("window-persistence: save failed", err);
  }
}
```

## 9. Acceptance Criteria

- `WindowType` no longer includes `"chat"`; grep returns zero hits
  under `apps/web/components/notebook/`.
- Opening a notebook with no prior state shows an empty canvas.
- Clicking the Sparkles button in a note title-bar opens an AI Panel
  bound to that note's `pageId`. The default tab is Ask.
- Two different notes → two independent AI Panels on the canvas.
- Refreshing the page after arranging windows restores their
  positions and sizes.
- Memory tab shows the same data as the legacy
  `MemoryLinksPanel.tsx` does today.
- Trace tab shows the same data as the S1 `AIActionsList.tsx` does
  today.
- All tests pass: `pnpm playwright test tests/s3-ai-panel.spec.ts`
  (once the dev stack is running) and `pnpm vitest run
  tests/unit/window-persistence.test.ts`.
- No regressions in the S1 `notebook-ai-trace.spec.ts` smoke test
  (it is updated to route through the new Trace tab).

## 10. Non-goals Re-stated

Chat vs. AI Panel confusion is ended by having exactly one window
type (`ai_panel`) for page-bound AI. If the workspace ever needs a
standalone ChatGPT-style conversation surface again, it belongs in
the existing `/workspace/chat` route, not in the notebook canvas.
`code` and `canvas` windows remain deferred.
