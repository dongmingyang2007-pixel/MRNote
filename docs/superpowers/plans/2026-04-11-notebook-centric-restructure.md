# Notebook-Centric Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform MRAI from an AI assistant console into a notebook-centric AI workspace, where notebooks are the core experience and chat/memory become notebook sub-modules.

**Architecture:** Replace the current global sidebar (Home/Chat/Memory/Notebooks/Discover) with a context-switching sidebar: global mode shows 3 items (Dashboard/Notebooks/Settings), notebook mode shows 5 tabs (Pages/Chat/Memory/Learn/Settings). Each notebook auto-creates a Project to bind chat and memory APIs. Existing ChatInterface and memory components are reused inside notebook sub-routes.

**Tech Stack:** Next.js 16 App Router, React 18, TipTap, Tailwind CSS, next-intl, lucide-react, CSS custom properties (glassmorphism design system)

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `components/console/GlobalSidebar.tsx` | Global sidebar (Dashboard/Notebooks/Settings) — renders when user is NOT inside a notebook |
| `components/console/NotebookSidebar.tsx` | Notebook-internal sidebar (Back/Pages/Chat/Memory/Learn/Settings) with expandable 240px panel |
| `components/console/NotebookSidePanel.tsx` | The 240px expandable panel content (page tree, chat list, memory cards, learn items) |
| `app/[locale]/workspace/notebooks/[notebookId]/layout.tsx` | Notebook workspace layout — renders NotebookSidebar + content area, fetches notebook info, provides notebookId context |
| `app/[locale]/workspace/notebooks/[notebookId]/chat/page.tsx` | Notebook chat page — reuses ChatInterface with notebook's project_id |
| `app/[locale]/workspace/notebooks/[notebookId]/memory/page.tsx` | Notebook memory page — reuses memory components with notebook's project_id |
| `app/[locale]/workspace/notebooks/[notebookId]/settings/page.tsx` | Notebook settings page |

### Modified files

| File | Change |
|------|--------|
| `components/console/ConsoleShell.tsx` | Replace `<Sidebar />` with conditional `<GlobalSidebar />` or nothing (notebook layout handles its own sidebar) |
| `components/console/Sidebar.tsx` | Keep file but stop rendering it from ConsoleShell (notebook layout renders NotebookSidebar instead) |
| `app/[locale]/workspace/page.tsx` | Redesign as "Today's Workspace" smart homepage |
| `app/[locale]/workspace/layout.tsx` | Add sidebar context switching logic |
| `components/console/glass/GlassTopBar.tsx` | Update breadcrumbs for new route structure |
| `components/console/CommandPalette.tsx` | Update navigation items |
| `messages/zh/console.json` | Add new i18n keys |
| `messages/en/console.json` | Add new i18n keys |

### Deleted routes (Phase 3)

| Route | Status |
|-------|--------|
| `app/[locale]/workspace/chat/page.tsx` | Delete (migrated to notebook sub-route) |
| `app/[locale]/workspace/memory/page.tsx` | Delete (migrated to notebook sub-route) |
| `app/[locale]/workspace/memory/list-preview/page.tsx` | Delete |
| `app/[locale]/workspace/assistants/page.tsx` | Delete |
| `app/[locale]/workspace/assistants/new/page.tsx` | Delete |
| `app/[locale]/workspace/assistants/[id]/page.tsx` | Delete |
| `app/[locale]/workspace/discover/` (entire directory) | Delete |

---

## Task 1: Backend — Auto-create Project on Notebook Creation

**Files:**
- Modify: `apps/api/app/routers/notebooks.py` (the `create_notebook` endpoint)

- [ ] **Step 1: Read the current create_notebook endpoint**

Read `apps/api/app/routers/notebooks.py` and find the `create_notebook` POST endpoint. Note how it currently creates a Notebook without ensuring a Project exists.

- [ ] **Step 2: Add auto-project-creation logic**

In the `create_notebook` endpoint, after creating the Notebook and before `db.commit()`, add:

```python
from app.models import Project
from app.services.memory_roots import ensure_project_assistant_root

# Auto-create a Project if none provided
if not notebook.project_id:
    project = Project(
        workspace_id=workspace_id,
        name=f"Notebook: {payload.title or 'Untitled'}",
    )
    db.add(project)
    db.flush()
    root_memory, _ = ensure_project_assistant_root(db, project, reparent_orphans=False)
    project.assistant_root_memory_id = root_memory.id
    notebook.project_id = project.id
```

This mirrors the exact pattern from `projects.py:create_project` (lines 50-59).

- [ ] **Step 3: Verify the API still imports**

Run:
```bash
cd /Users/dog/Desktop/MRAI/apps/api && PYTHONPATH=/Users/dog/Desktop/MRAI/apps/api .venv/bin/python -c "from app.routers.notebooks import router; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/routers/notebooks.py
git commit -m "feat: auto-create Project when creating a Notebook"
```

---

## Task 2: Add i18n Keys for New Navigation

**Files:**
- Modify: `apps/web/messages/zh/console.json`
- Modify: `apps/web/messages/en/console.json`

- [ ] **Step 1: Add Chinese translation keys**

Add these keys to `apps/web/messages/zh/console.json` (anywhere in the file, maintaining alphabetical order near existing `nav.*` keys):

```json
"nav.dashboard": "工作台",
"nav.notebooks": "笔记",
"nav.settings": "设置",
"nav.back": "返回",
"nav.pages": "页面",
"nav.chat": "AI 对话",
"nav.memory": "记忆",
"nav.learn": "学习",
"nav.notebookSettings": "笔记本设置",
"dashboard.welcome": "欢迎回来",
"dashboard.continueWriting": "继续写作",
"dashboard.myNotebooks": "我的笔记本",
"dashboard.recentChats": "最近对话",
"dashboard.noRecent": "还没有最近编辑的页面",
"dashboard.noNotebooks": "还没有笔记本",
"dashboard.noChats": "还没有最近的对话"
```

- [ ] **Step 2: Add English translation keys**

Add corresponding keys to `apps/web/messages/en/console.json`:

```json
"nav.dashboard": "Dashboard",
"nav.notebooks": "Notes",
"nav.settings": "Settings",
"nav.back": "Back",
"nav.pages": "Pages",
"nav.chat": "AI Chat",
"nav.memory": "Memory",
"nav.learn": "Learn",
"nav.notebookSettings": "Notebook Settings",
"dashboard.welcome": "Welcome back",
"dashboard.continueWriting": "Continue Writing",
"dashboard.myNotebooks": "My Notebooks",
"dashboard.recentChats": "Recent Chats",
"dashboard.noRecent": "No recently edited pages",
"dashboard.noNotebooks": "No notebooks yet",
"dashboard.noChats": "No recent chats"
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/messages/zh/console.json apps/web/messages/en/console.json
git commit -m "i18n: add navigation and dashboard translation keys"
```

---

## Task 3: Create GlobalSidebar Component

**Files:**
- Create: `apps/web/components/console/GlobalSidebar.tsx`

- [ ] **Step 1: Create the GlobalSidebar component**

Create `apps/web/components/console/GlobalSidebar.tsx`. This is a simplified version of the current Sidebar.tsx with only 3 nav items (Dashboard, Notebooks, Settings) and no project list or expand-on-hover behavior.

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { LayoutDashboard, BookOpen, Settings } from "lucide-react";

const NAV_ITEMS = [
  { href: "/app", key: "nav.dashboard", Icon: LayoutDashboard },
  { href: "/app/notebooks", key: "nav.notebooks", Icon: BookOpen },
  { href: "/app/settings", key: "nav.settings", Icon: Settings },
] as const;

