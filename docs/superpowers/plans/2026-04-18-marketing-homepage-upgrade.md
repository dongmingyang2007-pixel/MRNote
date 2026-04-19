# Marketing Homepage Upgrade — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every placeholder visual on `/[locale]` (Hero demo
box, 3× feature `screenshot` boxes, big Screenshot section) with
self-rendered HTML/CSS "mockups" of MRNote's actual product UI —
windows, memory cards, digest — so the first-time visitor instantly
sees *what the product looks like and what makes it different* without
a single binary image. Add a `LiveCanvasDemo` below the fold that
users can drag to feel the floating-window UX first-hand. Fix the
login dead-end by giving the auth pages a tagline + prominent "返回
首页" back-link.

**Architecture:** Keep the existing 6-section marketing page, its
next-intl i18n, and `marketing.css` tokens. Add a new
`marketing-mock-*` CSS layer that mirrors the real product chrome
(title bar, traffic lights, content cells) at marketing quality.
Build 5 new React components: one generic `MockWindow` chrome, three
content-specific content cards (`MemoryMock`, `FollowupMock`,
`DigestMock`), one `HeroCanvasStage` that composes them into an
idle-floating stack for the hero, and one `LiveCanvasDemo` client
component that reuses the same mocks wrapped in `react-rnd` for drag.
Use CSS `@keyframes` for the "GIF-like" motion (idle float, typewriter,
pulse, shimmer); no video, no Lottie, no GSAP for the mocks
themselves. Auth fix is a tiny shared `AuthBrandHeader` that replaces
the existing bare wordmark.

**Tech Stack:** Next.js 16 (app router), React 18, TypeScript,
next-intl 4, Plus Jakarta Sans (already loaded), Lucide icons
(already a dep), `react-rnd` (already in use by WindowManager),
Playwright (existing smoke tests), marketing.css design tokens
(`--brand-v2`, `--bg-surface`, `--border`, `--text-primary`,
`--text-secondary`, `--radius-*`, `--motion-*`, `--space-*`).

**Reference:** Overleaf homepage — big bold hero + real product
canvas right below. We steal the *structure* not the content.

---

## Phase Overview

| # | Phase | Scope |
|---|---|---|
| A | CSS foundation: `.marketing-mock-*` tokens + keyframes in `marketing.css` |
| B | `MockWindow` chrome + three content mocks (`MemoryMock`, `FollowupMock`, `DigestMock`) |
| C | `HeroCanvasStage` + swap hero demo placeholder |
| D | Swap 3× feature `__media` placeholders to use the same mocks |
| E | `LiveCanvasDemo` (draggable, react-rnd) + swap `ScreenshotSection` placeholder |
| F | Auth dead-end fix: `AuthBrandHeader` with tagline + back-link |
| G | Playwright smoke update + manual dev-server verification |

Each phase ends in a single commit. No placeholders in any phase.

---

## File Structure

**Create:**
- `apps/web/components/marketing/mocks/MockWindow.tsx` — reusable
  window chrome (traffic lights + title + body slot). Server
  component.
- `apps/web/components/marketing/mocks/MemoryMock.tsx` — feature 1
  card content ("持久记忆" extracted rows with typewriter accent).
  Server component.
- `apps/web/components/marketing/mocks/FollowupMock.tsx` — feature 2
  card content (followup reminder with pulsing dot). Server
  component.
- `apps/web/components/marketing/mocks/DigestMock.tsx` — feature 3
  card content (Monday digest bullet list). Server component.
- `apps/web/components/marketing/HeroCanvasStage.tsx` — composes the
  three mocks into a stacked floating canvas for the hero. Server
  component (CSS-only animation).
- `apps/web/components/marketing/LiveCanvasDemo.tsx` — interactive
  drag canvas wrapping the same three mocks in `react-rnd`. Client
  component (`"use client"`).
- `apps/web/components/marketing/AuthBrandHeader.tsx` — shared auth
  header with wordmark + tagline + back-to-home link.
- `apps/web/tests/marketing-homepage.spec.ts` — new Playwright smoke
  test.

**Modify:**
- `apps/web/styles/marketing.css` — append `.marketing-mock-*` layer
  with chrome, row, badge, keyframes.
- `apps/web/components/marketing/HeroSection.tsx` — replace
  `marketing-hero__demo` placeholder div with `<HeroCanvasStage />`.
- `apps/web/components/marketing/FeaturesSection.tsx` — replace each
  `marketing-feature__media` placeholder div with one of the three
  mocks.
- `apps/web/components/marketing/ScreenshotSection.tsx` — replace
  `marketing-screenshot` placeholder div with `<LiveCanvasDemo />`.
- `apps/web/app/[locale]/(auth)/layout.tsx` — replace the inline
  wordmark block with `<AuthBrandHeader />`.
- `apps/web/messages/zh/marketing.json` — add 4 new keys for the
  LiveCanvasDemo instruction tooltip.
- `apps/web/messages/en/marketing.json` — matching 4 keys.
- `apps/web/messages/zh/auth.json` — add 2 keys for the auth header
  tagline + back link.
- `apps/web/messages/en/auth.json` — matching 2 keys.

