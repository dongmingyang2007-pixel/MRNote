# Role-Personalized Landing — Design Spec

**Date:** 2026-04-20
**Status:** draft
**Scope:** `apps/web` marketing homepage (`/` and `/en`)

## 1. Goal

Lift marketing homepage conversion by letting visitors opt-in to a role (研究生 / 律师 / 医生 / 老师 / 创业者 / 设计师). When a role is picked, the page shows a **role-exclusive section** with content tailored to that occupation (demo scenario, template pack,专属优惠 offer) plus social proof (stat count, testimonial, institution logos). The rest of the homepage stays generic.

The flow is **opt-in and dismissible** — visitors who don't pick see a generic homepage and are not blocked.

## 2. Non-goals

- **No full-page rewrite per role.** Hero headline, ProblemSection, FeaturesSection, ScreenshotSection, PricingSnapshotSection, CTAFooterSection all stay role-neutral. Only a small Hero badge + the new ExclusiveSection change.
- **No paid / third-party ads.** "广告" here means first-party promotional content MRNote produces. No AdSense, no partner feeds.
- **No post-signup personalization.** This spec is anonymous marketing-page-only. The `/app` in-app experience already has its own onboarding wizard and is untouched.
- **No A/B testing infra in this spec.** Instrumentation hooks are in scope (events), but A/B framework is future work.
- **No URL-parameter deep link (`?role=law`) in v1.** Can be added later; v1 uses cookie + click selector only.

## 3. User flow

```
[Visitor arrives at /]
      │
      ▼
[Sees generic Hero + normal sections + ExclusiveSection (empty state)]
      │
      ├─ (ignores) ───▶ standard homepage experience, no friction
      │
      └─ (clicks a role chip in ExclusiveSection)
             │
             ▼
      [ExclusiveSection expands to show 3 cards + testimonial + logo strip]
      [Hero gets a small "✨ 为 X 定制" badge above the headline]
      [Role stored in cookie `mrai_landing_role` for 30 days]
             │
             ├─ (clicks another role) ─▶ content swaps with fade, no reload
             │
             └─ (clicks "切换") ──────▶ returns to empty state, cookie cleared
```

Role selection persists across page reloads via cookie. Returning visitors land on their role automatically.

## 4. UI structure

### 4.1 Page composition (in order)

| # | Section | Role-sensitive? | File |
|---|---|---|---|
| 1 | `PublicHeader` | no | `components/marketing/PublicHeader.tsx` |
| 2 | `HeroSection` | yes (badge only) | `components/marketing/HeroSection.tsx` |
| 3 | `ProblemSection` | no | — |
| 4 | `FeaturesSection` | no | — |
| 5 | `ScreenshotSection` | no | — |
| 6 | **`ExclusiveSection` (new)** | **yes (primary)** | `components/marketing/ExclusiveSection.tsx` |
| 7 | `PricingSnapshotSection` | no | — |
| 8 | `CTAFooterSection` | no | — |
| 9 | `PublicFooter` | no | — |

ExclusiveSection sits **between ScreenshotSection and PricingSnapshotSection**: visitors see the product's visual pitch first, then "here's what it does for YOU specifically," then pricing.

### 4.2 Hero badge (empty state vs role-selected)