export default function GlobalSidebar() {
  const pathname = usePathname();
  const t = useTranslations("console");

  const isActive = (href: string) => {
    if (href === "/app") return pathname === "/app" || pathname.endsWith("/workspace");
    return pathname.startsWith(href);
  };

  // Don't render if user is inside a notebook (NotebookSidebar handles that)
  const isInsideNotebook = /\/notebooks\/[^/]+/.test(pathname);
  if (isInsideNotebook) return null;

  return (
    <nav
      className="glass-sidebar glass-sidebar--collapsed"
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        bottom: 0,
        width: 56,
        zIndex: 40,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        paddingTop: 12,
        paddingBottom: 12,
        gap: 4,
      }}
    >
      {/* Logo */}
      <Link href="/app" className="glass-sidebar-logo" style={{ marginBottom: 16 }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: "white" }}>
          {t("nav.dashboard").charAt(0)}
        </span>
      </Link>

      {/* Nav items */}
      <div style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1 }}>
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            prefetch={false}
            className={`glass-sidebar-nav-item${isActive(item.href) ? " is-active" : ""}`}
            title={t(item.key)}
            aria-label={t(item.key)}
          >
            <item.Icon size={20} strokeWidth={1.8} />
          </Link>
        ))}
      </div>
    </nav>
  );
}
```

- [ ] **Step 2: Verify build**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && npx pnpm build 2>&1 | grep -E "(error|Error|✓ Compiled)" | head -5
```
Expected: `✓ Compiled successfully`

- [ ] **Step 3: Commit**

```bash
git add apps/web/components/console/GlobalSidebar.tsx
git commit -m "feat: add GlobalSidebar component with 3-item navigation"
```

---

## Task 4: Create NotebookSidebar Component

**Files:**
- Create: `apps/web/components/console/NotebookSidebar.tsx`

- [ ] **Step 1: Create the NotebookSidebar component**

Create `apps/web/components/console/NotebookSidebar.tsx`. This renders when the user is inside a notebook. It has a 56px icon rail with tabs (Pages/Chat/Memory/Learn) and a toggleable 240px panel.

