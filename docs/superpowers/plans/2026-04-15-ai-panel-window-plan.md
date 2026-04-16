# S3 — AI Panel Windowization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the notebook `chat` window type to `ai_panel`, give
it a tabbed layout (Ask / Summary / Memory / Trace), add two open
triggers (note title-bar button + sidebar icon), and persist the
window layout per notebook to `localStorage`.

**Architecture:** The AI Panel is a proper `WindowType` with its own
content component (`AIPanelWindow`) that hosts four tab components
backed by existing APIs. Open triggers dispatch `openWindow({ type:
"ai_panel", meta: { pageId, notebookId } })` through the existing
`WindowManager`. Layout persistence is a pair of pure helpers
(`loadPersistedLayout` / `savePersistedLayout`) consumed by
`WindowManagerProvider` — hydrated as the reducer's initial state and
written back with a 500 ms debounce.

**Tech Stack:** Next.js 14 (app router), React 18, TypeScript,
Tiptap, react-rnd (already in use), vitest (new dev-dep), Playwright
(existing).

**Spec:** `docs/superpowers/specs/2026-04-15-ai-panel-window-design.md`

---

## Phase Overview

| # | Phase | Scope |
|---|---|---|
| A | Persistence helpers + vitest | `window-persistence.ts` + 6 unit tests |
| B | Rename `chat` → `ai_panel` across WindowManager / Window / WindowCanvas / MinimizedTray (deletes ChatWindow) |
| C | `AIPanelWindow` shell + 4 tab components |
| D | Open triggers: note title-bar Sparkles + sidebar AI icon |
| E | Wire persistence into `WindowManagerProvider` |
| F | NoteEditor cleanup + i18n string updates + Playwright smoke tests |

---

### Task 1: Add vitest dev-dependency and npm script

**Files:**
- Modify: `apps/web/package.json`

- [ ] **Step 1: Install vitest + jsdom**

```bash
cd apps/web
pnpm add -D vitest@^1.6.0 jsdom@^24.0.0 @vitest/ui@^1.6.0
```

Expected: `package.json` devDependencies gains `vitest`, `jsdom`,
`@vitest/ui`; `pnpm-lock.yaml` updates.

- [ ] **Step 2: Add test script**

Edit `apps/web/package.json` and change the `"scripts"` block to:

```json
  "scripts": {
    "dev": "next dev --webpack -p 3000",
    "build": "next build --webpack",
    "start": "node server.mjs",
    "lint": "eslint .",
    "e2e": "playwright test",
    "test:unit": "vitest run",
    "test:unit:watch": "vitest"
  },
```

- [ ] **Step 3: Create minimal vitest config**

Create `apps/web/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["tests/unit/**/*.test.ts", "tests/unit/**/*.test.tsx"],
    globals: false,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
```

- [ ] **Step 4: Verify vitest runs (no tests yet)**

Run: `cd apps/web && pnpm test:unit`
Expected: `No test files found` (exit 0 or non-error). If it errors on
config, fix the path alias. Ignore the "no tests" warning.

- [ ] **Step 5: Commit**

```bash
git add apps/web/package.json apps/web/pnpm-lock.yaml apps/web/vitest.config.ts
git commit -m "chore(web): add vitest for S3 unit tests"
```

---

### Task 2: Create window-persistence helpers and unit tests

**Files:**
- Create: `apps/web/components/notebook/window-persistence.ts`
- Create: `apps/web/tests/unit/window-persistence.test.ts`

- [ ] **Step 1: Write the failing test**

Create `apps/web/tests/unit/window-persistence.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  CURRENT_SCHEMA_VERSION,
  STORAGE_KEY_PREFIX,
  loadPersistedLayout,
  savePersistedLayout,
} from "@/components/notebook/window-persistence";
import type { WindowState } from "@/components/notebook/WindowManager";

const SAMPLE: WindowState[] = [
  {
    id: "w1",
    type: "note",
    title: "t",
    x: 10,
    y: 20,
    width: 780,
    height: 600,
    zIndex: 1,
    minimized: false,
    maximized: false,
    meta: { pageId: "p1", notebookId: "nb1" },
  },
];

beforeEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("window-persistence", () => {
  it("loadPersistedLayout returns [] when nothing is stored", () => {
    expect(loadPersistedLayout("nb1")).toEqual([]);
  });

  it("roundtrips save → load", () => {
    savePersistedLayout("nb1", SAMPLE);
    expect(loadPersistedLayout("nb1")).toEqual(SAMPLE);
  });

  it("loadPersistedLayout returns [] on malformed JSON", () => {
    window.localStorage.setItem(STORAGE_KEY_PREFIX + "nb1", "not-json");
    expect(loadPersistedLayout("nb1")).toEqual([]);
  });

  it("loadPersistedLayout returns [] when schema version does not match", () => {
    window.localStorage.setItem(
      STORAGE_KEY_PREFIX + "nb1",
      JSON.stringify({ v: 99, windows: SAMPLE }),
    );
    expect(loadPersistedLayout("nb1")).toEqual([]);
  });

  it("loadPersistedLayout returns [] when windows is not an array", () => {
    window.localStorage.setItem(
      STORAGE_KEY_PREFIX + "nb1",
      JSON.stringify({ v: CURRENT_SCHEMA_VERSION, windows: "bogus" }),
    );
    expect(loadPersistedLayout("nb1")).toEqual([]);
  });

  it("savePersistedLayout swallows localStorage quota errors", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const setItem = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new DOMException("quota", "QuotaExceededError");
      });
    expect(() => savePersistedLayout("nb1", SAMPLE)).not.toThrow();
    expect(warn).toHaveBeenCalled();
    setItem.mockRestore();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/web && pnpm test:unit`
Expected: FAIL — cannot resolve `@/components/notebook/window-persistence`.

- [ ] **Step 3: Create the helper module**