**Files touched but not restructured:** `globals.css` (token contract
kept identical), `HeroAnimatedClient.tsx` (its GSAP wrapper already
handles `.marketing-fade-in` children — we don't touch it).

---

## Phase A — CSS foundation

### Task A1: Append mock chrome + keyframes to `marketing.css`

**Files:**
- Modify: `apps/web/styles/marketing.css` (append at end)

- [ ] **Step 1: Append the mock layer**

Append this exact block to the end of
`apps/web/styles/marketing.css`:

```css
/* ─── Mock product chrome (in-page UI mockups) ─── */
/* Used by HeroCanvasStage, FeaturesSection media, LiveCanvasDemo.   *
 * Every visual on the landing page renders through these classes —  *
 * no binary images, no Lottie. Motion is CSS keyframe-driven so the *
 * bundle stays lean. Respect `prefers-reduced-motion`.              */

.marketing-mock {
  position: relative;
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
  border: 1px solid var(--border);
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 12px 32px rgba(15, 23, 42, 0.08);
  overflow: hidden;
  font-size: 0.8125rem;
  color: var(--text-primary);
}

.marketing-mock__titlebar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(
    180deg,
    rgba(15, 23, 42, 0.02) 0%,
    transparent 100%
  );
}

.marketing-mock__lights {
  display: inline-flex;
  gap: 6px;
}
.marketing-mock__light {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: var(--border);
}
.marketing-mock__light--red    { background: #ff5f57; }
.marketing-mock__light--yellow { background: #febc2e; }
.marketing-mock__light--green  { background: #28c840; }

.marketing-mock__title {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-secondary);
  letter-spacing: 0.02em;
}

.marketing-mock__body {
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* Generic key/value row used by Memory / Followup / Digest mocks. */
.marketing-mock__row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  background: var(--bg-base);
  border: 1px solid var(--border);
}

.marketing-mock__row-label {
  font-size: 0.6875rem;
  font-weight: 600;
  color: var(--brand-v2);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  flex-shrink: 0;
  width: 64px;
  line-height: 1.4;
}

.marketing-mock__row-value {
  font-size: 0.8125rem;
  color: var(--text-primary);
  line-height: 1.45;
  flex: 1;
}

.marketing-mock__dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--brand-v2);
  flex-shrink: 0;
  margin-top: 5px;
}
.marketing-mock__dot--pulse {
  animation: marketing-mock-pulse 1.8s ease-in-out infinite;
}
.marketing-mock__dot--amber {
  background: #f59e0b;
}

/* Typewriter caret used by MemoryMock on the "extracted" value. */
.marketing-mock__caret {
  display: inline-block;
  width: 1px;
  height: 1em;
  margin-left: 2px;
  background: var(--text-primary);
  vertical-align: -2px;
  animation: marketing-mock-blink 1s steps(1) infinite;
}

/* ─── Hero canvas stage ─── */
/* Three mocks overlap and float idly — gives the Hero a "living"    *
 * floating-window impression without a binary screenshot.           */

.marketing-canvas-stage {
  position: relative;
  width: 100%;
  aspect-ratio: 4 / 3;
  isolation: isolate;
}

.marketing-canvas-stage::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: var(--radius-lg);
  background:
    radial-gradient(
      circle at 30% 20%,
      rgba(15, 118, 255, 0.08) 0%,
      transparent 60%
    ),
    radial-gradient(
      circle at 80% 80%,
      rgba(15, 118, 255, 0.06) 0%,
      transparent 55%
    );
  z-index: -1;
}

.marketing-canvas-stage__slot {
  position: absolute;
  width: 62%;
  animation: marketing-mock-float 7s ease-in-out infinite;
  will-change: transform;
}

.marketing-canvas-stage__slot--a {
  top: 2%;
  left: 4%;
  animation-delay: 0s;
  z-index: 3;
}
.marketing-canvas-stage__slot--b {
  top: 30%;
  right: 2%;
  width: 58%;
  animation-delay: -2.3s;
  z-index: 2;
}
.marketing-canvas-stage__slot--c {
  bottom: 2%;
  left: 10%;
  width: 60%;
  animation-delay: -4.6s;
  z-index: 1;
}

/* ─── Live canvas demo (draggable) ─── */
/* Container for react-rnd wrappers. We hand react-rnd absolute      *
 * positioning — it sets `position: absolute` + inline transforms on *
 * its own root node, so our container must be `position: relative`  *
 * and clip on both axes.                                            */

.marketing-live-canvas {
  position: relative;
  width: 100%;
  max-width: 1100px;
  margin: 56px auto 0;
  height: 520px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  background:
    radial-gradient(
      circle at 20% 30%,
      rgba(15, 118, 255, 0.06) 0%,
      transparent 55%
    ),
    var(--bg-surface);
  overflow: hidden;
}

.marketing-live-canvas__hint {
  position: absolute;
  top: 12px;
  left: 16px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: var(--radius-full);
  background: var(--bg-base);
  border: 1px solid var(--border);
  font-size: 0.75rem;
  color: var(--text-secondary);
  z-index: 10;
  pointer-events: none;
}

@media (max-width: 768px) {
  .marketing-live-canvas {
    height: 420px;
    margin-top: 32px;
  }
}

/* ─── Keyframes ─── */

@keyframes marketing-mock-float {
  0%, 100% {
    transform: translateY(0) rotate(-0.2deg);
  }
  50% {
    transform: translateY(-8px) rotate(0.2deg);
  }
}

@keyframes marketing-mock-pulse {
  0%, 100% {
    opacity: 1;
    box-shadow: 0 0 0 0 rgba(15, 118, 255, 0.35);
  }
  50% {
    opacity: 0.6;
    box-shadow: 0 0 0 6px rgba(15, 118, 255, 0);
  }
}

@keyframes marketing-mock-blink {
  50% { opacity: 0; }
}

@keyframes marketing-mock-shimmer {
  0% { background-position: -200px 0; }
  100% { background-position: 200px 0; }
}

@media (prefers-reduced-motion: reduce) {
  .marketing-canvas-stage__slot,
  .marketing-mock__dot--pulse,
  .marketing-mock__caret {
    animation: none !important;
  }
}
```

- [ ] **Step 2: Visually verify css is syntactically valid**

Run: `cd apps/web && pnpm tsc --noEmit`
Expected: no changes in TypeScript output (CSS isn't typechecked but
this confirms we didn't break an import). `pnpm lint` if the repo has
a CSS linter — if the script doesn't exist, skip.

- [ ] **Step 3: Commit**

```bash
git add apps/web/styles/marketing.css
git commit -m "feat(web): add marketing-mock CSS layer for in-page UI mockups"
```

---

## Phase B — Mock components

### Task B1: Build the reusable `MockWindow` chrome

**Files:**
- Create: `apps/web/components/marketing/mocks/MockWindow.tsx`

- [ ] **Step 1: Create the file**

```tsx
import type { ReactNode } from "react";

interface MockWindowProps {
  title: string;
  children: ReactNode;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Marketing-only window chrome. Mirrors the real WindowManager frame
 * at a smaller scale (traffic lights + title + bordered body). All
 * three feature mocks render inside this shell so the hero, the
 * features, and the live-canvas demo share one visual language.
 *
 * Server component — no state, no refs.
 */
export default function MockWindow({
  title,
  children,
  className,
  style,
}: MockWindowProps) {
  return (
    <div
      className={`marketing-mock${className ? ` ${className}` : ""}`}
      style={style}
      aria-hidden="true"
    >
      <div className="marketing-mock__titlebar">
        <div className="marketing-mock__lights">
          <span className="marketing-mock__light marketing-mock__light--red" />
          <span className="marketing-mock__light marketing-mock__light--yellow" />
          <span className="marketing-mock__light marketing-mock__light--green" />
        </div>
        <span className="marketing-mock__title">{title}</span>
      </div>
      <div className="marketing-mock__body">{children}</div>
    </div>
  );
}
```

`aria-hidden="true"` — mockups are decorative; the real information
is in the adjacent `<h3>` + body copy.

### Task B2: Build `MemoryMock` — feature 1 content

**Files:**
- Create: `apps/web/components/marketing/mocks/MemoryMock.tsx`

- [ ] **Step 1: Create the file**

```tsx
import MockWindow from "./MockWindow";

/**
 * Feature 1 — "持久记忆". Shows three memory rows extracted from a
 * client conversation. The last row ends with a blinking caret to
 * suggest it's being written in real-time, reinforcing the
 * "auto-extracted" promise of the feature.
 */
export default function MemoryMock({ style }: { style?: React.CSSProperties }) {
  return (
    <MockWindow title="Memory · Sarah Chen" style={style}>
      <div className="marketing-mock__row">
        <span className="marketing-mock__row-label">Quote</span>
        <span className="marketing-mock__row-value">$18K, delivery in 6 weeks</span>
      </div>
      <div className="marketing-mock__row">
        <span className="marketing-mock__row-label">Prefers</span>
        <span className="marketing-mock__row-value">Async updates, no weekly calls</span>
      </div>
      <div className="marketing-mock__row">
        <span className="marketing-mock__row-label">Next</span>
        <span className="marketing-mock__row-value">
          Send revised SOW by Fri
          <span className="marketing-mock__caret" />
        </span>
      </div>
    </MockWindow>
  );
}
```

### Task B3: Build `FollowupMock` — feature 2 content

**Files:**
- Create: `apps/web/components/marketing/mocks/FollowupMock.tsx`

- [ ] **Step 1: Create the file**

```tsx
import MockWindow from "./MockWindow";

/**
 * Feature 2 — "跟进提醒". Two due-today items with pulsing brand-blue
 * dots + one 45-day dormant client warning in amber. The pulse is the
 * "nudge" motion; no timer or wall-clock logic — it's purely visual.
 */
export default function FollowupMock({ style }: { style?: React.CSSProperties }) {
  return (
    <MockWindow title="Follow-ups · Due today" style={style}>
      <div className="marketing-mock__row">
        <span className="marketing-mock__dot marketing-mock__dot--pulse" />
        <span className="marketing-mock__row-value">
          Send proposal to <strong>Lisa Patel</strong> · promised Mon
        </span>
      </div>
      <div className="marketing-mock__row">
        <span className="marketing-mock__dot marketing-mock__dot--pulse" />
        <span className="marketing-mock__row-value">
          Revise Q3 SOW for <strong>Sarah Chen</strong>
        </span>
      </div>
      <div className="marketing-mock__row">
        <span className="marketing-mock__dot marketing-mock__dot--amber" />
        <span className="marketing-mock__row-value">
          <strong>David Kim</strong> — 45 days since last reply
        </span>
      </div>
    </MockWindow>
  );
}
```

### Task B4: Build `DigestMock` — feature 3 content

**Files:**
- Create: `apps/web/components/marketing/mocks/DigestMock.tsx`

- [ ] **Step 1: Create the file**

```tsx
import MockWindow from "./MockWindow";

/**
 * Feature 3 — "每周反思". Monday digest preview. Four compressed
 * bullets giving the feeling of a "weekly at a glance". No motion —
 * this one is intentionally calm to contrast with the pulsing
 * FollowupMock.
 */
export default function DigestMock({ style }: { style?: React.CSSProperties }) {
  return (
    <MockWindow title="Monday Digest · Wk 16" style={style}>
      <div className="marketing-mock__row">
        <span className="marketing-mock__row-label">Done</span>
        <span className="marketing-mock__row-value">
          14 conversations · 6 clients touched
        </span>
      </div>
      <div className="marketing-mock__row">
        <span className="marketing-mock__row-label">Overdue</span>
        <span className="marketing-mock__row-value">
          2 promises past due — Lisa, Marco
        </span>
      </div>
      <div className="marketing-mock__row">
        <span className="marketing-mock__row-label">Drift</span>
        <span className="marketing-mock__row-value">
          Sarah's scope +32% vs. original SOW
        </span>
      </div>
    </MockWindow>
  );
}
```

### Task B5: Commit mocks

- [ ] **Step 1: Verify mocks typecheck**

Run: `cd apps/web && pnpm tsc --noEmit`
Expected: clean (no new errors).

- [ ] **Step 2: Commit**

```bash
git add apps/web/components/marketing/mocks/
git commit -m "feat(web): add MockWindow + Memory/Followup/Digest marketing mocks"
```

---

## Phase C — Hero canvas stage

### Task C1: Build `HeroCanvasStage`

**Files:**
- Create: `apps/web/components/marketing/HeroCanvasStage.tsx`

- [ ] **Step 1: Create the file**

```tsx
import MemoryMock from "./mocks/MemoryMock";
import FollowupMock from "./mocks/FollowupMock";
import DigestMock from "./mocks/DigestMock";

/**
 * The right half of the Hero. Three mocks overlap and float idly on
 * a soft blue stage — the first picture a visitor sees of "what this
 * product looks like". No drag here (that's LiveCanvasDemo's job) —
 * this stays calm and decorative.
 *
 * Server component. Motion is CSS-only.
 */
export default function HeroCanvasStage() {
  return (
    <div className="marketing-canvas-stage">
      <div className="marketing-canvas-stage__slot marketing-canvas-stage__slot--a">
        <MemoryMock />
      </div>
      <div className="marketing-canvas-stage__slot marketing-canvas-stage__slot--b">
        <FollowupMock />
      </div>
      <div className="marketing-canvas-stage__slot marketing-canvas-stage__slot--c">
        <DigestMock />
      </div>
    </div>
  );
}
```

### Task C2: Swap the Hero demo placeholder

**Files:**
- Modify: `apps/web/components/marketing/HeroSection.tsx`

- [ ] **Step 1: Replace the placeholder div**

In `HeroSection.tsx`, replace the entire
`<div className="marketing-hero__demo marketing-fade-in marketing-fade-in--delay-2">…</div>`
block (lines 43–57 of the current file) with:

```tsx
<div className="marketing-hero__demo-wrap marketing-fade-in marketing-fade-in--delay-2">
  <HeroCanvasStage />
</div>
```

And add the import at the top alongside the existing imports:

```tsx
import HeroCanvasStage from "./HeroCanvasStage";
```

- [ ] **Step 2: Remove the dashed-border styling for the old demo**

In `apps/web/styles/marketing.css`, locate the
`.marketing-hero__demo { … }` rule (starting around line 167). Leave
it in place (the class still exists, we renamed our wrapper to
`marketing-hero__demo-wrap` to avoid the dashed border). Add a new
rule directly below the existing `.marketing-hero__demo` block:

```css
.marketing-hero__demo-wrap {
  position: relative;
  width: 100%;
}
```

This gives the new wrapper a clean container without inheriting the
placeholder's dashed border.

- [ ] **Step 3: Run dev server and visually verify**

```bash
cd apps/web && pnpm dev
```

Open `http://localhost:3000/zh`. Expected:
- Hero right side shows three floating mock windows (Memory /
  Follow-ups / Monday Digest)
- Windows drift up-down subtly (≈8px, 7s period)
- No dashed border, no "30 秒产品导览 · 演示视频占位" text

- [ ] **Step 4: Commit**

```bash
git add apps/web/components/marketing/HeroCanvasStage.tsx \
        apps/web/components/marketing/HeroSection.tsx \
        apps/web/styles/marketing.css
git commit -m "feat(web): replace hero demo placeholder with HeroCanvasStage"
```

---

## Phase D — Feature media swap

### Task D1: Replace the three feature placeholders

**Files:**
- Modify: `apps/web/components/marketing/FeaturesSection.tsx`

- [ ] **Step 1: Rewrite the component**

Replace the entire contents of
`apps/web/components/marketing/FeaturesSection.tsx` with:

```tsx
import { getTranslations } from "next-intl/server";
import { Brain, Bell, CalendarCheck } from "lucide-react";

import MemoryMock from "./mocks/MemoryMock";
import FollowupMock from "./mocks/FollowupMock";
import DigestMock from "./mocks/DigestMock";

const FEATURE_ICONS = {
  1: Brain,
  2: Bell,
  3: CalendarCheck,
} as const;

// Map feature index → mock component. Kept here (not in mocks/) so
// the feature→mock pairing is visible at the call site.
const FEATURE_MOCKS = {
  1: MemoryMock,
  2: FollowupMock,
  3: DigestMock,
} as const;

type FeatureKey = 1 | 2 | 3;

export default async function FeaturesSection() {
  const t = await getTranslations("marketing");
  const features: FeatureKey[] = [1, 2, 3];

  return (
    <section className="marketing-section" id="features">
      <div className="marketing-inner">
        <div
          className="marketing-inner--narrow mb-10 md:mb-16"
          style={{ textAlign: "center", margin: "0 auto" }}
        >
          <span className="marketing-eyebrow">{t("features.kicker")}</span>
          <h2 className="marketing-h2 font-display tracking-tight text-3xl md:text-4xl lg:text-5xl">
            {t("features.title")}
          </h2>
        </div>

        {features.map((i) => {
          const Icon = FEATURE_ICONS[i];
          const Mock = FEATURE_MOCKS[i];
          const reverse = i % 2 === 0;
          return (
            <div
              key={i}
              className={`marketing-feature${reverse ? " marketing-feature--reverse" : ""}`}
            >
              <div className="marketing-feature__copy">
                <div className="marketing-problem-card__icon" style={{ marginBottom: 0 }}>
                  <Icon size={20} strokeWidth={2} />
                </div>
                <span className="marketing-eyebrow" style={{ marginBottom: 0 }}>
                  {t(`feature${i}.eyebrow`)}
                </span>
                <h3 className="marketing-h3 font-display tracking-tight text-xl md:text-2xl">
                  {t(`feature${i}.title`)}
                </h3>
                <p className="marketing-body text-base md:text-lg leading-relaxed">
                  {t(`feature${i}.body`)}
                </p>
                <ul className="marketing-feature__bullets">
                  <li className="marketing-feature__bullet">
                    {t(`feature${i}.bullets.0`)}
                  </li>
                  <li className="marketing-feature__bullet">
                    {t(`feature${i}.bullets.1`)}
                  </li>
                  <li className="marketing-feature__bullet">
                    {t(`feature${i}.bullets.2`)}
                  </li>
                </ul>
              </div>
              <div className="marketing-feature__media-wrap">
                <Mock />
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Add the wrapper class to `marketing.css`**

The old `.marketing-feature__media` rule has a dashed border + flex
centering we don't want. Append to the end of `marketing.css`:

```css
.marketing-feature__media-wrap {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

@media (min-width: 1024px) {
  .marketing-feature__media-wrap {
    max-width: 520px;
    margin-inline: auto;
  }
}
```

The old `.marketing-feature__media` class stays in the stylesheet
unreferenced — leave it; another branch may still use it, and the
dead CSS cost is negligible.

- [ ] **Step 3: Visually verify**

Reload `http://localhost:3000/zh`. Expected:
- Feature 1 (持久记忆) → MemoryMock on right
- Feature 2 (跟进提醒) → FollowupMock on left (reverse layout)
- Feature 3 (每周反思) → DigestMock on right
- Each mock is full-width at the mock's natural aspect, no dashed
  border, no "截图占位" text

- [ ] **Step 4: Commit**

```bash
git add apps/web/components/marketing/FeaturesSection.tsx \
        apps/web/styles/marketing.css
git commit -m "feat(web): swap feature placeholders for Memory/Followup/Digest mocks"
```

---

## Phase E — Live canvas demo

### Task E1: Add i18n keys for the hint tooltip

**Files:**
- Modify: `apps/web/messages/zh/marketing.json`
- Modify: `apps/web/messages/en/marketing.json`

- [ ] **Step 1: Add zh keys**

In `apps/web/messages/zh/marketing.json`, locate the `"screenshot.placeholder.hint"` line and add these four keys directly below it (before the comma that ends that group — or just before `"pricing.kicker"`):

```json
  "screenshot.canvas.hint": "拖动任意窗口 — 试试看",
  "screenshot.canvas.memory": "记忆",
  "screenshot.canvas.followup": "跟进",
  "screenshot.canvas.digest": "周报",
```

- [ ] **Step 2: Add en keys**

In `apps/web/messages/en/marketing.json`, add the matching keys at
the same location:

```json
  "screenshot.canvas.hint": "Drag any window — try it",
  "screenshot.canvas.memory": "Memory",
  "screenshot.canvas.followup": "Follow-ups",
  "screenshot.canvas.digest": "Digest",
```

### Task E2: Build `LiveCanvasDemo`

**Files:**
- Create: `apps/web/components/marketing/LiveCanvasDemo.tsx`

- [ ] **Step 1: Confirm `react-rnd` is available**

Run: `cd apps/web && node -e "require.resolve('react-rnd')"`
Expected: prints a path (no error). If it errors, run `pnpm add
react-rnd` first.

- [ ] **Step 2: Create the component**

```tsx
"use client";

import { useState, useRef, useEffect } from "react";
import { Rnd } from "react-rnd";
import { MousePointer2 } from "lucide-react";
import { useTranslations } from "next-intl";

import MemoryMock from "./mocks/MemoryMock";
import FollowupMock from "./mocks/FollowupMock";
import DigestMock from "./mocks/DigestMock";

interface WindowState {
  id: string;
  x: number;
  y: number;
  component: React.ComponentType<{ style?: React.CSSProperties }>;
}

// Starting layout is tuned for a 1100x520 canvas. We scale down
// proportionally when the container is narrower (mobile).
const INITIAL_LAYOUT: readonly WindowState[] = [
  { id: "memory",   x: 40,  y: 60,  component: MemoryMock },
  { id: "followup", x: 420, y: 180, component: FollowupMock },
  { id: "digest",   x: 200, y: 320, component: DigestMock },
] as const;

const WINDOW_WIDTH = 340;

/**
 * Below-the-fold interactive demo — the "it's really a canvas" proof.
 * Each mock is wrapped in react-rnd; drag-only (no resize). Position
 * lives in component state — intentionally not persisted, a fresh
 * visitor should see the same arrangement every load. Windows come
 * forward on click via a monotonic z-index counter.
 */
export default function LiveCanvasDemo() {
  const t = useTranslations("marketing");
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>(
    Object.fromEntries(INITIAL_LAYOUT.map((w) => [w.id, { x: w.x, y: w.y }])),
  );
  const [order, setOrder] = useState<string[]>(INITIAL_LAYOUT.map((w) => w.id));
  const zCounterRef = useRef(0);

  // Scale positions for narrow viewports. We measure the container
  // width once on mount + on window resize; no ResizeObserver needed
  // — the demo is not mission-critical.
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [scale, setScale] = useState(1);
  useEffect(() => {
    function update() {
      const el = containerRef.current;
      if (!el) return;
      const w = el.offsetWidth;
      setScale(Math.min(1, w / 1100));
    }
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  function bringForward(id: string) {
    zCounterRef.current += 1;
    setOrder((prev) => [...prev.filter((x) => x !== id), id]);
  }

  return (
    <div className="marketing-live-canvas" ref={containerRef}>
      <div className="marketing-live-canvas__hint">
        <MousePointer2 size={14} strokeWidth={2} />
        {t("screenshot.canvas.hint")}
      </div>
      {INITIAL_LAYOUT.map((w) => {
        const Mock = w.component;
        const pos = positions[w.id];
        const z = order.indexOf(w.id) + 1;
        return (
          <Rnd
            key={w.id}
            size={{ width: WINDOW_WIDTH * scale, height: "auto" }}
            position={{ x: pos.x * scale, y: pos.y * scale }}
            onDragStart={() => bringForward(w.id)}
            onDragStop={(_, d) => {
              setPositions((p) => ({
                ...p,
                [w.id]: { x: d.x / scale, y: d.y / scale },
              }));
            }}
            bounds="parent"
            enableResizing={false}
            dragHandleClassName="marketing-mock__titlebar"
            style={{ zIndex: z, cursor: "grab" }}
          >
            <Mock />
          </Rnd>
        );
      })}
    </div>
  );
}
```

Notes on the choices:
- `dragHandleClassName="marketing-mock__titlebar"` — the user must
  grab the title bar, exactly like the real WindowManager. Body rows
  stay click-selectable (future-proof for content interaction).
- `bounds="parent"` — windows cannot escape the canvas.
- `enableResizing={false}` — resizing is an expert feature; the
  marketing demo wants to feel immediate.
- No `localStorage` persistence — a fresh visitor must always see the
  same starting stack (the "three floating windows" shape is part of
  the pitch).

### Task E3: Swap the Screenshot section

**Files:**
- Modify: `apps/web/components/marketing/ScreenshotSection.tsx`

- [ ] **Step 1: Rewrite the component**

Replace the contents of `ScreenshotSection.tsx` with:

```tsx
import { getTranslations } from "next-intl/server";

import LiveCanvasDemo from "./LiveCanvasDemo";

export default async function ScreenshotSection() {
  const t = await getTranslations("marketing");
  return (
    <section className="marketing-section" style={{ paddingTop: 48 }}>
      <div className="marketing-inner">
        <div
          className="marketing-inner--narrow"
          style={{ textAlign: "center", margin: "0 auto" }}
        >
          <span className="marketing-eyebrow">{t("screenshot.kicker")}</span>
          <h2 className="marketing-h2 font-display tracking-tight text-3xl md:text-4xl lg:text-5xl">
            {t("screenshot.title")}
          </h2>
          <p
            className="marketing-lead text-lg md:text-xl leading-relaxed"
            style={{ marginTop: 16, maxWidth: 620, marginInline: "auto" }}
          >
            {t("screenshot.sub")}
          </p>
        </div>

        <LiveCanvasDemo />
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Visually verify**

Reload `http://localhost:3000/zh`. Scroll past the features. Expected:
- The big placeholder with dashed border is gone
- A 1100×520 canvas containing three mock windows
- Top-left corner has a `"拖动任意窗口 — 试试看"` hint pill
- Clicking and dragging any window's *title bar* moves it
- Clicking a window brings it to the front (z-index)
- Windows cannot be dragged outside the canvas

- [ ] **Step 3: Commit**

```bash
git add apps/web/components/marketing/LiveCanvasDemo.tsx \
        apps/web/components/marketing/ScreenshotSection.tsx \
        apps/web/messages/zh/marketing.json \
        apps/web/messages/en/marketing.json
git commit -m "feat(web): replace screenshot placeholder with LiveCanvasDemo"
```

---

## Phase F — Auth dead-end fix

### Task F1: Add i18n keys for the auth header

**Files:**
- Modify: `apps/web/messages/zh/auth.json`
- Modify: `apps/web/messages/en/auth.json`

- [ ] **Step 1: Find existing `footer` keys in both files**

Run: `grep -n '"footer' apps/web/messages/zh/auth.json`
You'll find a `footer.terms` and `footer.privacy` entry. Add the new
keys near the top of the JSON (siblings of `footer.terms`). If the
file already has a section labeled for brand, add them there
instead.

- [ ] **Step 2: Add zh keys**

Add to `apps/web/messages/zh/auth.json`:

```json
  "brand.tagline": "能记住所有客户的 AI 笔记本",
  "brand.back": "返回首页",
```

- [ ] **Step 3: Add en keys**

Add to `apps/web/messages/en/auth.json`:

```json
  "brand.tagline": "The AI notebook that remembers every client",
  "brand.back": "Back to home",
```

### Task F2: Build `AuthBrandHeader`

**Files:**
- Create: `apps/web/components/marketing/AuthBrandHeader.tsx`

- [ ] **Step 1: Create the file**

```tsx
import { ArrowLeft } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";

/**
 * Auth-only header. Replaces the bare wordmark on login / register /
 * forgot-password so returning users who got bounced from /app/* can
 * (a) see what product they're logging into and (b) exit to the
 * marketing page without manually editing the URL.
 *
 * Layout mirrors the previous wordmark block's position (top-left),
 * but adds the tagline beside the brand and a muted "← 返回首页"
 * link at the top-right.
 */
export default async function AuthBrandHeader() {
  const t = await getTranslations("auth");
  const tMarketing = await getTranslations("marketing");

  return (
    <header className="flex items-center justify-between px-6 pt-8 md:px-10">
      <Link
        href="/"
        className="inline-flex items-center gap-3 text-sm"
        aria-label={tMarketing("brand.name")}
      >
        <span className="h-2.5 w-2.5 rounded-sm bg-[var(--brand-v2)]" />
        <span className="font-display font-semibold tracking-tight">
          {tMarketing("brand.name")}
        </span>
        <span className="hidden text-[var(--text-secondary)] md:inline">
          · {t("brand.tagline")}
        </span>
      </Link>

      <Link
        href="/"
        className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] px-3 py-1.5 text-xs font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-surface)] hover:text-[var(--text-primary)]"
      >
        <ArrowLeft size={12} strokeWidth={2.5} />
        {t("brand.back")}
      </Link>
    </header>
  );
}
```

### Task F3: Swap auth layout to use the header

**Files:**
- Modify: `apps/web/app/[locale]/(auth)/layout.tsx`

- [ ] **Step 1: Replace the inline header**

Replace the entire `<header>…</header>` block (lines 17–26 of the
current file) with:

```tsx
<AuthBrandHeader />
```

And add the import at the top:

```tsx
import AuthBrandHeader from "@/components/marketing/AuthBrandHeader";
```

Also remove the now-unused `tMarketing` import and local call in the
layout, since `AuthBrandHeader` owns that translation fetch.
Specifically, delete these lines from the existing layout:

```tsx
const tMarketing = await getTranslations("marketing");
```

(Leave the `const tAuth = await getTranslations("auth");` — it's
still used by the footer below.)

- [ ] **Step 2: Visually verify**

```bash
# Dev server should still be running; if not:
cd apps/web && pnpm dev
```

Open `http://localhost:3000/zh/login`. Expected:
- Top-left: `MRNote · 能记住所有客户的 AI 笔记本` (tagline hidden <
  768px)
- Top-right: small pill-shaped `← 返回首页` link
- Form, field labels, footer unchanged

Click `← 返回首页` — should navigate to `/zh` (marketing).

- [ ] **Step 3: Commit**

```bash
git add apps/web/components/marketing/AuthBrandHeader.tsx \
        apps/web/app/[locale]/\(auth\)/layout.tsx \
        apps/web/messages/zh/auth.json \
        apps/web/messages/en/auth.json
git commit -m "feat(web): give auth pages tagline + back-to-home link"
```

---

## Phase G — Verification

### Task G1: Add a Playwright smoke test

**Files:**
- Create: `apps/web/tests/marketing-homepage.spec.ts`

- [ ] **Step 1: Look at the existing foundation spec's setup**

Run: `head -30 apps/web/tests/foundation.spec.ts`
Note: the file's `test.describe` header and any shared fixture. The
new spec must match that pattern (base URL, locale, etc.). If
`foundation.spec.ts` uses a `test.beforeEach` that needs auth, our
new spec must *not* include that beforeEach — marketing is unauth.

- [ ] **Step 2: Create the spec**

```ts
import { test, expect } from "@playwright/test";

/**
 * Marketing homepage smoke — just proves the mocks render and the
 * live-canvas hint is visible. Full visual regression lives
 * elsewhere (or nowhere — we're trading that off for velocity).
 */
test.describe("Marketing homepage", () => {
  test("renders hero canvas stage + all three mocks", async ({ page }) => {
    await page.goto("/zh");

    // Hero title still there — sanity check the page rendered at all.
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    // Hero canvas stage — three MockWindow chromes inside it.
    // The stage has the class .marketing-canvas-stage; each slot
    // contains one .marketing-mock.
    const stage = page.locator(".marketing-canvas-stage");
    await expect(stage).toBeVisible();
    await expect(stage.locator(".marketing-mock")).toHaveCount(3);

    // Features section has another three mocks (one per feature).
    // Total on the page before LiveCanvasDemo: 3 hero + 3 features = 6.
    // LiveCanvasDemo adds another 3, so total 9.
    const allMocks = page.locator(".marketing-mock");
    await expect(allMocks).toHaveCount(9);

    // Live canvas hint pill is visible.
    await expect(
      page.locator(".marketing-live-canvas__hint"),
    ).toBeVisible();
  });

  test("auth page shows back-to-home link", async ({ page }) => {
    await page.goto("/zh/login");
    const backLink = page.getByRole("link", { name: /返回首页/ });
    await expect(backLink).toBeVisible();
    await backLink.click();
    await expect(page).toHaveURL(/\/zh\/?$/);
  });
});
```

- [ ] **Step 3: Run it**

```bash
cd apps/web && pnpm playwright test marketing-homepage.spec.ts
```

Expected: 2 passed. If the count assertion fails at exactly 9, first
visually verify both pages rendered correctly (open them in the
browser) — an off-by-one almost certainly means a slot didn't render
(e.g. missing import). If off count is correct but the hero is
still showing the dashed-border placeholder, the `HeroSection.tsx`
swap in Phase C was incomplete.

- [ ] **Step 4: Run the full existing marketing-adjacent suite**

```bash
cd apps/web && pnpm playwright test foundation
```

Expected: all existing foundation tests still pass. If one regresses
because the hero markup changed (e.g. an `expect` on the dashed
placeholder text), update that assertion to match the new markup —
the underlying test intent is still valid.

- [ ] **Step 5: Full unit test run**

```bash
cd apps/web && pnpm test --run
```

Expected: pass. Unit tests don't touch marketing directly, so this
is a regression catch-net.

### Task G2: Manual dev-server walkthrough

- [ ] **Step 1: Start dev server, step through the golden path**

```bash
cd apps/web && pnpm dev
```

Open `http://localhost:3000/zh` and verify in order:
1. Hero: three floating mock windows drift subtly. No text placeholder.
2. Problem section: unchanged (three icon cards — we didn't touch it).
3. Features section: three rows, each with a mock on the media side,
   alternating left/right. Memory has blinking caret; Followups has
   pulsing blue dots + one amber dot.
4. Screenshot section: the big dashed placeholder is gone; replaced
   by a canvas with three draggable windows. Drag one by its title
   bar — it follows the cursor. Release — it stays. Try to drag
   off-canvas — it stops at the edge. Click a different window —
   it comes to the front.
5. Pricing section: unchanged.
6. CTA section: unchanged.
7. Click "登录" in the header (or go to `/zh/login`). Top-left should
   show `MRNote · 能记住所有客户的 AI 笔记本`; top-right should have
   a `← 返回首页` pill. Click the pill → back to `/zh`.

- [ ] **Step 2: Check `prefers-reduced-motion`**

In Chrome DevTools → Rendering → Emulate CSS media feature
`prefers-reduced-motion: reduce`. Reload `/zh`. Expected:
- Floating motion on hero mocks is frozen (no up-down drift)
- Pulsing dots on FollowupMock are frozen (solid blue, no halo)
- Caret on MemoryMock does not blink
- LiveCanvasDemo dragging still works — user-initiated, not
  auto-motion.

- [ ] **Step 3: Check English locale**

Open `http://localhost:3000/en`. Everything should render; the hint
pill should say "Drag any window — try it". Hero copy is English.

- [ ] **Step 4: Commit any last touch-ups + push**

If G1 forced any tiny fix-up, commit it. If everything passed:

```bash
git log --oneline -10
```

Expected: 6 new commits on top of the pre-plan HEAD (Phase A, B, C,
D, E, F, plus any G1/G2 fixups).

No push — the user can open a PR separately.

---

## Out of scope (explicit non-goals)

- **Full visual regression testing.** We're not adding Percy /
  Chromatic / Playwright screenshot baselines. The smoke test in G1
  counts DOM nodes; visual changes pass silently. Acceptable
  tradeoff — the mocks are a marketing asset, not business logic.
- **SSR-safe drag.** `react-rnd` is client-only, which is why
  `LiveCanvasDemo` is a `"use client"` component. No prerender
  fallback; the canvas renders empty for ≤100ms on hydration and
  that's fine for below-the-fold.
- **Custom cursor during drag.** `react-rnd` uses the browser default
  grab cursor. Good enough for v1.
- **Mobile drag.** It works on touch (react-rnd handles it), but the
  canvas is cramped on <375px. Acceptable — the marketing pitch
  survives fine on a phone even if dragging is awkward.
- **Copy edits / new i18n content.** The plan only adds the four
  strings LiveCanvasDemo needs + the two strings AuthBrandHeader
  needs. Any broader rewrite is a separate task.
- **Landing routing change.** The `"/app/* → /login"` bounce in
  `proxy.ts:166` is unchanged. Phase F makes the login page less of
  a dead-end; the smart-root-redirect discussed in conversation is
  not part of this plan (it touches auth policy, deserves its own).

---

## Self-Review

**Spec coverage.** The plan covers every upgrade we agreed on:
(1) Hero real demo → Phase C; (2) Real feature screenshots → Phase D;
(3) Interactive live canvas → Phase E; (4) Login dead-end fix →
Phase F. Excluded items listed under "Out of scope" are explicit
non-goals.

**Placeholder scan.** Every step has exact paths, exact commands,
full code blocks (no "fill in details"). The "if G1 forced a
touch-up" line in G2 step 4 is conditional, not a placeholder for
missing content.

**Type consistency.** `MockWindow` prop signature
(`{ title, children, className?, style? }`) stays the same across all
three content mocks. `LiveCanvasDemo`'s `WindowState.component` type
matches what `MockWindow` exposes via `style` prop. `FEATURE_MOCKS`
keys match `FEATURE_ICONS` keys (both `1 | 2 | 3`).