```tsx
"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowLeft, FileText, MessageSquare, Brain, BookOpen, Settings } from "lucide-react";

type SideTab = "pages" | "chat" | "memory" | "learn" | null;

interface NotebookSidebarProps {
  notebookId: string;
  notebookTitle?: string;
}

const TABS = [
  { id: "pages" as const, Icon: FileText, key: "nav.pages", route: "" },
  { id: "chat" as const, Icon: MessageSquare, key: "nav.chat", route: "/chat" },
  { id: "memory" as const, Icon: Brain, key: "nav.memory", route: "/memory" },
  { id: "learn" as const, Icon: BookOpen, key: "nav.learn", route: "/learn" },
] as const;

export default function NotebookSidebar({ notebookId, notebookTitle }: NotebookSidebarProps) {
  const pathname = usePathname();
  const t = useTranslations("console");
  const [activeTab, setActiveTab] = useState<SideTab>("pages");

  const basePath = `/app/notebooks/${notebookId}`;

  const isTabActive = (route: string) => {
    if (route === "") {
      // "pages" tab is active on the base route and /pages/* routes
      return pathname === basePath ||
        pathname.endsWith(`/notebooks/${notebookId}`) ||
        pathname.includes(`/notebooks/${notebookId}/pages/`);
    }
    return pathname.includes(`/notebooks/${notebookId}${route}`);
  };

  const handleTabClick = useCallback((tabId: SideTab) => {
    setActiveTab((prev) => (prev === tabId ? null : tabId));
  }, []);

  const panelOpen = activeTab !== null;

  return (
    <div style={{ display: "flex", height: "100%", position: "relative" }}>
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
          zIndex: 40,
        }}
      >
        {/* Back button */}
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

        {/* Tab icons */}
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`glass-sidebar-nav-item${isTabActive(tab.route) ? " is-active" : ""}${activeTab === tab.id ? " is-active" : ""}`}
            title={t(tab.key)}
            aria-label={t(tab.key)}
            onClick={() => handleTabClick(tab.id)}
          >
            <tab.Icon size={20} strokeWidth={1.8} />
          </button>
        ))}

        {/* Spacer */}
        <div style={{ flex: 1 }} />

        {/* Settings */}
        <Link
          href={`${basePath}/settings`}
          prefetch={false}
          className={`glass-sidebar-nav-item${pathname.includes("/settings") ? " is-active" : ""}`}
          title={t("nav.notebookSettings")}
          aria-label={t("nav.notebookSettings")}
        >
          <Settings size={20} strokeWidth={1.8} />
        </Link>
      </nav>

      {/* 240px expandable panel */}
      {panelOpen && (
        <div
          style={{
            width: 240,
            borderRight: "1px solid var(--console-border, rgba(255,255,255,0.7))",
            background: "rgba(255, 255, 255, 0.55)",
            backdropFilter: "blur(16px)",
            WebkitBackdropFilter: "blur(16px)",
            overflowY: "auto",
            padding: "16px 12px",
            flexShrink: 0,
          }}
        >
          <div style={{ fontSize: "0.6875rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--console-text-muted, #6b7280)", marginBottom: 12 }}>
            {t(`nav.${activeTab}` as "nav.pages")}
          </div>

          {activeTab === "pages" && (
            <div style={{ fontSize: "0.8125rem", color: "var(--console-text-secondary)" }}>
              {/* Page tree will be rendered by NotebookSidePanel */}
              <p style={{ color: "var(--console-text-muted)", fontSize: "0.75rem" }}>
                Page tree content loaded from notebook layout
              </p>
            </div>
          )}

          {activeTab === "chat" && (
            <div style={{ fontSize: "0.8125rem" }}>
              <Link
                href={`${basePath}/chat`}
                style={{ display: "block", padding: "8px 12px", borderRadius: 8, color: "var(--console-text-primary)", textDecoration: "none" }}
              >
                Open AI Chat
              </Link>
            </div>
          )}

          {activeTab === "memory" && (
            <div style={{ fontSize: "0.8125rem" }}>
              <Link
                href={`${basePath}/memory`}
                style={{ display: "block", padding: "8px 12px", borderRadius: 8, color: "var(--console-text-primary)", textDecoration: "none" }}
              >
                Open Memory
              </Link>
            </div>
          )}

          {activeTab === "learn" && (
            <div style={{ fontSize: "0.8125rem", color: "var(--console-text-muted)" }}>
              Coming soon
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && npx pnpm build 2>&1 | grep -E "(error|Error|✓ Compiled)" | head -5
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/components/console/NotebookSidebar.tsx
git commit -m "feat: add NotebookSidebar with context-switching tabs and expandable panel"
```

---

## Task 5: Create Notebook Workspace Layout

**Files:**
- Create: `apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx`
- Modify: `apps/web/app/[locale]/workspace/notebooks/layout.tsx` (already exists, currently just imports CSS)

- [ ] **Step 1: Create the notebook workspace layout**

This layout wraps all routes inside a specific notebook. It renders the NotebookSidebar and provides notebook context. It also replaces the ConsoleShell sidebar by hiding the global sidebar (ConsoleShell renders `<Sidebar />` but the GlobalSidebar component already returns null for notebook routes).

Create `apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import NotebookSidebar from "@/components/console/NotebookSidebar";
import { apiGet } from "@/lib/api";

interface NotebookInfo {
  id: string;
  title: string;
  project_id: string | null;
}

export default function NotebookWorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams<{ notebookId: string }>();
  const [notebook, setNotebook] = useState<NotebookInfo | null>(null);

  useEffect(() => {
    void apiGet<NotebookInfo>(`/api/v1/notebooks/${params.notebookId}`)
      .then(setNotebook)
      .catch(() => setNotebook(null));
  }, [params.notebookId]);

  return (
    <div style={{ display: "flex", height: "calc(100vh - 48px - 28px)", marginLeft: -56 }}>
      {/* NotebookSidebar replaces the global sidebar */}
      <NotebookSidebar
        notebookId={params.notebookId}
        notebookTitle={notebook?.title}
      />

      {/* Content area */}
      <div style={{ flex: 1, overflow: "auto", minWidth: 0 }}>
        {children}
      </div>
    </div>
  );
}
```