Create `apps/web/components/notebook/window-persistence.ts`:

```ts
import type { WindowState } from "./WindowManager";

export const STORAGE_KEY_PREFIX = "mrai.windows.";
export const CURRENT_SCHEMA_VERSION = 1 as const;

interface PersistedLayout {
  v: typeof CURRENT_SCHEMA_VERSION;
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
    return (parsed as PersistedLayout).windows;
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

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/web && pnpm test:unit`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/notebook/window-persistence.ts apps/web/tests/unit/window-persistence.test.ts
git commit -m "feat(web): window-persistence helpers + vitest coverage"
```

---

### Task 3: Rename WindowType "chat" → "ai_panel" in WindowManager

**Files:**
- Modify: `apps/web/components/notebook/WindowManager.tsx`

- [ ] **Step 1: Update the `WindowType` union**

Open `apps/web/components/notebook/WindowManager.tsx`. Line 16:

```ts
export type WindowType = "note" | "chat" | "file" | "memory" | "study";
```

Replace with:

```ts
export type WindowType = "note" | "ai_panel" | "file" | "memory" | "study";
```

- [ ] **Step 2: Update the `DEFAULT_SIZES` map**

Still in `WindowManager.tsx`, find the `DEFAULT_SIZES` block (starts
at line 56). Replace the `chat` row:

```ts
const DEFAULT_SIZES: Record<WindowType, { width: number; height: number }> = {
  note: { width: 780, height: 600 },
  chat: { width: 420, height: 550 },
  file: { width: 700, height: 500 },
  memory: { width: 500, height: 600 },
  study: { width: 600, height: 500 },
};
```

Replace with:

```ts
const DEFAULT_SIZES: Record<WindowType, { width: number; height: number }> = {
  note: { width: 780, height: 600 },
  ai_panel: { width: 480, height: 620 },
  file: { width: 700, height: 500 },
  memory: { width: 500, height: 600 },
  study: { width: 600, height: 500 },
};
```

- [ ] **Step 3: Update `supportsMultiOpen`**

Inside the `OPEN_WINDOW` case in `windowReducer`. Find line 99:

```ts
const supportsMultiOpen = type === "note" || type === "file";
```

Replace with:

```ts
const supportsMultiOpen =
  type === "note" || type === "file" || type === "ai_panel";
```

- [ ] **Step 4: Typecheck**

Run: `cd apps/web && pnpm lint 2>&1 | head -20`
Expected: no errors from WindowManager.tsx (other files will still
reference `chat` — that's next). Don't fix them yet.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/notebook/WindowManager.tsx
git commit -m "refactor(web): rename WindowType chat → ai_panel in WindowManager"
```

---

### Task 4: Update Window.tsx icon + add titlebarExtras prop

**Files:**
- Modify: `apps/web/components/notebook/Window.tsx`

- [ ] **Step 1: Update imports + icon map**

Open `apps/web/components/notebook/Window.tsx`. Line 5–15:

```ts
import {
  Minus,
  Square,
  Maximize2,
  X,
  FileText,
  MessageSquare,
  FileUp,
  Brain,
  BookOpen,
} from "lucide-react";
```

Replace with:

```ts
import {
  Minus,
  Square,
  Maximize2,
  X,
  FileText,
  Sparkles,
  FileUp,
  Brain,
  BookOpen,
} from "lucide-react";
```

Then the `WINDOW_ICONS` map at line 23–29:

```ts
const WINDOW_ICONS: Record<WindowType, typeof FileText> = {
  note: FileText,
  chat: MessageSquare,
  file: FileUp,
  memory: Brain,
  study: BookOpen,
};
```

Replace with:

```ts
const WINDOW_ICONS: Record<WindowType, typeof FileText> = {
  note: FileText,
  ai_panel: Sparkles,
  file: FileUp,
  memory: Brain,
  study: BookOpen,
};
```

- [ ] **Step 2: Add titlebarExtras prop**

In the `WindowProps` interface (line 35–38):

```ts
interface WindowProps {
  windowState: WindowState;
  children: React.ReactNode;
}
```

Replace with:

```ts
interface WindowProps {
  windowState: WindowState;
  children: React.ReactNode;
  titlebarExtras?: React.ReactNode;
}
```

Update the component signature (line 44):

```ts
export default function Window({ windowState, children }: WindowProps) {
```

Replace with:

```ts
export default function Window({
  windowState,
  children,
  titlebarExtras,
}: WindowProps) {
```

- [ ] **Step 3: Render extras in title-bar controls**

Find the title-bar controls cluster (line 139–164), currently:

```tsx
          <div className="wm-titlebar-controls">
            <button
              type="button"
              className="wm-titlebar-btn"
              onClick={handleMinimize}
              title="Minimize"
            >
              <Minus size={14} />
            </button>
            ...
```

Change to:

```tsx
          <div className="wm-titlebar-controls">
            {titlebarExtras}
            <button
              type="button"
              className="wm-titlebar-btn"
              onClick={handleMinimize}
              title="Minimize"
            >
              <Minus size={14} />
            </button>
            ...
```

(Leave the rest of the controls cluster intact — just add the
`{titlebarExtras}` line before the first button.)

- [ ] **Step 4: Typecheck**