- Empty state: Hero renders unchanged.
- Role selected: Small chip appears above the headline: `✨ 为研究生定制` (teal #0d9488 background, white text, rounded-full, 12px text). No other hero change.

### 4.3 ExclusiveSection layout

**Empty state (no role chosen):**

```
┌─ ✦ 为你精选 · 独家 ────────────────────────────┐
│                                                │
│       选择你的身份，解锁定制内容                 │
│                                                │
│  [⚖️ 律师] [🔬 研究生] [👨‍⚕️ 医生] [👨‍🏫 老师]      │
│  [🚀 创业者] [🎨 设计师]                        │
│                                                │
│   ┌─占位─┐ ┌─占位─┐ ┌─占位─┐                    │
│   │ 淡化 │ │ 淡化 │ │ 淡化 │   ← 3 张灰色占位卡  │
│   └──────┘ └──────┘ └──────┘                    │
│                                                │
└────────────────────────────────────────────────┘
```

**Role-selected state (e.g., 研究生):**

```
┌─ ✦ 为你精选 · 独家 ────────────────────────────┐
│                                                │
│       为研究生打造的 MRNote                      │
│   已有 5,243 名研究生把 MRNote 作为日常研究伙伴   │
│                                                │
│  [⚖️ 律师] [🔬 研究生✓] [👨‍⚕️ 医生] ...  切换 →   │
│                                                │
│  ┌──场景 DEMO────┐ ┌──模板包──────┐ ┌──专属优惠──┐
│  │ 文献综述自动整理│ │ 研究生 5 件套 │ │[独家] edu  │
│  │ [animation]    │ │ 免费导入 →   │ │ Pro 免费6月│
│  │                │ │              │ │ [立即激活→]│
│  └───────────────┘ └──────────────┘ └───────────┘
│                                                │
│  ┌─ 💬 李同学 · 清华大学 计算机博二 ─────────┐    │
│  │ "写论文最痛的一步是把之前读过的文献..."   │    │
│  └─────────────────────────────────────────┘    │
│                                                │
│   使用 MRNote 的研究机构                         │
│   清华 · 北大 · 中科院 · 复旦 · 浙大              │
│                                                │
└────────────────────────────────────────────────┘
```

**Background:** subtle linear-gradient `#f0fdfa → #fff` so the section reads as its own island.

### 4.4 Cards (3-slot contract)

Every role has exactly 3 cards, all required, in this fixed order:

| Slot | Purpose | Emotional trigger |
|---|---|---|
| 1. Scenario demo | Show product in role-specific use | "它真的懂我" (affinity) |
| 2. Template pack | Pre-made MRNote templates for role's workflows | "我今天就能用" (utility) |
| 3. 专属优惠 (exclusive offer) | Role-gated promotion (discount / extended trial / credit) | "只有我能拿" (loss aversion) |

Card 3 uses the **warm accent** `#F97316` for the CTA button and carries a `独家` corner badge; cards 1 and 2 use the neutral card style (white bg, `#e5e7eb` border, teal accent chip).

### 4.5 Social proof trio (below the cards)

Three fixed elements, all role-specific:

- **Stat line** (in the section header): `已有 {count} 名{role}把 MRNote 作为日常{domain_noun}`. Count animates from 0 to target on scroll-into-view (respecting `prefers-reduced-motion`).
- **Testimonial strip**: avatar + 1-sentence quote (≤ 60 汉字) + name/title. One per role.
- **Institution logo row**: 5 text-only logo marks (no bitmap logos in v1 — text branding keeps weight low and avoids permissioning).

## 5. Roles (v1)

| key | 中文 | English | icon | domain_noun (used in stat line) |
|---|---|---|---|---|
| `researcher` | 研究生 | Researcher | 🔬 | 研究伙伴 |
| `lawyer` | 律师 | Lawyer | ⚖️ | 案件助手 |
| `doctor` | 医生 | Doctor | 👨‍⚕️ | 病历助手 |
| `teacher` | 老师 | Teacher | 👨‍🏫 | 教学助手 |
| `founder` | 创业者 | Founder | 🚀 | 创业大脑 |
| `designer` | 设计师 | Designer | 🎨 | 灵感图书馆 |

Emoji icons are used **only inside the role chips**, per the skill's guidance that emoji is not used as general UI icons. Chips sit in a decorative context (selector widget), not a navigation icon context, so this is acceptable.

No "Other" option in v1. Unselected = generic experience (already a first-class path). Adding "Other" would duplicate that path without adding signal.

## 6. Content model

Role content lives in a single typed module, not in translations, because it's structured and versioned together.

`apps/web/lib/marketing/role-content.ts`:

```ts
export type RoleKey = "researcher" | "lawyer" | "doctor" | "teacher" | "founder" | "designer";

export interface RoleContent {
  key: RoleKey;
  label: { zh: string; en: string };
  icon: string;                         // emoji for chip
  domainNoun: { zh: string; en: string };
  stat: { count: number; asOf: string }; // e.g. { count: 5243, asOf: "2026-04" }
  demo: {
    title: { zh: string; en: string };
    description: { zh: string; en: string };
    animationKey: string;               // maps to a CSS/HTML mock in marketing/mocks/
  };
  templatePack: {
    title: { zh: string; en: string };
    items: { zh: string; en: string }[]; // e.g. ["文献卡", "实验日志", ...]
    cta: { zh: string; en: string };
  };
  offer: {
    title: { zh: string; en: string };
    description: { zh: string; en: string };
    cta: { zh: string; en: string };
    href: string;                        // landing URL for the offer flow
  };
  testimonial: {
    quote: { zh: string; en: string };
    name: string;
    title: { zh: string; en: string };
    avatarInitial: string;
  };
  institutions: string[];                // 5 text-only names
}

export const ROLE_CONTENT: Record<RoleKey, RoleContent> = { ... };
```

Both `zh` and `en` are required fields. An English-locale visitor picking 研究生 sees the `en` content; no fallback-to-Chinese silent behavior.

Stat counts are **manually maintained** in v1 with an `asOf` month label shown as "as of YYYY-MM" in a tooltip (for honesty when numbers are round/illustrative). Future: wire to real analytics.

Testimonials require real-person consent before ship. Placeholder "内测用户" attribution allowed for the first release only, flagged in a `// TODO: replace with consented quote` comment.

## 7. Components

| Path | Purpose |
|---|---|
| `components/marketing/ExclusiveSection.tsx` | Top-level section container, handles role state, empty/populated rendering |
| `components/marketing/role-selector/RoleChipRow.tsx` | Horizontal scrollable chip row, active state, keyboard navigable |
| `components/marketing/role-selector/RoleCard.tsx` | Shared card shell for slot 1 & 2 |
| `components/marketing/role-selector/ExclusiveOfferCard.tsx` | Slot-3 card with warm accent + 独家 badge + offer CTA |
| `components/marketing/role-selector/TestimonialStrip.tsx` | Avatar + quote + attribution |
| `components/marketing/role-selector/InstitutionLogoRow.tsx` | Text logo marks, opacity 0.6, fade-in on mount |
| `components/marketing/role-selector/StatCounter.tsx` | Number that animates to target on scroll-into-view, respects `prefers-reduced-motion` |
| `lib/marketing/role-content.ts` | Typed content table (see §6) |
| `hooks/useRoleSelection.ts` | Reads/writes `mrai_landing_role` cookie; exposes `{ role, setRole, clearRole }` |
| `styles/marketing.css` | Add section-specific styles (gradient bg, card shadows, warm CTA color token) |

`ExclusiveSection` is mounted in `apps/web/app/[locale]/page.tsx` between `ScreenshotSection` and `PricingSnapshotSection`.

## 8. Data & persistence

- Cookie name: `mrai_landing_role`.
- Value: one of the `RoleKey` strings.
- Attributes: `path=/`, `max-age=2592000` (30 days), `sameSite=lax`. **Not** `httpOnly` (needs client read).
- Server-side: `/app/[locale]/page.tsx` reads the cookie during SSR and passes `initialRole` prop to `ExclusiveSection` to avoid a flash of empty content for returning visitors.
- `useRoleSelection` hook handles browser-side updates (click → set cookie → setState).

No server API, no DB writes. Role is never sent to the API.

## 9. Interaction details

- **Chip click:** Sets role → cookie written → `ExclusiveSection` transitions content with 200ms fade-out / fade-in (skipped if `prefers-reduced-motion: reduce`). Hero badge appears on next paint.
- **Switch:** "切换" link next to the active chip label; clicking clears the cookie and returns to empty state. Fade, same timing.
- **Keyboard:** Chips are `<button>` elements in a `role="radiogroup"` container. Arrow keys navigate left/right, Enter/Space selects, Escape clears focus. Tab order: chip row → first card CTA → second card CTA → third card CTA → testimonial (non-interactive) → institution row (non-interactive).
- **Focus:** Visible focus ring on chips (`outline: 2px solid #0d9488` `outline-offset: 2px`).
- **Touch targets:** Chips are 36px tall minimum (padding 10px × 16px on a 16px font).

## 10. Accessibility

- Color contrast for all text ≥ 4.5:1 against its background. Warm CTA `#F97316` against white has contrast 3.68 — **only used on buttons ≥ 14px bold**, which meets large-text 3:1.
- Emoji in chips is decorative; chip `aria-label` is the role label without emoji (e.g., `aria-label="研究生"`).
- Section has `aria-label="为你精选 · 独家"` on the outer wrapper.
- Stat counter announces final value to screen readers via `aria-live="polite"` (not each intermediate number).
- `prefers-reduced-motion: reduce`: disable counter animation, fade transitions become instant, logo row fade-in disabled.
- Testimonial avatar uses initial letter (not emoji) — treated as decorative (`aria-hidden="true"`), actual attribution text is the accessible name.

## 11. Analytics

Fire these client events (for future dashboards; no analytics SDK wired in v1 — emit to `console` in dev, noop in prod until we pick a tool):

| Event | When | Properties |
|---|---|---|
| `landing.role.selected` | User picks a role from empty state | `{ role, locale }` |
| `landing.role.switched` | User picks a different role | `{ fromRole, toRole, locale }` |
| `landing.role.cleared` | User clicks "切换" | `{ fromRole, locale }` |
| `landing.offer.clicked` | User clicks Slot-3 CTA | `{ role, offerHref, locale }` |
| `landing.role.restored` | Cookie hydrated on page load | `{ role, locale }` |

These events are the instrumentation story. Wiring to Plausible / PostHog / Amplitude is future work and does not block this spec.

## 12. i18n

Role content lives in `role-content.ts` per §6. Wrapper chrome (section title "为你精选 · 独家", "选择你的身份，解锁定制内容", "切换", empty-state placeholder labels) lives in `messages/{zh,en}/marketing.json` under a new `exclusiveSection` namespace.

Both `/zh` and `/en` routes render the same component; locale determines which content branch is pulled.

## 13. Testing

- **Unit** (Vitest): `useRoleSelection` cookie read/write, stat counter respects reduced-motion, `ExclusiveSection` renders empty vs populated correctly given the `initialRole` prop.
- **Playwright smoke**: visit `/`, click 研究生 chip, assert stat text, Hero badge present, switch to 律师 and assert swap, click 切换 and assert empty state returns.
- **a11y**: `axe` scan on both empty and populated states.

No backend test surface (no API changes).

## 14. Out of scope / future

- URL param deep link (`?role=...`) for SEM landing — defer to v2.
- Real-time stats from analytics backend — v1 uses manual `{ count, asOf }`.
- More than 6 roles — add as real demand surfaces (PM, consultant, investor are the likely next three).
- A/B test framework for testing card layouts / offer copy — defer.
- Bitmap institution logos — text-only in v1.
- Role-aware PricingSnapshot CTAs — if a role is set, could swap the generic CTA for a role-tinted one; **not in this spec**, explicitly kept neutral so pricing reads the same to everyone.

## 15. Open questions

None blocking. Noted items for reviewer:

- Do we want the empty-state placeholder cards to animate (gentle pulse) to draw the eye, or stay static? Spec currently says **static** — animation would fight for attention with the real Hero.
- Stat counts for v1: are we shipping illustrative rounded numbers, or holding the section back until we have real numbers? Spec currently says **illustrative with `asOf` label** for launch.