The `marginLeft: -56` counteracts the ConsoleShell's `marginLeft: 56`, so the NotebookSidebar can render at the exact position where the global sidebar was.

- [ ] **Step 2: Verify build**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && npx pnpm build 2>&1 | grep -E "(error|Error|✓ Compiled)" | head -5
```

- [ ] **Step 3: Commit**

```bash
git add "apps/web/app/[locale]/workspace/notebooks/[notebookId]/layout.tsx"
git commit -m "feat: add notebook workspace layout with NotebookSidebar"
```

---

## Task 6: Modify ConsoleShell to Use GlobalSidebar

**Files:**
- Modify: `apps/web/components/console/ConsoleShell.tsx`

- [ ] **Step 1: Replace Sidebar with GlobalSidebar**

Read `apps/web/components/console/ConsoleShell.tsx`. Replace the `<Sidebar />` import and usage with `<GlobalSidebar />`:

Change:
```tsx
import Sidebar from "./Sidebar";
```
To:
```tsx
import GlobalSidebar from "./GlobalSidebar";
```

And in the JSX, replace `<Sidebar />` with `<GlobalSidebar />`.

- [ ] **Step 2: Verify build**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && npx pnpm build 2>&1 | grep -E "(error|Error|✓ Compiled)" | head -5
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/components/console/ConsoleShell.tsx
git commit -m "refactor: replace Sidebar with GlobalSidebar in ConsoleShell"
```

---

## Task 7: Create Notebook Chat Sub-Route

**Files:**
- Create: `apps/web/app/[locale]/workspace/notebooks/[notebookId]/chat/page.tsx`

- [ ] **Step 1: Create the notebook chat page**

This page reuses the existing ChatInterface component but scoped to the notebook's project. Read `apps/web/app/[locale]/workspace/chat/page.tsx` to understand how ChatInterface is used, then create a simplified version.

```tsx
"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiGet } from "@/lib/api";

interface NotebookInfo {
  id: string;
  title: string;
  project_id: string | null;
}

export default function NotebookChatPage() {
  const params = useParams<{ notebookId: string }>();
  const [notebook, setNotebook] = useState<NotebookInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void apiGet<NotebookInfo>(`/api/v1/notebooks/${params.notebookId}`)
      .then((data) => {
        setNotebook(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [params.notebookId]);

  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--console-text-muted)" }}>
        Loading...
      </div>
    );
  }

  if (!notebook?.project_id) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--console-text-muted)" }}>
        No project linked to this notebook.
      </div>
    );
  }

  // Import ChatInterface dynamically to avoid circular deps
  const ChatInterface = require("@/components/console/ChatInterface").default;

  return (
    <div style={{ height: "100%", overflow: "hidden" }}>
      <ChatInterface projectId={notebook.project_id} />
    </div>
  );
}
```

Note: ChatInterface currently gets projectId from useProjectContext(). We need to check if it accepts a `projectId` prop directly. If not, we may need to wrap it with ProjectContext set to the notebook's project_id. Read `ChatInterface.tsx` to verify.

- [ ] **Step 2: Verify build**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && npx pnpm build 2>&1 | grep -E "(error|Error|✓ Compiled)" | head -5
```

- [ ] **Step 3: Commit**

```bash
git add "apps/web/app/[locale]/workspace/notebooks/[notebookId]/chat/page.tsx"
git commit -m "feat: add notebook chat sub-route reusing ChatInterface"
```

---

## Task 8: Create Notebook Memory Sub-Route

**Files:**
- Create: `apps/web/app/[locale]/workspace/notebooks/[notebookId]/memory/page.tsx`

- [ ] **Step 1: Create the notebook memory page**

Similar to the chat page, this reuses existing memory components scoped to the notebook's project.

```tsx
"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiGet } from "@/lib/api";

interface NotebookInfo {
  id: string;
  project_id: string | null;
}