Run: `cd apps/web && pnpm tsc --noEmit 2>&1 | grep -i "window.tsx\|WindowManager" | head -20`
Expected: no errors from these two files.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/notebook/Window.tsx
git commit -m "refactor(web): Window icon map + titlebarExtras prop for injected controls"
```

---

### Task 5: Update MinimizedTray icon map

**Files:**
- Modify: `apps/web/components/notebook/MinimizedTray.tsx`

- [ ] **Step 1: Swap the icon**

Open `apps/web/components/notebook/MinimizedTray.tsx`. Lines 3–9:

```tsx
import {
  FileText,
  MessageSquare,
  FileUp,
  Brain,
  BookOpen,
} from "lucide-react";
```

Replace with:

```tsx
import {
  FileText,
  Sparkles,
  FileUp,
  Brain,
  BookOpen,
} from "lucide-react";
```

Then `TRAY_ICONS` (lines 17–23):

```tsx
const TRAY_ICONS: Record<WindowType, typeof FileText> = {
  note: FileText,
  chat: MessageSquare,
  file: FileUp,
  memory: Brain,
  study: BookOpen,
};
```

Replace with:

```tsx
const TRAY_ICONS: Record<WindowType, typeof FileText> = {
  note: FileText,
  ai_panel: Sparkles,
  file: FileUp,
  memory: Brain,
  study: BookOpen,
};
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/components/notebook/MinimizedTray.tsx
git commit -m "refactor(web): MinimizedTray uses Sparkles for ai_panel"
```

---

### Task 6: Create the four tab components

**Files:**
- Create: `apps/web/components/notebook/contents/ai-panel-tabs/AskTab.tsx`
- Create: `apps/web/components/notebook/contents/ai-panel-tabs/SummaryTab.tsx`
- Create: `apps/web/components/notebook/contents/ai-panel-tabs/MemoryTab.tsx`
- Create: `apps/web/components/notebook/contents/ai-panel-tabs/TraceTab.tsx`

- [ ] **Step 1: Create AskTab.tsx**

```tsx
"use client";

import { useCallback } from "react";
import AIPanel from "@/components/console/editor/AIPanel";

interface AskTabProps {
  notebookId: string;
  pageId: string;
}

export default function AskTab({ notebookId, pageId }: AskTabProps) {
  // The Window shell already handles close; onClose is a no-op here.
  const noop = useCallback(() => {}, []);

  return (
    <div style={{ height: "100%", overflow: "auto" }}>
      <AIPanel
        notebookId={notebookId}
        pageId={pageId}
        onClose={noop}
      />
    </div>
  );
}
```

- [ ] **Step 2: Create TraceTab.tsx**

```tsx
"use client";

import AIActionsList from "@/components/notebook/AIActionsList";

interface TraceTabProps {
  pageId: string;
}

export default function TraceTab({ pageId }: TraceTabProps) {
  return <AIActionsList pageId={pageId} />;
}
```

- [ ] **Step 3: Create MemoryTab.tsx**

```tsx
"use client";

import MemoryLinksPanel from "@/components/console/editor/MemoryLinksPanel";

interface MemoryTabProps {
  pageId: string;
}

export default function MemoryTab({ pageId }: MemoryTabProps) {
  return <MemoryLinksPanel pageId={pageId} embedded />;
}
```

- [ ] **Step 4: Create SummaryTab.tsx**

```tsx
"use client";

import { useCallback, useState } from "react";
import { Sparkles, Loader2 } from "lucide-react";
import { apiStream } from "@/lib/api-stream";

interface SummaryTabProps {
  pageId: string;
}