export default function NotebookMemoryPage() {
  const params = useParams<{ notebookId: string }>();
  const [notebook, setNotebook] = useState<NotebookInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void apiGet<NotebookInfo>(`/api/v1/notebooks/${params.notebookId}`)
      .then((data) => {
        setNotebook(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [params.notebookId]);

  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--console-text-muted)" }}>
        Loading...
      </div>
    );
  }

  if (!notebook?.project_id) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--console-text-muted)" }}>
        No project linked to this notebook.
      </div>
    );
  }

  return (
    <div style={{ height: "100%", overflow: "auto", padding: "24px 32px" }}>
      <h2 style={{ fontSize: "1.25rem", fontWeight: 600, color: "var(--console-text-primary)", marginBottom: 16 }}>
        Memory
      </h2>
      <p style={{ color: "var(--console-text-muted)", fontSize: "0.875rem" }}>
        Memory view for this notebook (project: {notebook.project_id}).
        Full memory UI will be connected in a follow-up task.
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Create notebook settings page**

Create `apps/web/app/[locale]/workspace/notebooks/[notebookId]/settings/page.tsx`:

```tsx
"use client";

import { useParams } from "next/navigation";

export default function NotebookSettingsPage() {
  const params = useParams<{ notebookId: string }>();

  return (
    <div style={{ padding: "32px 40px", maxWidth: 640, margin: "0 auto" }}>
      <h2 style={{ fontSize: "1.25rem", fontWeight: 600, color: "var(--console-text-primary)", marginBottom: 16 }}>
        Notebook Settings
      </h2>
      <p style={{ color: "var(--console-text-muted)", fontSize: "0.875rem" }}>
        Settings for notebook {params.notebookId}.
        Model configuration, export/import, and notebook metadata will be added here.
      </p>
    </div>
  );
}
```

- [ ] **Step 3: Verify build**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && npx pnpm build 2>&1 | grep -E "(error|Error|✓ Compiled)" | head -5
```

- [ ] **Step 4: Commit**

```bash
git add "apps/web/app/[locale]/workspace/notebooks/[notebookId]/memory/page.tsx" \
       "apps/web/app/[locale]/workspace/notebooks/[notebookId]/settings/page.tsx"
git commit -m "feat: add notebook memory and settings sub-routes"
```

---

## Task 9: Redesign Homepage as Today's Workspace

**Files:**
- Modify: `apps/web/app/[locale]/workspace/page.tsx`

- [ ] **Step 1: Rewrite the homepage**

Read the current `apps/web/app/[locale]/workspace/page.tsx`. Rewrite it as a "Today's Workspace" smart homepage with three sections:

1. **Welcome + Continue Writing** — latest 3 edited pages across all notebooks
2. **My Notebooks** — notebook card grid
3. **Recent Chats** — cross-notebook recent conversations

The component should:
- Fetch notebooks from `GET /api/v1/notebooks`
- Fetch recent pages from `GET /api/v1/pages/search?q=` (returns latest pages)
- Use the existing dashboard CSS classes where possible
- Link to notebook routes (`/app/notebooks/[id]`) instead of assistant routes
- Remove all assistant/project management UI

- [ ] **Step 2: Verify build**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && npx pnpm build 2>&1 | grep -E "(error|Error|✓ Compiled)" | head -5
```

- [ ] **Step 3: Commit**

```bash
git add "apps/web/app/[locale]/workspace/page.tsx"
git commit -m "feat: redesign homepage as Today's Workspace"
```

---

## Task 10: Update GlassTopBar Breadcrumbs

**Files:**
- Modify: `apps/web/components/console/glass/GlassTopBar.tsx`

- [ ] **Step 1: Update breadcrumb routing logic**

Read `apps/web/components/console/glass/GlassTopBar.tsx`. Find the breadcrumb logic and update it:

- Remove: chat, memory, discover, assistants breadcrumbs
- Add: notebooks breadcrumb for `/app/notebooks/*` routes
- The notebook workspace routes should show: "铭润 > 笔记" or hide breadcrumb entirely inside notebook workspace (the NotebookSidebar provides navigation)

- [ ] **Step 2: Verify build and commit**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && npx pnpm build 2>&1 | grep -E "(error|Error|✓ Compiled)" | head -5
git add apps/web/components/console/glass/GlassTopBar.tsx
git commit -m "refactor: update GlassTopBar breadcrumbs for notebook-centric routes"
```

---

## Task 11: Update CommandPalette Navigation

**Files:**
- Modify: `apps/web/components/console/CommandPalette.tsx`

- [ ] **Step 1: Update navigation items**

Read `apps/web/components/console/CommandPalette.tsx`. Find the `NAVIGATION_ITEMS` array and update it:

Remove: chat, memory, assistants, discover entries
Keep: notebooks
Add: dashboard (home/workspace)

- [ ] **Step 2: Verify build and commit**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && npx pnpm build 2>&1 | grep -E "(error|Error|✓ Compiled)" | head -5
git add apps/web/components/console/CommandPalette.tsx
git commit -m "refactor: update CommandPalette navigation for notebook-centric structure"
```

---

## Task 12: Delete Old Routes

**Files:**
- Delete: `apps/web/app/[locale]/workspace/chat/page.tsx`
- Delete: `apps/web/app/[locale]/workspace/memory/page.tsx`
- Delete: `apps/web/app/[locale]/workspace/memory/list-preview/page.tsx`
- Delete: `apps/web/app/[locale]/workspace/assistants/` (entire directory)
- Delete: `apps/web/app/[locale]/workspace/discover/` (entire directory)

- [ ] **Step 1: Delete old route files**

```bash
rm apps/web/app/\[locale\]/workspace/chat/page.tsx
rm apps/web/app/\[locale\]/workspace/memory/page.tsx
rm -rf apps/web/app/\[locale\]/workspace/memory/list-preview
rm -rf apps/web/app/\[locale\]/workspace/assistants
rm -rf apps/web/app/\[locale\]/workspace/discover
```

- [ ] **Step 2: Verify build**

The build should succeed since no remaining code imports from these deleted routes. If any imports break, fix them.

```bash
cd /Users/dog/Desktop/MRAI/apps/web && npx pnpm build 2>&1 | grep -E "(error|Error|✓ Compiled)" | head -5
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "cleanup: remove old chat/memory/assistants/discover routes"
```

---

## Task 13: Final Verification

- [ ] **Step 1: Full build**

```bash
cd /Users/dog/Desktop/MRAI/apps/web && npx pnpm build 2>&1 | tail -25
```

Expected: All routes compile, including:
```
├ ƒ /[locale]/workspace
├ ƒ /[locale]/workspace/notebooks
├ ƒ /[locale]/workspace/notebooks/[notebookId]
├ ƒ /[locale]/workspace/notebooks/[notebookId]/chat
├ ƒ /[locale]/workspace/notebooks/[notebookId]/memory
├ ƒ /[locale]/workspace/notebooks/[notebookId]/pages/[pageId]
├ ƒ /[locale]/workspace/notebooks/[notebookId]/settings
└ ƒ /[locale]/workspace/settings
```

Old routes should NOT appear:
```
NOT: /[locale]/workspace/chat
NOT: /[locale]/workspace/memory
NOT: /[locale]/workspace/assistants
NOT: /[locale]/workspace/discover
```

- [ ] **Step 2: Backend verification**

```bash
cd /Users/dog/Desktop/MRAI/apps/api && PYTHONPATH=/Users/dog/Desktop/MRAI/apps/api .venv/bin/python -c "from app.main import app; print('Backend OK')"
```

- [ ] **Step 3: Start dev server and test navigation flow**

```bash
cd /Users/dog/Desktop/MRAI && bash scripts/dev.sh
```

Test in browser:
1. `/app` → Today's Workspace homepage with notebook cards
2. Click a notebook → sidebar switches to notebook-internal navigation
3. Click Pages/Chat/Memory tabs in sidebar → panel expands/collapses
4. Click back arrow → returns to notebook list
5. Global sidebar shows only Dashboard/Notebooks/Settings