export default function SummaryTab({ pageId }: SummaryTabProps) {
  const [summary, setSummary] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = useCallback(async () => {
    if (streaming) return;
    setStreaming(true);
    setError(null);
    setSummary("");
    try {
      let acc = "";
      for await (const event of apiStream("/api/v1/ai/notebook/page-action", {
        page_id: pageId,
        action_type: "summarize",
      })) {
        if (event.event === "token") {
          const tok = (event.data as { content?: string }).content || "";
          acc += tok;
          setSummary(acc);
        } else if (event.event === "error") {
          setError(
            (event.data as { message?: string }).message || "Summary failed",
          );
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Summary failed");
    } finally {
      setStreaming(false);
    }
  }, [pageId, streaming]);

  return (
    <div data-testid="ai-panel-summary" style={{ padding: 12 }}>
      <button
        type="button"
        onClick={handleGenerate}
        disabled={streaming}
        data-testid="ai-panel-summary-generate"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          padding: "6px 12px",
          borderRadius: 8,
          border: "1px solid #e5e7eb",
          background: streaming ? "#f3f4f6" : "#ffffff",
          cursor: streaming ? "wait" : "pointer",
          fontSize: 12,
          fontWeight: 600,
        }}
      >
        {streaming ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
        {streaming ? "Generating…" : "Generate summary"}
      </button>
      {error && (
        <p style={{ marginTop: 12, fontSize: 12, color: "#b91c1c" }}>{error}</p>
      )}
      {summary && (
        <div
          data-testid="ai-panel-summary-output"
          style={{
            marginTop: 12,
            padding: 12,
            borderRadius: 8,
            background: "#f9fafb",
            border: "1px solid #e5e7eb",
            fontSize: 13,
            lineHeight: 1.55,
            whiteSpace: "pre-wrap",
          }}
        >
          {summary}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Typecheck**

Run: `cd apps/web && pnpm tsc --noEmit 2>&1 | grep -i "ai-panel-tabs" | head -20`
Expected: no errors in the four new files. Look up the real signature
of `apiStream` in `apps/web/lib/api-stream.ts` and adjust the shape of
`event.event` / `event.data` if different — the two patterns we use
(`"token"` with `content` and `"error"` with `message`) must match
how the S1 wiring yields SSE events.

- [ ] **Step 6: Commit**

```bash
git add apps/web/components/notebook/contents/ai-panel-tabs
git commit -m "feat(web): four AI-panel tab components"
```

---

### Task 7: Create AIPanelWindow shell + CSS

**Files:**
- Create: `apps/web/components/notebook/contents/AIPanelWindow.tsx`
- Create: `apps/web/styles/ai-panel-window.css`
- Modify: `apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx` (import the new CSS)

- [ ] **Step 1: Create the CSS file**

```css
.ai-panel-window {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #ffffff;
}

.ai-panel-window__tabs {
  display: flex;
  gap: 2px;
  padding: 6px 8px 0;
  border-bottom: 1px solid #e5e7eb;
  flex-shrink: 0;
}

.ai-panel-window__tabs button {
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 500;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  color: #6b7280;
}

.ai-panel-window__tabs button[aria-selected="true"] {
  color: #111827;
  border-bottom-color: #2563eb;
  font-weight: 600;
}

.ai-panel-window__body {
  flex: 1;
  overflow: auto;
  min-height: 0;
}
```

- [ ] **Step 2: Create AIPanelWindow.tsx**

```tsx
"use client";

import { useState } from "react";
import AskTab from "./ai-panel-tabs/AskTab";
import SummaryTab from "./ai-panel-tabs/SummaryTab";
import MemoryTab from "./ai-panel-tabs/MemoryTab";
import TraceTab from "./ai-panel-tabs/TraceTab";

type TabKey = "ask" | "summary" | "memory" | "trace";

interface AIPanelWindowProps {
  notebookId: string;
  pageId: string;
}

const TABS: { key: TabKey; label: string }[] = [
  { key: "ask", label: "Ask" },
  { key: "summary", label: "Summary" },
  { key: "memory", label: "Memory" },
  { key: "trace", label: "Trace" },
];

export default function AIPanelWindow({
  notebookId,
  pageId,
}: AIPanelWindowProps) {
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
        {tab === "ask" && (
          <AskTab notebookId={notebookId} pageId={pageId} />
        )}
        {tab === "summary" && <SummaryTab pageId={pageId} />}
        {tab === "memory" && <MemoryTab pageId={pageId} />}
        {tab === "trace" && <TraceTab pageId={pageId} />}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Import the CSS globally in the notebook layout**

Open `apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx`.
Locate the existing CSS imports near the top. Add (alphabetical):

```tsx
import "@/styles/ai-panel-window.css";
```

- [ ] **Step 4: Typecheck**

Run: `cd apps/web && pnpm tsc --noEmit 2>&1 | grep -i "AIPanelWindow\|ai-panel-window" | head -10`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/notebook/contents/AIPanelWindow.tsx apps/web/styles/ai-panel-window.css apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx
git commit -m "feat(web): AIPanelWindow shell with Ask/Summary/Memory/Trace tabs"
```

---

### Task 8: Delete ChatWindow and update WindowCanvas dispatch

**Files:**
- Delete: `apps/web/components/notebook/contents/ChatWindow.tsx`
- Modify: `apps/web/components/notebook/WindowCanvas.tsx`

- [ ] **Step 1: Replace WindowCanvas.tsx**

Overwrite `apps/web/components/notebook/WindowCanvas.tsx` with:

```tsx
"use client";

import { useCallback, useRef } from "react";
import { Layers, Sparkles } from "lucide-react";
import { useWindowManager, useWindows } from "./WindowManager";
import Window from "./Window";
import NoteWindow from "./contents/NoteWindow";
import AIPanelWindow from "./contents/AIPanelWindow";
import FileWindow from "./contents/FileWindow";
import MemoryWindow from "./contents/MemoryWindow";
import StudyWindow from "./contents/StudyWindow";
import type { WindowState } from "./WindowManager";

// ---------------------------------------------------------------------------
// Window content router
// ---------------------------------------------------------------------------

function WindowContent({ windowState }: { windowState: WindowState }) {
  switch (windowState.type) {
    case "note":
      return <NoteWindow pageId={windowState.meta.pageId || ""} />;

    case "ai_panel":
      return (
        <AIPanelWindow
          notebookId={windowState.meta.notebookId || ""}
          pageId={windowState.meta.pageId || ""}
        />
      );

    case "file":
      return (
        <FileWindow
          url={windowState.meta.url}
          mimeType={windowState.meta.mimeType}
          filename={windowState.meta.filename}
        />
      );

    case "memory":
      return (
        <MemoryWindow
          notebookId={windowState.meta.notebookId || ""}
          initialPageId={windowState.meta.pageId}
        />
      );

    case "study":
      return (
        <StudyWindow notebookId={windowState.meta.notebookId || ""} />
      );

    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState() {
  return (
    <div className="wm-empty-state">
      <Layers size={48} strokeWidth={1.2} className="wm-empty-state-icon" />
      <span className="wm-empty-state-text">打开侧栏中的页面开始工作</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Canvas
// ---------------------------------------------------------------------------

export default function WindowCanvas() {
  const canvasRef = useRef<HTMLDivElement>(null);
  const windows = useWindows();
  const { openWindow } = useWindowManager();
  const visibleWindows = windows.filter((w) => !w.minimized);

  const buildNoteExtras = useCallback(
    (w: WindowState) => {
      if (w.type !== "note" || !w.meta.pageId) return undefined;
      return (
        <button
          type="button"
          className="wm-titlebar-btn"
          onClick={(e) => {
            e.stopPropagation();
            openWindow({
              type: "ai_panel",
              title: `AI · ${w.title}`,
              meta: {
                pageId: w.meta.pageId || "",
                notebookId: w.meta.notebookId || "",
              },
            });
          }}
          title="Open AI Panel"
          data-testid="note-open-ai-panel"
        >
          <Sparkles size={14} />
        </button>
      );
    },
    [openWindow],
  );

  return (
    <div ref={canvasRef} className="wm-canvas">
      {visibleWindows.map((w) => (
        <Window
          key={w.id}
          windowState={w}
          titlebarExtras={buildNoteExtras(w)}
        >
          <WindowContent windowState={w} />
        </Window>
      ))}

      {visibleWindows.length === 0 && <EmptyState />}
    </div>
  );
}
```

- [ ] **Step 2: Delete ChatWindow.tsx**

```bash
rm apps/web/components/notebook/contents/ChatWindow.tsx
```

- [ ] **Step 3: Grep for leftover references**

Run: `cd apps/web && grep -rn "type: \"chat\"\|ChatWindow\|ai_chat_window\|WindowType.*chat" --include="*.tsx" --include="*.ts" components lib app tests`
Expected output: one hit in `components/console/NotebookSidebar.tsx`
line ~63 (will be fixed in Task 9). No other hits.

- [ ] **Step 4: Typecheck**

Run: `cd apps/web && pnpm tsc --noEmit 2>&1 | grep -i "WindowCanvas\|ChatWindow" | head -10`
Expected: no errors from WindowCanvas; possibly one from
NotebookSidebar.tsx referencing `type: "chat"` (fixed next).

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/notebook/WindowCanvas.tsx apps/web/components/notebook/contents/ChatWindow.tsx
git commit -m "refactor(web): WindowCanvas dispatches ai_panel, deletes ChatWindow"
```

---

### Task 9: Add AI icon to NotebookSidebar and update chat→ai_panel

**Files:**
- Modify: `apps/web/components/console/NotebookSidebar.tsx`
- Modify: `apps/web/messages/en/console-notebooks.json`
- Modify: `apps/web/messages/zh/console-notebooks.json`

- [ ] **Step 1: Update en locale strings**

Edit `apps/web/messages/en/console-notebooks.json`. Replace the
existing line

```json
  "sidebar.openChat": "Open AI Chat",
```

with

```json
  "sidebar.openAIPanel": "Open AI Panel",
  "sidebar.openAIPanelNeedsPage": "Open a page first",
```

- [ ] **Step 2: Update zh locale strings**

Apply equivalent changes to
`apps/web/messages/zh/console-notebooks.json`:

Replace `"sidebar.openChat"` with:

```json
  "sidebar.openAIPanel": "打开 AI 面板",
  "sidebar.openAIPanelNeedsPage": "请先打开一个页面",
```

(If `"sidebar.openChat"` does not exist in the zh file, add the two
keys anyway.)

- [ ] **Step 3: Rewrite NotebookSidebar.tsx**

Overwrite `apps/web/components/console/NotebookSidebar.tsx` with:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  ArrowLeft,
  FileText,
  Sparkles,
  Brain,
  BookOpen,
  Settings,
} from "lucide-react";
import { apiGet } from "@/lib/api";
import { useWindowManager, useWindows } from "@/components/notebook/WindowManager";
import MinimizedTray from "@/components/notebook/MinimizedTray";

type SideTab = "pages" | "ai_panel" | "memory" | "learn" | null;

interface NotebookSidebarProps {
  notebookId: string;
}

const TABS = [
  { id: "pages" as const, Icon: FileText, key: "nav.pages" },
  { id: "ai_panel" as const, Icon: Sparkles, key: "nav.aiPanel" },
  { id: "memory" as const, Icon: Brain, key: "nav.memory" },
  { id: "learn" as const, Icon: BookOpen, key: "nav.learn" },
] as const;

export default function NotebookSidebar({ notebookId }: NotebookSidebarProps) {
  const pathname = usePathname();
  const t = useTranslations("console");
  const tn = useTranslations("console-notebooks");
  const [activeTab, setActiveTab] = useState<SideTab>("pages");
  const [pages, setPages] = useState<
    Array<{ id: string; title: string; page_type: string }>
  >([]);

  useEffect(() => {
    void apiGet<{
      items: Array<{ id: string; title: string; page_type: string }>;
    }>(`/api/v1/notebooks/${notebookId}/pages`)
      .then((data) => setPages(data.items || []))
      .catch(() => setPages([]));
  }, [notebookId]);

  const basePath = `/app/notebooks/${notebookId}`;

  const isRouteActive = (tabId: string) => {
    if (tabId === "pages") {
      return (
        pathname === basePath ||
        pathname.endsWith(`/notebooks/${notebookId}`) ||
        pathname.includes(`/notebooks/${notebookId}/pages/`)
      );
    }
    if (tabId === "memory")
      return pathname.includes(`/notebooks/${notebookId}/memory`);
    if (tabId === "learn")
      return pathname.includes(`/notebooks/${notebookId}/learn`);
    return false;
  };

  const { openWindow } = useWindowManager();
  const windows = useWindows();

  const handleTabClick = useCallback(
    (tabId: SideTab) => {
      if (tabId === "pages") {
        setActiveTab((prev) => (prev === tabId ? null : tabId));
        return;
      }
      if (tabId === "ai_panel") {
        // Spec §4.7 — find the focused, non-minimized note window.
        const focusedNote = [...windows]
          .filter(
            (w) => w.type === "note" && !w.minimized && w.meta.pageId,
          )
          .sort((a, b) => b.zIndex - a.zIndex)[0];
        if (!focusedNote) {
          console.warn(
            "ai-panel-sidebar: no focused note window; open a page first",
          );
          return;
        }
        openWindow({
          type: "ai_panel",
          title: `AI · ${focusedNote.title}`,
          meta: {
            pageId: focusedNote.meta.pageId || "",
            notebookId: focusedNote.meta.notebookId || notebookId,
          },
        });
        return;
      }
      if (tabId === "memory") {
        openWindow({
          type: "memory",
          title: tn("sidebar.openMemory"),
          meta: { notebookId },
        });
      } else if (tabId === "learn") {
        openWindow({
          type: "study",
          title: "Study",
          meta: { notebookId },
        });
      }
    },
    [openWindow, notebookId, tn, windows],
  );

  const panelOpen = activeTab === "pages";

  return (
    <div style={{ display: "flex", height: "100%" }}>
      {/* 56px icon rail */}
      <nav
        className="glass-sidebar glass-sidebar--collapsed"
        style={{
          position: "relative",
          width: 56,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          paddingTop: 12,
          paddingBottom: 12,
          gap: 4,
          flexShrink: 0,
          zIndex: 2,
        }}
      >
        <Link
          href="/app/notebooks"
          prefetch={false}
          className="glass-sidebar-nav-item"
          title={t("nav.back")}
          aria-label={t("nav.back")}
          style={{ marginBottom: 12 }}
        >
          <ArrowLeft size={20} strokeWidth={1.8} />
        </Link>

        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            data-testid={`sidebar-tab-${tab.id}`}
            className={`glass-sidebar-nav-item${
              isRouteActive(tab.id) || activeTab === tab.id ? " is-active" : ""
            }`}
            title={t(tab.key)}
            aria-label={t(tab.key)}
            onClick={() => handleTabClick(tab.id)}
          >
            <tab.Icon size={20} strokeWidth={1.8} />
          </button>
        ))}

        <div style={{ flex: 1 }} />

        <MinimizedTray />

        <Link
          href={`${basePath}/settings`}
          prefetch={false}
          className={`glass-sidebar-nav-item${
            pathname.includes("/settings") ? " is-active" : ""
          }`}
          title={t("nav.notebookSettings")}
          aria-label={t("nav.notebookSettings")}
        >
          <Settings size={20} strokeWidth={1.8} />
        </Link>
      </nav>

      {panelOpen && (
        <div
          className="notebook-side-panel"
          style={{
            width: 240,
            borderRight:
              "1px solid var(--console-border, rgba(255,255,255,0.7))",
            background: "rgba(255, 255, 255, 0.55)",
            backdropFilter: "blur(16px)",
            WebkitBackdropFilter: "blur(16px)",
            overflowY: "auto",
            padding: "16px 12px",
            flexShrink: 0,
          }}
        >
          <div
            style={{
              fontSize: "0.6875rem",
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
              color: "var(--console-text-muted, #6b7280)",
              marginBottom: 12,
            }}
          >
            {t("nav.pages")}
          </div>

          <div style={{ fontSize: "0.8125rem" }}>
            {pages.map((page) => (
              <button
                key={page.id}
                type="button"
                onClick={() =>
                  openWindow({
                    type: "note",
                    title: page.title || tn("common.untitled"),
                    meta: { notebookId, pageId: page.id },
                  })
                }
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "6px 12px",
                  borderRadius: 6,
                  color: "var(--console-text-primary, #1a1a2e)",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  fontSize: "0.8125rem",
                  transition: "background 100ms ease",
                  width: "100%",
                  textAlign: "left",
                }}
              >
                <FileText size={14} />
                {page.title || tn("common.untitled")}
              </button>
            ))}
            <Link
              href={basePath}
              prefetch={false}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "8px 12px",
                borderRadius: 6,
                color: "var(--console-accent, #2563EB)",
                textDecoration: "none",
                fontSize: "0.8125rem",
                fontWeight: 500,
                marginTop: 8,
              }}
            >
              + {tn("pages.create")}
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Add the missing `console.nav.aiPanel` key**

The sidebar references `t("nav.aiPanel")` (the `t` namespace is
`"console"`). Locate the console locale files:

```bash
ls apps/web/messages/en/*.json | xargs grep -l '"nav.memory"'
```

For each file that owns `nav.memory` (should be `console.json`), add
`"nav.aiPanel": "AI Panel"` (en) / `"nav.aiPanel": "AI 面板"` (zh)
near the other `nav.*` keys. If an existing `nav.chat` key exists, keep
it — it might be used elsewhere — but add the new key alongside.

- [ ] **Step 5: Typecheck + verify no chat leftovers**

Run:
```bash
cd apps/web && pnpm tsc --noEmit 2>&1 | grep -i "NotebookSidebar\|\"chat\"" | head -20
cd apps/web && grep -rn 'type: "chat"' components
```
Expected: no TS errors; second grep returns no hits.

- [ ] **Step 6: Commit**

```bash
git add apps/web/components/console/NotebookSidebar.tsx apps/web/messages
git commit -m "feat(web): sidebar AI icon opens ai_panel bound to focused note"
```

---

### Task 10: Wire persistence into WindowManagerProvider

**Files:**
- Modify: `apps/web/components/notebook/WindowManager.tsx`
- Modify: `apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx`
- Create: `apps/web/tests/unit/window-manager-persistence.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `apps/web/tests/unit/window-manager-persistence.test.tsx`:

```tsx
import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import {
  STORAGE_KEY_PREFIX,
  CURRENT_SCHEMA_VERSION,
} from "@/components/notebook/window-persistence";
import {
  WindowManagerProvider,
  useWindowManager,
} from "@/components/notebook/WindowManager";

// Small test harness that reaches into the provider.
function Harness({ onReady }: { onReady: (api: ReturnType<typeof useWindowManager>) => void }) {
  const api = useWindowManager();
  onReady(api);
  return null;
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("WindowManagerProvider persistence", () => {
  it("hydrates from localStorage on mount", () => {
    window.localStorage.setItem(
      STORAGE_KEY_PREFIX + "nb1",
      JSON.stringify({
        v: CURRENT_SCHEMA_VERSION,
        windows: [
          {
            id: "w1",
            type: "note",
            title: "hydrated",
            x: 5,
            y: 6,
            width: 780,
            height: 600,
            zIndex: 1,
            minimized: false,
            maximized: false,
            meta: { pageId: "p1", notebookId: "nb1" },
          },
        ],
      }),
    );

    let api: ReturnType<typeof useWindowManager> | undefined;
    render(
      <WindowManagerProvider notebookId="nb1">
        <Harness onReady={(a) => { api = a; }} />
      </WindowManagerProvider>,
    );
    expect(api?.windows).toHaveLength(1);
    expect(api?.windows[0].title).toBe("hydrated");
  });

  it("persists changes back to localStorage", async () => {
    let api: ReturnType<typeof useWindowManager> | undefined;
    render(
      <WindowManagerProvider notebookId="nb2">
        <Harness onReady={(a) => { api = a; }} />
      </WindowManagerProvider>,
    );
    act(() => {
      api?.openWindow({
        type: "note",
        title: "t",
        meta: { pageId: "p1", notebookId: "nb2" },
      });
    });
    // Wait for debounced persist (500ms)
    await new Promise((r) => setTimeout(r, 600));
    const raw = window.localStorage.getItem(STORAGE_KEY_PREFIX + "nb2");
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw!);
    expect(parsed.v).toBe(CURRENT_SCHEMA_VERSION);
    expect(parsed.windows).toHaveLength(1);
    expect(parsed.windows[0].title).toBe("t");
  });
});
```

Also add `@testing-library/react` as a dev dep (needed by this test):

```bash
cd apps/web && pnpm add -D @testing-library/react@^16.0.0 @testing-library/dom@^10.0.0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/web && pnpm test:unit tests/unit/window-manager-persistence.test.tsx`
Expected: FAIL — provider does not accept `notebookId` prop / does
not hydrate.

- [ ] **Step 3: Extend the provider to accept notebookId + hydrate + persist**

In `apps/web/components/notebook/WindowManager.tsx`, add to the
imports at the top:

```ts
import { useEffect } from "react";
import {
  loadPersistedLayout,
  savePersistedLayout,
} from "./window-persistence";
```

Update the provider signature and body:

```tsx
export function WindowManagerProvider({
  children,
  notebookId,
}: {
  children: ReactNode;
  notebookId: string;
}) {
  const [windows, dispatch] = useReducer(
    windowReducer,
    undefined,
    () => loadPersistedLayout(notebookId),
  );

  // Debounced persist on change.
  useEffect(() => {
    const handle = setTimeout(() => {
      savePersistedLayout(notebookId, windows);
    }, 500);
    return () => clearTimeout(handle);
  }, [notebookId, windows]);

  const openWindow = useCallback(
    (payload: OpenWindowPayload) => dispatch({ kind: "OPEN_WINDOW", payload }),
    [],
  );
  // ... the rest of the existing dispatch wrappers unchanged
```

Keep the rest of the provider body (`closeWindow`, `minimizeWindow`,
etc.) as-is; only the two changes above are needed.

- [ ] **Step 4: Pass notebookId from the notebook layout**

Open
`apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx`.
Locate the `<WindowManagerProvider>` usage and pass the param:

```tsx
// Near the top of the component, after `const params = useParams<...>()`:
const notebookId = params.notebookId;
// ...
<WindowManagerProvider notebookId={notebookId}>
  {children}
</WindowManagerProvider>
```

If the layout is a Server Component and has no access to `useParams`,
promote it (add `"use client"` if it isn't already) OR read
`notebookId` from the route segment via
`params: { notebookId: string }` — whichever pattern the file
already uses. Do not invent a new data-loading path; the file already
has `notebookId` somewhere (it has to — the page knows its id).

- [ ] **Step 5: Run to verify test pass**

Run: `cd apps/web && pnpm test:unit`
Expected: the two new persistence tests pass, plus the six helper
tests from Task 2.

- [ ] **Step 6: Commit**

```bash
git add apps/web/components/notebook/WindowManager.tsx apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx apps/web/tests/unit/window-manager-persistence.test.tsx apps/web/package.json apps/web/pnpm-lock.yaml
git commit -m "feat(web): WindowManagerProvider hydrates/persists per-notebook layout"
```

---

### Task 11: Remove S1 Trace footer from NoteEditor

**Files:**
- Modify: `apps/web/components/console/editor/NoteEditor.tsx`

- [ ] **Step 1: Remove the import**

Delete the `import AIActionsList from "@/components/notebook/AIActionsList";`
line at the top of `apps/web/components/console/editor/NoteEditor.tsx`.

- [ ] **Step 2: Remove the footer JSX**

Find and remove the `<details>` block added in S1:

```tsx
      {/* Collapsible AI Trace footer (S1) */}
      {pageId && (
        <details style={{ borderTop: "1px solid #eee", marginTop: 12 }}>
          <summary
            data-testid="panel-tab-trace"
            style={{
              cursor: "pointer",
              padding: "6px 12px",
              fontSize: 12,
              color: "#666",
              userSelect: "none",
            }}
          >
            AI Actions
          </summary>
          <AIActionsList pageId={pageId} />
        </details>
      )}
```

Delete the entire block. Keep the `</div></div>` return boilerplate
that follows.

- [ ] **Step 3: Typecheck**

Run: `cd apps/web && pnpm tsc --noEmit 2>&1 | grep -i "NoteEditor" | head -10`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/web/components/console/editor/NoteEditor.tsx
git commit -m "refactor(web): remove S1 inline trace footer — moved to ai_panel Trace tab"
```

---

### Task 12: Update the S1 Playwright smoke test to use the new Trace tab

**Files:**
- Modify: `apps/web/tests/notebook-ai-trace.spec.ts`

- [ ] **Step 1: Rewrite the test**

Overwrite `apps/web/tests/notebook-ai-trace.spec.ts` with:

```ts
import { test, expect } from "@playwright/test";

test.describe("AI action trace tab", () => {
  test("trace tab of AI Panel shows an entry after a selection rewrite", async ({
    page,
  }) => {
    await page.goto("/workspace/notebooks");
    await page.getByRole("button", { name: /create/i }).first().click();
    await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);

    // Create a page inside the notebook.
    await page.getByRole("button", { name: /create/i }).first().click();

    // Type and rewrite.
    const editor = page.locator(".ProseMirror").first();
    await editor.click();
    await editor.type("Hello world, this is a sentence.");
    await editor.press("Meta+a");

    const rewrite = page.getByRole("button", { name: /rewrite/i });
    if (await rewrite.isVisible().catch(() => false)) {
      await rewrite.click();
      await page.waitForTimeout(2000);
    }

    // Open AI Panel from the note title-bar.
    await page.getByTestId("note-open-ai-panel").first().click();

    // Switch to the Trace tab and assert an entry is visible.
    await page.getByTestId("ai-panel-tab-trace").click();
    const items = page.getByTestId("ai-action-item");
    await expect(items.first()).toBeVisible({ timeout: 10_000 });
    await expect(items.first()).toContainText(/selection\.rewrite/);
  });
});
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/tests/notebook-ai-trace.spec.ts
git commit -m "test(web): S1 trace smoke now drives the ai_panel Trace tab"
```

---

### Task 13: Playwright smoke for the four S3 flows

**Files:**
- Create: `apps/web/tests/s3-ai-panel.spec.ts`

- [ ] **Step 1: Write the test**

Create `apps/web/tests/s3-ai-panel.spec.ts`:

```ts
import { test, expect } from "@playwright/test";

async function bootstrapNotebookWithPage(page: import("@playwright/test").Page) {
  await page.goto("/workspace/notebooks");
  await page.getByRole("button", { name: /create/i }).first().click();
  await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);
  await page.getByRole("button", { name: /create/i }).first().click();
  // Ensure the note window is rendered.
  await expect(page.locator(".wm-window").first()).toBeVisible();
}

test.describe("S3 AI Panel", () => {
  test("title-bar Sparkles opens AI Panel bound to the note", async ({
    page,
  }) => {
    await bootstrapNotebookWithPage(page);
    await page.getByTestId("note-open-ai-panel").first().click();
    await expect(page.getByTestId("ai-panel-tab-ask")).toBeVisible();
    // Ask tab is the default.
    await expect(page.getByTestId("ai-panel-tab-ask")).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  test("sidebar AI icon opens AI Panel for the focused note", async ({
    page,
  }) => {
    await bootstrapNotebookWithPage(page);
    await page.getByTestId("sidebar-tab-ai_panel").click();
    await expect(page.getByTestId("ai-panel-tab-ask")).toBeVisible();
  });

  test("sidebar AI icon is a no-op when no note is focused", async ({
    page,
  }) => {
    await page.goto("/workspace/notebooks");
    await page.getByRole("button", { name: /create/i }).first().click();
    await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);
    // No page yet → no focused note.
    await page.getByTestId("sidebar-tab-ai_panel").click();
    await expect(page.getByTestId("ai-panel-tab-ask")).toHaveCount(0);
  });

  test("switching tabs swaps the body", async ({ page }) => {
    await bootstrapNotebookWithPage(page);
    await page.getByTestId("note-open-ai-panel").first().click();

    await page.getByTestId("ai-panel-tab-summary").click();
    await expect(page.getByTestId("ai-panel-summary")).toBeVisible();

    await page.getByTestId("ai-panel-tab-memory").click();
    // MemoryLinksPanel renders either the list or an empty-state hint.
    await expect(
      page.locator("text=/memory|No memories|empty/i").first(),
    ).toBeVisible();

    await page.getByTestId("ai-panel-tab-trace").click();
    await expect(page.getByTestId("ai-actions-list")).toBeVisible();
  });

  test("layout persists across reload", async ({ page }) => {
    await bootstrapNotebookWithPage(page);
    await page.getByTestId("note-open-ai-panel").first().click();
    await expect(page.getByTestId("ai-panel-tab-ask")).toBeVisible();

    const url = page.url();
    await page.reload();
    await page.waitForURL(url);

    // After reload the AI Panel window should still exist.
    await expect(page.getByTestId("ai-panel-tab-ask")).toBeVisible({
      timeout: 10_000,
    });
  });
});
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/tests/s3-ai-panel.spec.ts
git commit -m "test(web): Playwright smoke for S3 AI Panel flows"
```

---

### Task 14: Verify nothing is broken and report

**Files:** none (verification step)

- [ ] **Step 1: Run all unit tests**

Run: `cd apps/web && pnpm test:unit`
Expected: 8 passed (6 persistence helpers + 2 provider hydration).

- [ ] **Step 2: Typecheck full project**

Run: `cd apps/web && pnpm tsc --noEmit 2>&1 | tail -30`
Expected: no errors from files this plan touched. Pre-existing errors
(e.g., WhiteboardBlock Excalidraw mismatch) are out of scope.

- [ ] **Step 3: Grep for any leftover "chat" window references**

Run:
```bash
cd apps/web
grep -rn 'type: "chat"\|WINDOW_ICONS.*chat\|TRAY_ICONS.*chat\|WindowType.*"chat"' \
  --include="*.tsx" --include="*.ts" components app tests
```
Expected: no hits.

- [ ] **Step 4: Reported summary**

Produce a short report listing:
- all task commits (14 of them)
- unit + typecheck results
- any unexpected findings

No commit here.

---

## Final Acceptance Checklist

After all 14 tasks land, confirm:

- [ ] `pnpm test:unit` → 8 passed
- [ ] `grep -rn 'type: "chat"'` in `apps/web/components` → 0 hits
- [ ] `apps/web/components/notebook/contents/ChatWindow.tsx` no longer exists
- [ ] Opening a notebook, arranging windows, and reloading restores the layout
- [ ] Clicking the Sparkles button in a note title-bar opens a new AI Panel window
- [ ] Clicking the sidebar AI icon with a focused note opens a new AI Panel window
- [ ] The four tabs (Ask / Summary / Memory / Trace) all render their respective content
- [ ] S1's smoke test (updated in Task 12) still passes

## Cross-references

- Spec: `docs/superpowers/specs/2026-04-15-ai-panel-window-design.md`
- Original product spec: `MRAI_notebook_ai_os_build_spec.md` §6.3, §19.4
