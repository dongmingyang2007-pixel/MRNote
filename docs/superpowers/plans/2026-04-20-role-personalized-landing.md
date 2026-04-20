# Role-Personalized Landing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in role selector (研究生 / 律师 / 医生 / 老师 / 创业者 / 设计师) to the marketing homepage that reveals an exclusive section with role-specific content cards (demo, template pack, offer) plus social proof (stat, testimonial, institution logos).

**Architecture:** One new section component `ExclusiveSection` mounted between `ScreenshotSection` and `PricingSnapshotSection` in `app/[locale]/page.tsx`. A typed content table (`lib/marketing/role-content.ts`) drives 6 role variants. A cookie-backed `useRoleSelection` hook handles persistence and SSR hydration. A small conditional badge is added to `HeroSection`. All other sections stay role-neutral.

**Tech Stack:** Next.js 16 (App Router), React 18, next-intl, Vitest + Testing Library (unit), Playwright (e2e), CSS via `marketing.css` classes + minor inline styles.

**Spec reference:** [`docs/superpowers/specs/2026-04-20-role-personalized-landing-design.md`](../specs/2026-04-20-role-personalized-landing-design.md)

---

## File Structure

**New files:**

- `apps/web/lib/marketing/role-content.ts` — `RoleKey`, `RoleContent` types + `ROLE_CONTENT` record (6 roles, zh + en)
- `apps/web/hooks/useRoleSelection.ts` — cookie-backed `{ role, setRole, clearRole }`
- `apps/web/components/marketing/ExclusiveSection.tsx` — section container
- `apps/web/components/marketing/role-selector/RoleChipRow.tsx` — chip selector with radiogroup a11y
- `apps/web/components/marketing/role-selector/RoleCard.tsx` — shared card for demo + template slots
- `apps/web/components/marketing/role-selector/ExclusiveOfferCard.tsx` — offer card with warm CTA + 独家 badge
- `apps/web/components/marketing/role-selector/StatCounter.tsx` — 0→N animation respecting reduced-motion
- `apps/web/components/marketing/role-selector/TestimonialStrip.tsx` — avatar + quote + attribution
- `apps/web/components/marketing/role-selector/InstitutionLogoRow.tsx` — 5 text-only logos
- `apps/web/tests/unit/role-content.test.ts` — content table integrity
- `apps/web/tests/unit/useRoleSelection.test.tsx` — hook R/W via jsdom
- `apps/web/tests/unit/stat-counter.test.tsx` — reduced-motion behavior
- `apps/web/tests/unit/role-chip-row.test.tsx` — click + arrow key nav
- `apps/web/tests/unit/exclusive-section.test.tsx` — empty vs populated
- `apps/web/tests/role-personalized-landing.spec.ts` — Playwright e2e

**Modified files:**

- `apps/web/messages/zh/marketing.json` — add `exclusiveSection.*` keys
- `apps/web/messages/en/marketing.json` — same keys, English
- `apps/web/components/marketing/HeroSection.tsx` — accept `role?: RoleKey | null` prop, conditionally render badge
- `apps/web/app/[locale]/page.tsx` — SSR-read cookie, pass `initialRole` to `HeroSection` + `ExclusiveSection`
- `apps/web/styles/marketing.css` — add `.marketing-exclusive*` classes (section bg, card, chip, warm CTA)

---

## Task 1: Typed role content table

**Files:**
- Create: `apps/web/lib/marketing/role-content.ts`
- Test: `apps/web/tests/unit/role-content.test.ts`

- [ ] **Step 1: Write the failing test**

Create `apps/web/tests/unit/role-content.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { ROLE_CONTENT, ROLE_KEYS, type RoleKey } from "@/lib/marketing/role-content";

describe("ROLE_CONTENT", () => {
  it("defines exactly 6 roles in a fixed order", () => {
    expect(ROLE_KEYS).toEqual([
      "researcher", "lawyer", "doctor", "teacher", "founder", "designer",
    ]);
    expect(Object.keys(ROLE_CONTENT)).toHaveLength(6);
  });

  it.each(["researcher", "lawyer", "doctor", "teacher", "founder", "designer"] as RoleKey[])(
    "role %s has all required fields populated in both locales",
    (key) => {
      const c = ROLE_CONTENT[key];
      expect(c.key).toBe(key);
      expect(c.label.zh.length).toBeGreaterThan(0);
      expect(c.label.en.length).toBeGreaterThan(0);
      expect(c.icon.length).toBeGreaterThan(0);
      expect(c.domainNoun.zh.length).toBeGreaterThan(0);
      expect(c.domainNoun.en.length).toBeGreaterThan(0);
      expect(c.stat.count).toBeGreaterThan(0);
      expect(c.stat.asOf).toMatch(/^\d{4}-\d{2}$/);
      expect(c.demo.title.zh.length).toBeGreaterThan(0);
      expect(c.demo.title.en.length).toBeGreaterThan(0);
      expect(c.demo.description.zh.length).toBeGreaterThan(0);
      expect(c.demo.description.en.length).toBeGreaterThan(0);
      expect(c.demo.animationKey.length).toBeGreaterThan(0);
      expect(c.templatePack.title.zh.length).toBeGreaterThan(0);
      expect(c.templatePack.title.en.length).toBeGreaterThan(0);
      expect(c.templatePack.items.length).toBeGreaterThanOrEqual(3);
      expect(c.templatePack.cta.zh.length).toBeGreaterThan(0);
      expect(c.offer.title.zh.length).toBeGreaterThan(0);
      expect(c.offer.title.en.length).toBeGreaterThan(0);
      expect(c.offer.cta.zh.length).toBeGreaterThan(0);
      expect(c.offer.href.startsWith("/")).toBe(true);
      expect(c.testimonial.quote.zh.length).toBeGreaterThan(0);
      expect(c.testimonial.quote.en.length).toBeGreaterThan(0);
      expect(c.testimonial.name.length).toBeGreaterThan(0);
      expect(c.testimonial.title.zh.length).toBeGreaterThan(0);
      expect(c.testimonial.avatarInitial.length).toBe(1);
      expect(c.institutions).toHaveLength(5);
    },
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && pnpm test:unit -- tests/unit/role-content.test.ts`

Expected: FAIL — `@/lib/marketing/role-content` cannot be resolved.

- [ ] **Step 3: Create the content module**

Create `apps/web/lib/marketing/role-content.ts`:

```ts
export type RoleKey = "researcher" | "lawyer" | "doctor" | "teacher" | "founder" | "designer";

export const ROLE_KEYS: readonly RoleKey[] = [
  "researcher", "lawyer", "doctor", "teacher", "founder", "designer",
] as const;

interface Localized { zh: string; en: string }

export interface RoleContent {
  key: RoleKey;
  label: Localized;
  icon: string;
  domainNoun: Localized;
  stat: { count: number; asOf: string };
  demo: { title: Localized; description: Localized; animationKey: string };
  templatePack: { title: Localized; items: Localized[]; cta: Localized };
  offer: { title: Localized; description: Localized; cta: Localized; href: string };
  testimonial: { quote: Localized; name: string; title: Localized; avatarInitial: string };
  institutions: string[];
}

export const ROLE_CONTENT: Record<RoleKey, RoleContent> = {
  researcher: {
    key: "researcher",
    label: { zh: "研究生", en: "Researcher" },
    icon: "🔬",
    domainNoun: { zh: "研究伙伴", en: "research companion" },
    stat: { count: 5243, asOf: "2026-04" },
    demo: {
      title: { zh: "文献综述自动整理", en: "Auto-compiled literature review" },
      description: {
        zh: "看 MRNote 如何把 50 篇论文整理成可引用的综述。",
        en: "Watch MRNote turn 50 papers into a citeable review.",
      },
      animationKey: "researcher.literature",
    },
    templatePack: {
      title: { zh: "研究生 5 件套", en: "Grad student starter pack" },
      items: [
        { zh: "文献卡", en: "Literature card" },
        { zh: "实验日志", en: "Experiment log" },
        { zh: "开题报告", en: "Proposal" },
        { zh: "周报", en: "Weekly report" },
        { zh: "论文大纲", en: "Paper outline" },
      ],
      cta: { zh: "免费导入 →", en: "Import free →" },
    },
    offer: {
      title: { zh: ".edu 邮箱 · Pro 免费 6 月", en: ".edu email · 6 months Pro free" },
      description: {
        zh: "验证学生身份即可激活，无需信用卡。",
        en: "Verify your student status, no credit card required.",
      },
      cta: { zh: "立即激活 →", en: "Activate now →" },
      href: "/register?offer=edu-6m",
    },
    testimonial: {
      quote: {
        zh: "写论文最痛的一步是把之前读过的文献重新串起来。MRNote 帮我做了 80% —— 它真的记得我三个月前标注过什么。",
        en: "The hardest part of writing was stitching back what I'd already read. MRNote did 80% of it — it truly remembers what I highlighted 3 months ago.",
      },
      name: "李同学",
      title: { zh: "清华大学 · 计算机博二", en: "Tsinghua University · CS PhD Y2" },
      avatarInitial: "李",
    },
    institutions: ["清华大学", "北京大学", "中科院", "复旦大学", "浙江大学"],
  },
  lawyer: {
    key: "lawyer",
    label: { zh: "律师", en: "Lawyer" },
    icon: "⚖️",
    domainNoun: { zh: "案件助手", en: "case assistant" },
    stat: { count: 1872, asOf: "2026-04" },
    demo: {
      title: { zh: "合同摘要 10 秒出", en: "Contract summary in 10s" },
      description: {
        zh: "上传 30 页合同，AI 自动拎出风险条款与关键义务。",
        en: "Upload a 30-page contract; AI surfaces risk clauses and obligations.",
      },
      animationKey: "lawyer.contract",
    },
    templatePack: {
      title: { zh: "律师 5 件套", en: "Lawyer starter pack" },
      items: [
        { zh: "案件笔记", en: "Case note" },
        { zh: "客户档案", en: "Client profile" },
        { zh: "庭审要点", en: "Hearing brief" },
        { zh: "证据索引", en: "Evidence index" },
        { zh: "法条速查", en: "Statute lookup" },
      ],
      cta: { zh: "免费导入 →", en: "Import free →" },
    },
    offer: {
      title: { zh: "律所专属 · 3 席位包年 9 折", en: "Firm pack · 10% off 3-seat annual" },
      description: {
        zh: "适合独立律师与小型律所，含团队知识共享。",
        en: "Built for solo attorneys and small firms. Team memory included.",
      },
      cta: { zh: "了解详情 →", en: "Learn more →" },
      href: "/register?offer=firm-3seat",
    },
    testimonial: {
      quote: {
        zh: "之前一个案件的上下文散在邮件、钉钉、纸质笔记里。MRNote 把它们都拼起来，开庭前半小时能复盘完整时间线。",
        en: "Case context used to be scattered across email, chat, and paper notes. MRNote stitches it together — I can rehearse the full timeline 30min before hearing.",
      },
      name: "王律师",
      title: { zh: "北京某律所 · 执业 8 年", en: "Beijing firm · 8 yrs practice" },
      avatarInitial: "王",
    },
    institutions: ["金杜律师事务所", "中伦律师事务所", "方达律师事务所", "君合律师事务所", "海问律师事务所"],
  },
  doctor: {
    key: "doctor",
    label: { zh: "医生", en: "Doctor" },
    icon: "👨‍⚕️",
    domainNoun: { zh: "病历助手", en: "clinical sidekick" },
    stat: { count: 2104, asOf: "2026-04" },
    demo: {
      title: { zh: "门诊随手记结构化", en: "Consult notes, auto-structured" },
      description: {
        zh: "口述一段门诊观察，MRNote 自动拆成主诉 / 现病史 / 体检 / 处置。",
        en: "Dictate a consult; MRNote auto-splits it into CC / HPI / exam / plan.",
      },
      animationKey: "doctor.consult",
    },
    templatePack: {
      title: { zh: "医生 5 件套", en: "Clinician starter pack" },
      items: [
        { zh: "门诊记录", en: "Consult note" },
        { zh: "病例讨论", en: "Case discussion" },
        { zh: "文献笔记", en: "Literature note" },
        { zh: "术后随访", en: "Post-op follow-up" },
        { zh: "值班交接", en: "Shift handover" },
      ],
      cta: { zh: "免费导入 →", en: "Import free →" },
    },
    offer: {
      title: { zh: "医学生 · Pro 免费 1 年", en: "Med student · 1 year Pro free" },
      description: {
        zh: "医学院邮箱验证，支持规培期间持续免费。",
        en: "Medical school email verification, stays free during residency.",
      },
      cta: { zh: "立即激活 →", en: "Activate now →" },
      href: "/register?offer=med-1y",
    },
    testimonial: {
      quote: {
        zh: "值夜班最怕交接漏信息。MRNote 让我口述几句就能生成干净的交接单，节省至少 20 分钟。",
        en: "Night shifts risk missing handoff details. MRNote turns my dictation into a clean handover doc — saves at least 20 min.",
      },
      name: "张医生",
      title: { zh: "三甲医院 · 内科住院医师", en: "Tertiary hospital · Internal medicine resident" },
      avatarInitial: "张",
    },
    institutions: ["协和医院", "华西医院", "瑞金医院", "中山医院", "湘雅医院"],
  },
  teacher: {
    key: "teacher",
    label: { zh: "老师", en: "Teacher" },
    icon: "👨‍🏫",
    domainNoun: { zh: "教学助手", en: "teaching co-pilot" },
    stat: { count: 3156, asOf: "2026-04" },
    demo: {
      title: { zh: "教案 + 作业 + 题库一体化", en: "Lesson + homework + question bank in one" },
      description: {
        zh: "同一个知识点挂三处：教案、作业、题库，随时互相引用。",
        en: "One concept, three places — lesson, homework, question bank, cross-referenced.",
      },
      animationKey: "teacher.lessonbank",
    },
    templatePack: {
      title: { zh: "老师 5 件套", en: "Teacher starter pack" },
      items: [
        { zh: "教案", en: "Lesson plan" },
        { zh: "学情记录", en: "Student log" },
        { zh: "题库", en: "Question bank" },
        { zh: "家长沟通", en: "Parent notes" },
        { zh: "学期总结", en: "Term review" },
      ],
      cta: { zh: "免费导入 →", en: "Import free →" },
    },
    offer: {
      title: { zh: "教师节专属 · 包年 5 折", en: "Teachers' Day · 50% off annual" },
      description: {
        zh: "学校邮箱验证即享；班级共享工作区无限开。",
        en: "School email unlocks it; unlimited class workspaces included.",
      },
      cta: { zh: "立即激活 →", en: "Activate now →" },
      href: "/register?offer=teacher-50off",
    },
    testimonial: {
      quote: {
        zh: "以前备课要翻三年前的教案找一个例题。现在一句话就能跳过去，还能看到我当年写的反思。",
        en: "I used to dig through 3-yr-old lesson plans for one example. Now one query jumps me there — with my old reflection attached.",
      },
      name: "陈老师",
      title: { zh: "公立高中 · 数学教龄 12 年", en: "Public high school · Math, 12 yrs" },
      avatarInitial: "陈",
    },
    institutions: ["人大附中", "北京四中", "上海中学", "华师大二附中", "杭州二中"],
  },
  founder: {
    key: "founder",
    label: { zh: "创业者", en: "Founder" },
    icon: "🚀",
    domainNoun: { zh: "创业大脑", en: "founder brain" },
    stat: { count: 1620, asOf: "2026-04" },
    demo: {
      title: { zh: "客户访谈自动提炼洞察", en: "Customer interviews, insights auto-surfaced" },
      description: {
        zh: "20 场用户访谈，MRNote 自动聚类共性问题和高频语句。",
        en: "20 user interviews → auto-clustered pains and recurring quotes.",
      },
      animationKey: "founder.interviews",
    },
    templatePack: {
      title: { zh: "创业者 5 件套", en: "Founder starter pack" },
      items: [
        { zh: "用户访谈", en: "User interview" },
        { zh: "周例会纪要", en: "Weekly sync" },
        { zh: "融资材料", en: "Fundraising deck" },
        { zh: "决策日志", en: "Decision log" },
        { zh: "增长实验", en: "Growth experiment" },
      ],
      cta: { zh: "免费导入 →", en: "Import free →" },
    },
    offer: {
      title: { zh: "早期团队 · Team 5 人 7 折", en: "Early team · 30% off Team 5-seat" },
      description: {
        zh: "凭营业执照验证，适合 2–10 人早期创业团队。",
        en: "Business license verification. Fits 2–10 person early-stage teams.",
      },
      cta: { zh: "了解详情 →", en: "Learn more →" },
      href: "/register?offer=team-early",
    },
    testimonial: {
      quote: {
        zh: "做决策最怕忘了当时为什么这么选。MRNote 帮我把所有 reasoning 都挂在了决策日志上，半年后回看还清清楚楚。",
        en: "The scariest part of decisions is forgetting why. MRNote keeps every reasoning attached to the decision log — still crystal clear 6 months later.",
      },
      name: "赵总",
      title: { zh: "SaaS 初创 · 创始人", en: "SaaS startup · Founder" },
      avatarInitial: "赵",
    },
    institutions: ["红杉中国", "高瓴创投", "真格基金", "奇绩创坛", "GGV 纪源资本"],
  },
  designer: {
    key: "designer",
    label: { zh: "设计师", en: "Designer" },
    icon: "🎨",
    domainNoun: { zh: "灵感图书馆", en: "inspiration library" },
    stat: { count: 2789, asOf: "2026-04" },
    demo: {
      title: { zh: "灵感卡片秒级检索", en: "Instant inspiration card search" },
      description: {
        zh: "按颜色 / 结构 / 情绪搜一张三个月前收藏的卡片。",
        en: "Search a card you saved 3 months ago by color, structure, or mood.",
      },
      animationKey: "designer.inspire",
    },
    templatePack: {
      title: { zh: "设计师 5 件套", en: "Designer starter pack" },
      items: [
        { zh: "灵感卡", en: "Inspiration card" },
        { zh: "项目简报", en: "Project brief" },
        { zh: "评审记录", en: "Review log" },
        { zh: "竞品分析", en: "Competitor scan" },
        { zh: "交付清单", en: "Handoff checklist" },
      ],
      cta: { zh: "免费导入 →", en: "Import free →" },
    },
    offer: {
      title: { zh: "独立设计师 · 首月 1 元", en: "Freelancer · ¥1 first month" },
      description: {
        zh: "把零散的 Figma / Notion 笔记迁过来，体验 30 天。",
        en: "Migrate scattered Figma / Notion notes. 30-day full access.",
      },
      cta: { zh: "立即激活 →", en: "Activate now →" },
      href: "/register?offer=designer-1rmb",
    },
    testimonial: {
      quote: {
        zh: "以前收藏的灵感卡散在 Pinterest、截图文件夹、Figma 里找不回。MRNote 打了一个统一的搜索口，按情绪也能搜。",
        en: "My saved inspiration used to scatter across Pinterest, screenshot folders, Figma — unfindable. MRNote gives one search that even understands mood.",
      },
      name: "林设计师",
      title: { zh: "独立品牌设计师", en: "Independent brand designer" },
      avatarInitial: "林",
    },
    institutions: ["字节跳动", "小米设计", "蔚来 UX", "腾讯 CDC", "阿里 UED"],
  },
};

// TODO: replace placeholder testimonials with real-person consented quotes before launch.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && pnpm test:unit -- tests/unit/role-content.test.ts`

Expected: PASS — 7 tests (1 structural + 6 role-specific).

- [ ] **Step 5: Commit**

```bash
git add apps/web/lib/marketing/role-content.ts apps/web/tests/unit/role-content.test.ts
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(web): typed role-content table for personalized landing

Defines RoleKey, RoleContent, and ROLE_CONTENT for 6 roles
(researcher/lawyer/doctor/teacher/founder/designer) with zh+en
copy for demo / template pack / offer / testimonial / institution
logos. Drives the ExclusiveSection on the marketing homepage.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `useRoleSelection` hook

**Files:**
- Create: `apps/web/hooks/useRoleSelection.ts`
- Test: `apps/web/tests/unit/useRoleSelection.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `apps/web/tests/unit/useRoleSelection.test.tsx`:

```tsx
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ROLE_COOKIE_NAME, useRoleSelection } from "@/hooks/useRoleSelection";

function Probe({
  onReady,
}: {
  onReady: (api: ReturnType<typeof useRoleSelection>) => void;
}) {
  const api = useRoleSelection(null);
  onReady(api);
  return null;
}

function clearAllCookies() {
  document.cookie
    .split(";")
    .map((c) => c.trim().split("=")[0])
    .filter(Boolean)
    .forEach((name) => {
      document.cookie = `${name}=; Max-Age=0; Path=/`;
    });
}

describe("useRoleSelection", () => {
  beforeEach(() => clearAllCookies());
  afterEach(() => clearAllCookies());

  it("starts with initialRole (SSR hint)", () => {
    let api: ReturnType<typeof useRoleSelection> | null = null;
    function Probe2() {
      api = useRoleSelection("researcher");
      return null;
    }
    render(<Probe2 />);
    expect(api!.role).toBe("researcher");
  });

  it("setRole writes the cookie and updates state", () => {
    let api: ReturnType<typeof useRoleSelection> | null = null;
    render(<Probe onReady={(a) => (api = a)} />);
    act(() => { api!.setRole("lawyer"); });
    expect(api!.role).toBe("lawyer");
    expect(document.cookie).toContain(`${ROLE_COOKIE_NAME}=lawyer`);
  });

  it("clearRole removes the cookie and resets state", () => {
    let api: ReturnType<typeof useRoleSelection> | null = null;
    render(<Probe onReady={(a) => (api = a)} />);
    act(() => { api!.setRole("doctor"); });
    act(() => { api!.clearRole(); });
    expect(api!.role).toBeNull();
    expect(document.cookie).not.toContain(`${ROLE_COOKIE_NAME}=`);
  });

  it("ignores unknown roles written directly to cookie", () => {
    document.cookie = `${ROLE_COOKIE_NAME}=hacker; Path=/`;
    let api: ReturnType<typeof useRoleSelection> | null = null;
    render(<Probe onReady={(a) => (api = a)} />);
    expect(api!.role).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && pnpm test:unit -- tests/unit/useRoleSelection.test.tsx`

Expected: FAIL — module not found.

- [ ] **Step 3: Create the hook**

Create `apps/web/hooks/useRoleSelection.ts`:

```ts
"use client";

import { useCallback, useState } from "react";
import { clearCookie, readCookie, writeCookie } from "@/lib/cookie";
import { ROLE_KEYS, type RoleKey } from "@/lib/marketing/role-content";

export const ROLE_COOKIE_NAME = "mrai_landing_role";
const THIRTY_DAYS_SECONDS = 60 * 60 * 24 * 30;

function readRoleFromCookie(): RoleKey | null {
  const raw = readCookie(ROLE_COOKIE_NAME);
  if (!raw) return null;
  return (ROLE_KEYS as readonly string[]).includes(raw) ? (raw as RoleKey) : null;
}

export interface UseRoleSelection {
  role: RoleKey | null;
  setRole: (next: RoleKey) => void;
  clearRole: () => void;
}

export function useRoleSelection(initialRole: RoleKey | null): UseRoleSelection {
  const [role, setRoleState] = useState<RoleKey | null>(() => {
    // In browser, prefer live cookie over stale SSR hint.
    if (typeof document !== "undefined") {
      return readRoleFromCookie() ?? initialRole ?? null;
    }
    return initialRole ?? null;
  });

  const setRole = useCallback((next: RoleKey) => {
    writeCookie(ROLE_COOKIE_NAME, next, THIRTY_DAYS_SECONDS);
    setRoleState(next);
  }, []);

  const clearRole = useCallback(() => {
    clearCookie(ROLE_COOKIE_NAME);
    setRoleState(null);
  }, []);

  return { role, setRole, clearRole };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && pnpm test:unit -- tests/unit/useRoleSelection.test.tsx`

Expected: PASS — 4 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/web/hooks/useRoleSelection.ts apps/web/tests/unit/useRoleSelection.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(web): useRoleSelection hook backed by mrai_landing_role cookie

Reads/writes mrai_landing_role (30d, Path=/, SameSite=Lax).
Validates cookie value against ROLE_KEYS so stale or forged values
fall back to null. initialRole prop supports SSR-hydrated reads
without flashing an empty state for returning visitors.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: StatCounter component

**Files:**
- Create: `apps/web/components/marketing/role-selector/StatCounter.tsx`
- Test: `apps/web/tests/unit/stat-counter.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `apps/web/tests/unit/stat-counter.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import StatCounter from "@/components/marketing/role-selector/StatCounter";

describe("StatCounter", () => {
  const originalMatchMedia = window.matchMedia;

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
    vi.useRealTimers();
  });

  function setReducedMotion(matches: boolean) {
    window.matchMedia = vi.fn().mockImplementation((query) => ({
      matches: query.includes("prefers-reduced-motion") && matches,
      media: query, onchange: null,
      addListener: vi.fn(), removeListener: vi.fn(),
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  }

  it("renders the final value immediately when reduced-motion is requested", () => {
    setReducedMotion(true);
    render(<StatCounter target={5243} />);
    expect(screen.getByText("5,243")).toBeTruthy();
  });

  it("announces the final value via aria-live", () => {
    setReducedMotion(true);
    const { container } = render(<StatCounter target={100} />);
    const el = container.querySelector('[aria-live="polite"]');
    expect(el).not.toBeNull();
    expect(el!.textContent).toContain("100");
  });

  it("formats numbers with thousand separators", () => {
    setReducedMotion(true);
    render(<StatCounter target={12345} />);
    expect(screen.getByText("12,345")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && pnpm test:unit -- tests/unit/stat-counter.test.tsx`

Expected: FAIL — component not found.

- [ ] **Step 3: Create StatCounter**

Create `apps/web/components/marketing/role-selector/StatCounter.tsx`:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  target: number;
  durationMs?: number;
  className?: string;
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function formatNumber(n: number): string {
  return n.toLocaleString("en-US");
}

export default function StatCounter({ target, durationMs = 1200, className }: Props) {
  const [value, setValue] = useState<number>(() => (prefersReducedMotion() ? target : 0));
  const observerRef = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    if (prefersReducedMotion()) {
      setValue(target);
      return;
    }
    const node = observerRef.current;
    if (!node) return;

    let rafId: number | null = null;
    let started = false;

    const runCountUp = () => {
      const start = performance.now();
      const step = (now: number) => {
        const elapsed = now - start;
        const progress = Math.min(1, elapsed / durationMs);
        const eased = 1 - Math.pow(1 - progress, 3);
        setValue(Math.round(eased * target));
        if (progress < 1) rafId = requestAnimationFrame(step);
      };
      rafId = requestAnimationFrame(step);
    };

    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && !started) {
            started = true;
            runCountUp();
            io.disconnect();
            return;
          }
        }
      },
      { threshold: 0.3 },
    );
    io.observe(node);
    return () => {
      io.disconnect();
      if (rafId !== null) cancelAnimationFrame(rafId);
    };
  }, [target, durationMs]);

  return (
    <span
      ref={observerRef}
      className={className}
      aria-live="polite"
      aria-atomic="true"
    >
      {formatNumber(value)}
    </span>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && pnpm test:unit -- tests/unit/stat-counter.test.tsx`

Expected: PASS — 3 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/marketing/role-selector/StatCounter.tsx apps/web/tests/unit/stat-counter.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(web): StatCounter with IntersectionObserver + reduced-motion

Counts up from 0 to target when scrolled into view; renders the
final value instantly when prefers-reduced-motion: reduce. Emits
formatted thousand-separated number via aria-live="polite" so
screen readers announce only the final state.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: RoleChipRow component

**Files:**
- Create: `apps/web/components/marketing/role-selector/RoleChipRow.tsx`
- Test: `apps/web/tests/unit/role-chip-row.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `apps/web/tests/unit/role-chip-row.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import RoleChipRow from "@/components/marketing/role-selector/RoleChipRow";

describe("RoleChipRow", () => {
  it("renders all 6 chips with role labels", () => {
    render(<RoleChipRow activeRole={null} onSelect={() => {}} locale="zh" />);
    expect(screen.getByRole("radio", { name: "研究生" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "律师" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "医生" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "老师" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "创业者" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "设计师" })).toBeTruthy();
  });

  it("marks the active chip with aria-checked=true", () => {
    render(<RoleChipRow activeRole="lawyer" onSelect={() => {}} locale="zh" />);
    expect(screen.getByRole("radio", { name: "律师" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("radio", { name: "研究生" }).getAttribute("aria-checked")).toBe("false");
  });

  it("fires onSelect when a chip is clicked", () => {
    const onSelect = vi.fn();
    render(<RoleChipRow activeRole={null} onSelect={onSelect} locale="zh" />);
    fireEvent.click(screen.getByRole("radio", { name: "医生" }));
    expect(onSelect).toHaveBeenCalledWith("doctor");
  });

  it("arrow-right moves focus to next chip and fires onSelect", () => {
    const onSelect = vi.fn();
    render(<RoleChipRow activeRole="researcher" onSelect={onSelect} locale="zh" />);
    const first = screen.getByRole("radio", { name: "研究生" });
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(onSelect).toHaveBeenCalledWith("lawyer");
  });

  it("arrow-left from first wraps to last", () => {
    const onSelect = vi.fn();
    render(<RoleChipRow activeRole="researcher" onSelect={onSelect} locale="zh" />);
    const first = screen.getByRole("radio", { name: "研究生" });
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowLeft" });
    expect(onSelect).toHaveBeenCalledWith("designer");
  });

  it("renders English labels when locale=en", () => {
    render(<RoleChipRow activeRole={null} onSelect={() => {}} locale="en" />);
    expect(screen.getByRole("radio", { name: "Researcher" })).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && pnpm test:unit -- tests/unit/role-chip-row.test.tsx`

Expected: FAIL — component not found.

- [ ] **Step 3: Create RoleChipRow**

Create `apps/web/components/marketing/role-selector/RoleChipRow.tsx`:

```tsx
"use client";

import { useCallback, useRef } from "react";
import { ROLE_CONTENT, ROLE_KEYS, type RoleKey } from "@/lib/marketing/role-content";

interface Props {
  activeRole: RoleKey | null;
  onSelect: (role: RoleKey) => void;
  locale: "zh" | "en";
}

export default function RoleChipRow({ activeRole, onSelect, locale }: Props) {
  const chipsRef = useRef<Array<HTMLButtonElement | null>>([]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        const delta = e.key === "ArrowRight" ? 1 : -1;
        const nextIndex = (index + delta + ROLE_KEYS.length) % ROLE_KEYS.length;
        const nextRole = ROLE_KEYS[nextIndex];
        onSelect(nextRole);
        chipsRef.current[nextIndex]?.focus();
      }
    },
    [onSelect],
  );

  return (
    <div role="radiogroup" aria-label="role selector" className="marketing-exclusive__chips">
      {ROLE_KEYS.map((key, i) => {
        const content = ROLE_CONTENT[key];
        const isActive = activeRole === key;
        return (
          <button
            key={key}
            ref={(el) => { chipsRef.current[i] = el; }}
            type="button"
            role="radio"
            aria-checked={isActive}
            aria-label={content.label[locale]}
            tabIndex={isActive || (!activeRole && i === 0) ? 0 : -1}
            data-active={isActive || undefined}
            className="marketing-exclusive__chip"
            onClick={() => onSelect(key)}
            onKeyDown={(e) => handleKeyDown(e, i)}
          >
            <span aria-hidden="true">{content.icon}</span>
            <span>{content.label[locale]}</span>
          </button>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && pnpm test:unit -- tests/unit/role-chip-row.test.tsx`

Expected: PASS — 6 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/marketing/role-selector/RoleChipRow.tsx apps/web/tests/unit/role-chip-row.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(web): RoleChipRow with radiogroup a11y + arrow-key nav

Renders 6 role chips as a proper role=radiogroup with role=radio
buttons. Arrow keys wrap-navigate; Tab focuses the active chip
only (roving tabindex). Emoji is aria-hidden; the chip's visible
label becomes its accessible name in the current locale.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: RoleCard + ExclusiveOfferCard

**Files:**
- Create: `apps/web/components/marketing/role-selector/RoleCard.tsx`
- Create: `apps/web/components/marketing/role-selector/ExclusiveOfferCard.tsx`
- Test: `apps/web/tests/unit/role-cards.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `apps/web/tests/unit/role-cards.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import RoleCard from "@/components/marketing/role-selector/RoleCard";
import ExclusiveOfferCard from "@/components/marketing/role-selector/ExclusiveOfferCard";

describe("RoleCard", () => {
  it("renders label, title, description, and cta", () => {
    render(
      <RoleCard
        label="场景 DEMO"
        title="文献综述自动整理"
        description="看 MRNote 如何把 50 篇论文整理成可引用的综述。"
        cta="免费导入 →"
      />,
    );
    expect(screen.getByText("场景 DEMO")).toBeTruthy();
    expect(screen.getByText("文献综述自动整理")).toBeTruthy();
    expect(screen.getByText("免费导入 →")).toBeTruthy();
  });
});

describe("ExclusiveOfferCard", () => {
  it("renders title, description, CTA link, and the 独家 badge", () => {
    render(
      <ExclusiveOfferCard
        title=".edu 邮箱 · Pro 免费 6 月"
        description="验证学生身份即可激活，无需信用卡。"
        cta="立即激活 →"
        href="/register?offer=edu-6m"
        badge="独家"
      />,
    );
    const link = screen.getByRole("link", { name: /立即激活/ });
    expect(link.getAttribute("href")).toBe("/register?offer=edu-6m");
    expect(screen.getByText("独家")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && pnpm test:unit -- tests/unit/role-cards.test.tsx`

Expected: FAIL — components not found.

- [ ] **Step 3: Create RoleCard**

Create `apps/web/components/marketing/role-selector/RoleCard.tsx`:

```tsx
interface Props {
  label: string;
  title: string;
  description: string;
  cta?: string;
  mediaSlot?: React.ReactNode;
}

export default function RoleCard({ label, title, description, cta, mediaSlot }: Props) {
  return (
    <div className="marketing-exclusive__card">
      <span className="marketing-exclusive__card-label">{label}</span>
      <h4 className="marketing-exclusive__card-title">{title}</h4>
      <p className="marketing-exclusive__card-body">{description}</p>
      {mediaSlot ? <div className="marketing-exclusive__card-media">{mediaSlot}</div> : null}
      {cta ? <span className="marketing-exclusive__card-cta">{cta}</span> : null}
    </div>
  );
}
```

- [ ] **Step 4: Create ExclusiveOfferCard**

Create `apps/web/components/marketing/role-selector/ExclusiveOfferCard.tsx`:

```tsx
import { Link } from "@/i18n/navigation";

interface Props {
  title: string;
  description: string;
  cta: string;
  href: string;
  badge: string;
}

export default function ExclusiveOfferCard({ title, description, cta, href, badge }: Props) {
  return (
    <div className="marketing-exclusive__card marketing-exclusive__card--offer">
      <span className="marketing-exclusive__offer-badge">{badge}</span>
      <span className="marketing-exclusive__card-label marketing-exclusive__card-label--offer">
        专属优惠
      </span>
      <h4 className="marketing-exclusive__card-title">{title}</h4>
      <p className="marketing-exclusive__card-body">{description}</p>
      <Link href={href} className="marketing-exclusive__offer-cta">
        {cta}
      </Link>
    </div>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd apps/web && pnpm test:unit -- tests/unit/role-cards.test.tsx`

Expected: PASS — 2 tests.

- [ ] **Step 6: Commit**

```bash
git add apps/web/components/marketing/role-selector/RoleCard.tsx \
        apps/web/components/marketing/role-selector/ExclusiveOfferCard.tsx \
        apps/web/tests/unit/role-cards.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(web): RoleCard + ExclusiveOfferCard presentationals

Neutral RoleCard for demo + template slots. ExclusiveOfferCard
for slot 3 with warm-accent CTA (styled via .marketing-exclusive
__card--offer) and a 独家 corner badge, linking through i18n-aware
Link to the offer landing URL.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: TestimonialStrip + InstitutionLogoRow

**Files:**
- Create: `apps/web/components/marketing/role-selector/TestimonialStrip.tsx`
- Create: `apps/web/components/marketing/role-selector/InstitutionLogoRow.tsx`
- Test: `apps/web/tests/unit/social-proof.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `apps/web/tests/unit/social-proof.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import TestimonialStrip from "@/components/marketing/role-selector/TestimonialStrip";
import InstitutionLogoRow from "@/components/marketing/role-selector/InstitutionLogoRow";

describe("TestimonialStrip", () => {
  it("renders quote, attribution, and decorative avatar initial", () => {
    render(
      <TestimonialStrip
        quote="写论文最痛的一步是把之前读过的文献重新串起来。"
        name="李同学"
        title="清华大学 · 计算机博二"
        avatarInitial="李"
      />,
    );
    expect(screen.getByText(/写论文最痛的一步/)).toBeTruthy();
    expect(screen.getByText("李同学 · 清华大学 · 计算机博二")).toBeTruthy();
    const avatar = screen.getByText("李", { selector: "[aria-hidden='true']" });
    expect(avatar).toBeTruthy();
  });
});

describe("InstitutionLogoRow", () => {
  it("renders all 5 institution names with a heading", () => {
    render(
      <InstitutionLogoRow
        heading="使用 MRNote 的研究机构"
        names={["清华大学", "北京大学", "中科院", "复旦大学", "浙江大学"]}
      />,
    );
    expect(screen.getByText("使用 MRNote 的研究机构")).toBeTruthy();
    ["清华大学", "北京大学", "中科院", "复旦大学", "浙江大学"].forEach((n) => {
      expect(screen.getByText(n)).toBeTruthy();
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && pnpm test:unit -- tests/unit/social-proof.test.tsx`

Expected: FAIL — components not found.

- [ ] **Step 3: Create TestimonialStrip**

Create `apps/web/components/marketing/role-selector/TestimonialStrip.tsx`:

```tsx
interface Props {
  quote: string;
  name: string;
  title: string;
  avatarInitial: string;
}

export default function TestimonialStrip({ quote, name, title, avatarInitial }: Props) {
  return (
    <figure className="marketing-exclusive__testimonial">
      <div className="marketing-exclusive__testimonial-avatar" aria-hidden="true">
        {avatarInitial}
      </div>
      <div>
        <blockquote className="marketing-exclusive__testimonial-quote">
          &ldquo;{quote}&rdquo;
        </blockquote>
        <figcaption className="marketing-exclusive__testimonial-attr">
          {name} · {title}
        </figcaption>
      </div>
    </figure>
  );
}
```

- [ ] **Step 4: Create InstitutionLogoRow**

Create `apps/web/components/marketing/role-selector/InstitutionLogoRow.tsx`:

```tsx
interface Props {
  heading: string;
  names: string[];
}

export default function InstitutionLogoRow({ heading, names }: Props) {
  return (
    <div className="marketing-exclusive__logos">
      <div className="marketing-exclusive__logos-heading">{heading}</div>
      <ul className="marketing-exclusive__logos-list">
        {names.map((name) => (
          <li key={name} className="marketing-exclusive__logos-item">{name}</li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd apps/web && pnpm test:unit -- tests/unit/social-proof.test.tsx`

Expected: PASS — 2 tests.

- [ ] **Step 6: Commit**

```bash
git add apps/web/components/marketing/role-selector/TestimonialStrip.tsx \
        apps/web/components/marketing/role-selector/InstitutionLogoRow.tsx \
        apps/web/tests/unit/social-proof.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(web): TestimonialStrip + InstitutionLogoRow presentationals

Semantic figure/blockquote/figcaption for the testimonial so
screen readers group the quote with its attribution. Avatar
initial is decorative (aria-hidden). InstitutionLogoRow uses
text-only marks so we don't take on image-licensing work for v1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: i18n chrome strings

**Files:**
- Modify: `apps/web/messages/zh/marketing.json`
- Modify: `apps/web/messages/en/marketing.json`

- [ ] **Step 1: Add the `exclusiveSection` keys to `zh/marketing.json`**

Open `apps/web/messages/zh/marketing.json`, add these keys to the top-level object (place them after the existing `"hero.*"` block for readability):

```json
"exclusiveSection.eyebrow": "✦ 为你精选 · 独家",
"exclusiveSection.chipsLabel": "身份选择",
"exclusiveSection.emptyTitle": "选择你的身份，解锁定制内容",
"exclusiveSection.emptyHint": "告诉我们你的身份，为你推荐对的 demo、模板和专属优惠。",
"exclusiveSection.populatedTitle": "为{role}打造的 MRNote",
"exclusiveSection.statLinePrefix": "已有 ",
"exclusiveSection.statLineSuffix": " 名{role}把 MRNote 作为日常{noun}",
"exclusiveSection.switch": "切换",
"exclusiveSection.cardLabel.demo": "场景 DEMO",
"exclusiveSection.cardLabel.templatePack": "模板包",
"exclusiveSection.offerBadge": "独家",
"exclusiveSection.placeholderCard": "等待解锁",
"exclusiveSection.logosHeading": "正在使用 MRNote 的机构",
"exclusiveSection.statAsOfTooltip": "数据截至 {month}",
```

- [ ] **Step 2: Add the same keys to `en/marketing.json`**

```json
"exclusiveSection.eyebrow": "✦ Hand-picked for you · Exclusive",
"exclusiveSection.chipsLabel": "Role selector",
"exclusiveSection.emptyTitle": "Pick your role to unlock tailored content",
"exclusiveSection.emptyHint": "Tell us what you do; we'll show the right demo, templates, and offers.",
"exclusiveSection.populatedTitle": "MRNote for {role}",
"exclusiveSection.statLinePrefix": "",
"exclusiveSection.statLineSuffix": " {role}s already use MRNote as their daily {noun}",
"exclusiveSection.switch": "Switch",
"exclusiveSection.cardLabel.demo": "SCENARIO DEMO",
"exclusiveSection.cardLabel.templatePack": "TEMPLATE PACK",
"exclusiveSection.offerBadge": "EXCLUSIVE",
"exclusiveSection.placeholderCard": "Locked",
"exclusiveSection.logosHeading": "Teams using MRNote",
"exclusiveSection.statAsOfTooltip": "As of {month}",
```

- [ ] **Step 3: Verify JSON is valid**

Run: `cd apps/web && node -e "require('./messages/zh/marketing.json'); require('./messages/en/marketing.json'); console.log('ok')"`

Expected output: `ok`

- [ ] **Step 4: Commit**

```bash
git add apps/web/messages/zh/marketing.json apps/web/messages/en/marketing.json
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
i18n(web): exclusiveSection keys for role-personalized landing

Adds chrome strings (eyebrow, empty/populated titles, stat line,
switch, card labels, offer badge, logos heading) in zh + en. Role
content itself lives in lib/marketing/role-content.ts, not in
translations, because it is structured and versioned together.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Marketing CSS additions

**Files:**
- Modify: `apps/web/styles/marketing.css`

- [ ] **Step 1: Append the exclusive-section styles**

Append this block to the end of `apps/web/styles/marketing.css` (paste verbatim, single addition):

```css
/* ==========================================================================
   ExclusiveSection — role-personalized landing (see docs/superpowers/specs/
   2026-04-20-role-personalized-landing-design.md)
   ========================================================================== */

.marketing-exclusive {
  position: relative;
  padding: 72px 24px;
  background: linear-gradient(to bottom, #f0fdfa 0%, #ffffff 100%);
}

.marketing-exclusive__inner {
  max-width: 1100px;
  margin: 0 auto;
}

.marketing-exclusive__eyebrow {
  display: block;
  text-align: center;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: #0d9488;
  margin-bottom: 8px;
}

.marketing-exclusive__title {
  text-align: center;
  font-size: clamp(22px, 3vw, 32px);
  font-weight: 700;
  color: #0f2a2d;
  margin: 0 0 12px 0;
}

.marketing-exclusive__stat-line {
  text-align: center;
  font-size: 14px;
  color: #475569;
  margin-bottom: 24px;
}

.marketing-exclusive__stat-line strong {
  font-weight: 700;
  color: #0d9488;
  font-size: 17px;
}

.marketing-exclusive__hint {
  text-align: center;
  font-size: 13px;
  color: #64748b;
  margin-bottom: 20px;
}

.marketing-exclusive__chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
  margin-bottom: 28px;
}

.marketing-exclusive__chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: 1px solid #e5e7eb;
  background: #ffffff;
  border-radius: 999px;
  font-size: 13px;
  color: #475569;
  cursor: pointer;
  transition: background 150ms ease, color 150ms ease, border-color 150ms ease;
  min-height: 36px;
}

.marketing-exclusive__chip:hover {
  border-color: #5eead4;
  color: #0f2a2d;
}

.marketing-exclusive__chip:focus-visible {
  outline: 2px solid #0d9488;
  outline-offset: 2px;
}

.marketing-exclusive__chip[data-active] {
  background: #0d9488;
  color: #ffffff;
  border-color: #0d9488;
  font-weight: 600;
}

.marketing-exclusive__cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}

@media (max-width: 768px) {
  .marketing-exclusive__cards {
    grid-template-columns: 1fr;
  }
}

.marketing-exclusive__card {
  position: relative;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 18px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  display: flex;
  flex-direction: column;
}

.marketing-exclusive__card--placeholder {
  opacity: 0.5;
  min-height: 140px;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  font-size: 13px;
}

.marketing-exclusive__card-label {
  display: inline-block;
  background: #f0fdfa;
  color: #0d9488;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.5px;
  margin-bottom: 10px;
  align-self: flex-start;
}

.marketing-exclusive__card-label--offer {
  background: #fed7aa;
  color: #9a3412;
}

.marketing-exclusive__card-title {
  font-weight: 700;
  font-size: 15px;
  color: #0f2a2d;
  margin: 0 0 6px 0;
}

.marketing-exclusive__card-body {
  font-size: 13px;
  color: #64748b;
  line-height: 1.5;
  margin: 0 0 12px 0;
}

.marketing-exclusive__card-cta {
  color: #0d9488;
  font-size: 13px;
  font-weight: 600;
  margin-top: auto;
}

.marketing-exclusive__card--offer {
  background: linear-gradient(135deg, #fff7ed 0%, #ffffff 100%);
  border-color: #fed7aa;
  box-shadow: 0 2px 10px rgba(249, 115, 22, 0.08);
}

.marketing-exclusive__offer-badge {
  position: absolute;
  top: -8px;
  right: 14px;
  background: #f97316;
  color: #ffffff;
  font-size: 10px;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 999px;
  letter-spacing: 0.5px;
}

.marketing-exclusive__offer-cta {
  margin-top: auto;
  display: inline-block;
  background: #f97316;
  color: #ffffff;
  font-size: 14px;
  font-weight: 700;
  padding: 8px 14px;
  border-radius: 8px;
  text-decoration: none;
  transition: background 150ms ease;
  align-self: flex-start;
}

.marketing-exclusive__offer-cta:hover {
  background: #ea580c;
}

.marketing-exclusive__offer-cta:focus-visible {
  outline: 2px solid #f97316;
  outline-offset: 3px;
}

.marketing-exclusive__testimonial {
  margin: 0;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 16px;
  display: flex;
  gap: 14px;
  align-items: flex-start;
  margin-bottom: 18px;
}

.marketing-exclusive__testimonial-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: linear-gradient(135deg, #0d9488, #14b8a6);
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 16px;
  flex-shrink: 0;
}

.marketing-exclusive__testimonial-quote {
  margin: 0 0 6px 0;
  font-size: 13px;
  line-height: 1.55;
  color: #475569;
}

.marketing-exclusive__testimonial-attr {
  font-size: 11px;
  color: #94a3b8;
}

.marketing-exclusive__logos {
  text-align: center;
  margin-top: 18px;
}

.marketing-exclusive__logos-heading {
  font-size: 10px;
  color: #94a3b8;
  letter-spacing: 1.2px;
  text-transform: uppercase;
  margin-bottom: 10px;
}

.marketing-exclusive__logos-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  gap: 24px;
  justify-content: center;
  flex-wrap: wrap;
  opacity: 0.65;
}

.marketing-exclusive__logos-item {
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}

.marketing-exclusive__switch {
  background: none;
  border: none;
  color: #0d9488;
  font-size: 12px;
  cursor: pointer;
  text-decoration: underline;
  padding: 0 0 0 8px;
}

.marketing-exclusive__switch:focus-visible {
  outline: 2px solid #0d9488;
  outline-offset: 2px;
  border-radius: 2px;
}

/* Hero role badge (rendered inside HeroSection when a role is selected) */

.marketing-hero__role-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #0d9488;
  color: #ffffff;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 12px;
  border-radius: 999px;
  margin-bottom: 12px;
}

@media (prefers-reduced-motion: reduce) {
  .marketing-exclusive__chip {
    transition: none;
  }
  .marketing-exclusive__offer-cta {
    transition: none;
  }
}
```

- [ ] **Step 2: Verify CSS parses (optional but cheap)**

Run: `cd apps/web && node -e "const fs=require('fs'); const s=fs.readFileSync('styles/marketing.css','utf8'); if(!s.includes('marketing-exclusive__card--offer'))throw new Error('missing style')"`

Expected: no output (success).

- [ ] **Step 3: Commit**

```bash
git add apps/web/styles/marketing.css
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
style(web): marketing-exclusive CSS for role-personalized section

Section gradient background, chip row with focus-visible ring,
3-column cards collapsing to 1 column <=768px, warm-accent offer
card with orange #f97316 CTA + 独家 badge, testimonial and logo
row layouts, and a hero role badge. Respects prefers-reduced-motion
by disabling hover/CTA transitions.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: ExclusiveSection container

**Files:**
- Create: `apps/web/components/marketing/ExclusiveSection.tsx`
- Test: `apps/web/tests/unit/exclusive-section.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `apps/web/tests/unit/exclusive-section.test.tsx`:

```tsx
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import ExclusiveSection from "@/components/marketing/ExclusiveSection";

function clearAllCookies() {
  document.cookie
    .split(";")
    .map((c) => c.trim().split("=")[0])
    .filter(Boolean)
    .forEach((name) => {
      document.cookie = `${name}=; Max-Age=0; Path=/`;
    });
}

describe("ExclusiveSection", () => {
  beforeEach(() => clearAllCookies());
  afterEach(() => clearAllCookies());

  it("renders the empty state with placeholder cards when no role selected", () => {
    render(<ExclusiveSection initialRole={null} locale="zh" />);
    expect(screen.getByText("exclusiveSection.emptyTitle")).toBeTruthy();
    expect(screen.queryByText("立即激活 →")).toBeNull();
    const placeholders = screen.getAllByText("exclusiveSection.placeholderCard");
    expect(placeholders.length).toBeGreaterThanOrEqual(3);
  });

  it("renders role content when initialRole is provided", () => {
    render(<ExclusiveSection initialRole="researcher" locale="zh" />);
    expect(screen.getByText("文献综述自动整理")).toBeTruthy();
    expect(screen.getByText("研究生 5 件套")).toBeTruthy();
    expect(screen.getByText(".edu 邮箱 · Pro 免费 6 月")).toBeTruthy();
  });

  it("selecting a chip swaps the populated content", () => {
    render(<ExclusiveSection initialRole={null} locale="zh" />);
    act(() => {
      fireEvent.click(screen.getByRole("radio", { name: "律师" }));
    });
    expect(screen.getByText("合同摘要 10 秒出")).toBeTruthy();
  });

  it("switch link clears the role and returns to empty state", () => {
    render(<ExclusiveSection initialRole="lawyer" locale="zh" />);
    const switchBtn = screen.getByRole("button", { name: "exclusiveSection.switch" });
    act(() => { fireEvent.click(switchBtn); });
    expect(screen.queryByText("合同摘要 10 秒出")).toBeNull();
    expect(screen.getByText("exclusiveSection.emptyTitle")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && pnpm test:unit -- tests/unit/exclusive-section.test.tsx`

Expected: FAIL — component not found.

- [ ] **Step 3: Create ExclusiveSection**

Create `apps/web/components/marketing/ExclusiveSection.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import { useRoleSelection } from "@/hooks/useRoleSelection";
import { ROLE_CONTENT, type RoleKey } from "@/lib/marketing/role-content";
import RoleChipRow from "./role-selector/RoleChipRow";
import RoleCard from "./role-selector/RoleCard";
import ExclusiveOfferCard from "./role-selector/ExclusiveOfferCard";
import StatCounter from "./role-selector/StatCounter";
import TestimonialStrip from "./role-selector/TestimonialStrip";
import InstitutionLogoRow from "./role-selector/InstitutionLogoRow";

interface Props {
  initialRole: RoleKey | null;
  locale: "zh" | "en";
}

export default function ExclusiveSection({ initialRole, locale }: Props) {
  const t = useTranslations("marketing");
  const { role, setRole, clearRole } = useRoleSelection(initialRole);

  const content = role ? ROLE_CONTENT[role] : null;

  return (
    <section
      className="marketing-exclusive"
      aria-label={t("exclusiveSection.eyebrow")}
    >
      <div className="marketing-exclusive__inner">
        <span className="marketing-exclusive__eyebrow">{t("exclusiveSection.eyebrow")}</span>

        {content ? (
          <>
            <h2 className="marketing-exclusive__title">
              {t("exclusiveSection.populatedTitle", { role: content.label[locale] })}
            </h2>
            <p className="marketing-exclusive__stat-line">
              {t("exclusiveSection.statLinePrefix")}
              <strong title={t("exclusiveSection.statAsOfTooltip", { month: content.stat.asOf })}>
                <StatCounter target={content.stat.count} />
              </strong>
              {t("exclusiveSection.statLineSuffix", {
                role: content.label[locale],
                noun: content.domainNoun[locale],
              })}
              <button
                type="button"
                className="marketing-exclusive__switch"
                onClick={clearRole}
              >
                {t("exclusiveSection.switch")}
              </button>
            </p>

            <RoleChipRow activeRole={role} onSelect={setRole} locale={locale} groupLabel={t("exclusiveSection.chipsLabel")} />

            <div className="marketing-exclusive__cards">
              <RoleCard
                label={t("exclusiveSection.cardLabel.demo")}
                title={content.demo.title[locale]}
                description={content.demo.description[locale]}
              />
              <RoleCard
                label={t("exclusiveSection.cardLabel.templatePack")}
                title={content.templatePack.title[locale]}
                description={content.templatePack.items.map((i) => i[locale]).join(" / ")}
                cta={content.templatePack.cta[locale]}
              />
              <ExclusiveOfferCard
                title={content.offer.title[locale]}
                description={content.offer.description[locale]}
                cta={content.offer.cta[locale]}
                href={content.offer.href}
                badge={t("exclusiveSection.offerBadge")}
              />
            </div>

            <TestimonialStrip
              quote={content.testimonial.quote[locale]}
              name={content.testimonial.name}
              title={content.testimonial.title[locale]}
              avatarInitial={content.testimonial.avatarInitial}
            />

            <InstitutionLogoRow
              heading={t("exclusiveSection.logosHeading")}
              names={content.institutions}
            />
          </>
        ) : (
          <>
            <h2 className="marketing-exclusive__title">
              {t("exclusiveSection.emptyTitle")}
            </h2>
            <p className="marketing-exclusive__hint">{t("exclusiveSection.emptyHint")}</p>
            <RoleChipRow activeRole={null} onSelect={setRole} locale={locale} groupLabel={t("exclusiveSection.chipsLabel")} />
            <div className="marketing-exclusive__cards">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="marketing-exclusive__card marketing-exclusive__card--placeholder"
                  aria-hidden="true"
                >
                  {t("exclusiveSection.placeholderCard")}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && pnpm test:unit -- tests/unit/exclusive-section.test.tsx`

Expected: PASS — 4 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/marketing/ExclusiveSection.tsx apps/web/tests/unit/exclusive-section.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(web): ExclusiveSection container — empty vs populated + switch

Composes RoleChipRow, 3 cards, StatCounter, TestimonialStrip, and
InstitutionLogoRow. Accepts initialRole from the server (SSR cookie
read) to avoid a flash of empty state. Client-side state flows
through useRoleSelection; switch button clears the cookie and
returns to empty state.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Hero role badge

**Files:**
- Modify: `apps/web/components/marketing/HeroSection.tsx`
- Test: `apps/web/tests/unit/hero-role-badge.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `apps/web/tests/unit/hero-role-badge.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Mock server-only next-intl helper used by HeroSection.
vi.mock("next-intl/server", () => ({
  getTranslations: async (_ns?: string) => (key: string, values?: Record<string, string>) => {
    if (!values) return key;
    return Object.keys(values).reduce(
      (acc, name) => acc.replaceAll(`{${name}}`, String(values[name])),
      key,
    );
  },
}));

// Stub heavy client children so the server component renders plainly in jsdom.
vi.mock("@/components/marketing/HeroAnimatedClient", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/marketing/HeroCanvasStage", () => ({
  default: () => null,
}));

import HeroSection from "@/components/marketing/HeroSection";

async function renderServer(jsx: Promise<React.ReactElement>) {
  const el = await jsx;
  return render(el);
}

describe("HeroSection role badge", () => {
  it("does not render the badge when role is null", async () => {
    await renderServer(HeroSection({ role: null, locale: "zh" }) as unknown as Promise<React.ReactElement>);
    expect(screen.queryByTestId("hero-role-badge")).toBeNull();
  });

  it("renders the badge with the role label when role is set", async () => {
    await renderServer(HeroSection({ role: "researcher", locale: "zh" }) as unknown as Promise<React.ReactElement>);
    const badge = screen.getByTestId("hero-role-badge");
    expect(badge.textContent).toContain("研究生");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && pnpm test:unit -- tests/unit/hero-role-badge.test.tsx`

Expected: FAIL — `HeroSection` does not accept `role` / `locale` props.

- [ ] **Step 3: Modify HeroSection**

Open `apps/web/components/marketing/HeroSection.tsx` and replace the function signature + the body so it becomes:

```tsx
import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { ArrowRight, PlayCircle } from "lucide-react";
import HeroAnimatedClient from "./HeroAnimatedClient";
import HeroCanvasStage from "./HeroCanvasStage";
import { ROLE_CONTENT, type RoleKey } from "@/lib/marketing/role-content";

interface HeroSectionProps {
  role?: RoleKey | null;
  locale?: "zh" | "en";
}

export default async function HeroSection({ role = null, locale = "zh" }: HeroSectionProps = {}) {
  const t = await getTranslations("marketing");
  const roleLabel = role ? ROLE_CONTENT[role].label[locale] : null;
  return (
    <section className="marketing-hero">
      <HeroAnimatedClient>
        <div className="marketing-hero__grid">
          <div className="marketing-fade-in">
            {roleLabel ? (
              <span data-testid="hero-role-badge" className="marketing-hero__role-badge">
                ✨ {t("hero.forRole", { role: roleLabel })}
              </span>
            ) : null}
            <span className="marketing-eyebrow mb-4">{t("hero.kicker")}</span>
            <h1
              className="marketing-h1 font-display tracking-tight text-4xl md:text-6xl lg:text-7xl mb-6 md:mb-8"
            >
              {t("hero.title")}
            </h1>
            <p
              className="marketing-lead text-lg md:text-xl leading-relaxed mb-8 md:mb-10"
              style={{ maxWidth: 580 }}
            >
              {t("hero.sub")}
            </p>
            {/* KEEP EVERYTHING BELOW UNCHANGED — do not remove the existing CTA row, etc. */}
```

**Important:** only the new imports, the new `HeroSectionProps` type, the function signature, and the `{roleLabel ? ... : null}` JSX block above `<span className="marketing-eyebrow...">` are new. The rest of the file — CTA buttons, HeroCanvasStage mount, closing tags — stays exactly as it was. If unsure, read the full file first, then apply only this diff.

- [ ] **Step 4: Add the `hero.forRole` i18n key**

Open `apps/web/messages/zh/marketing.json` and add:

```json
"hero.forRole": "为{role}定制",
```

Open `apps/web/messages/en/marketing.json` and add:

```json
"hero.forRole": "Made for {role}",
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd apps/web && pnpm test:unit -- tests/unit/hero-role-badge.test.tsx`

Expected: PASS — 2 tests.

- [ ] **Step 6: Run full unit suite to catch regressions**

Run: `cd apps/web && pnpm test:unit`

Expected: all tests pass, no new failures in existing suites (in particular, prior `marketing-*` tests unaffected since `role` defaults to `null`).

- [ ] **Step 7: Commit**

```bash
git add apps/web/components/marketing/HeroSection.tsx \
        apps/web/messages/zh/marketing.json \
        apps/web/messages/en/marketing.json \
        apps/web/tests/unit/hero-role-badge.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(web): Hero role badge (conditional) for personalized landing

HeroSection now accepts role + locale props and renders a small
"✨ 为 X 定制" badge above the kicker when a role is set. Both
props are optional and default to null/zh, so existing callers
(if any) are unaffected. No Hero copy changes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Wire into the homepage (SSR cookie + mount)

**Files:**
- Modify: `apps/web/app/[locale]/page.tsx`

- [ ] **Step 1: Modify the page**

Open `apps/web/app/[locale]/page.tsx` and replace the whole file with:

```tsx
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { setRequestLocale } from "next-intl/server";

import "@/styles/marketing.css";

import PublicHeader from "@/components/marketing/PublicHeader";
import HeroSection from "@/components/marketing/HeroSection";
import ProblemSection from "@/components/marketing/ProblemSection";
import FeaturesSection from "@/components/marketing/FeaturesSection";
import ScreenshotSection from "@/components/marketing/ScreenshotSection";
import ExclusiveSection from "@/components/marketing/ExclusiveSection";
import PricingSnapshotSection from "@/components/marketing/PricingSnapshotSection";
import CTAFooterSection from "@/components/marketing/CTAFooterSection";
import PublicFooter from "@/components/marketing/PublicFooter";

import { ROLE_KEYS, type RoleKey } from "@/lib/marketing/role-content";
import { ROLE_COOKIE_NAME } from "@/hooks/useRoleSelection";
import { routing } from "@/i18n/routing";

const AUTH_COOKIE_NAMES = [
  "auth_state",
  "mingrun_workspace_id",
  "qihang_workspace_id",
] as const;

function readInitialRole(raw: string | undefined): RoleKey | null {
  if (!raw) return null;
  return (ROLE_KEYS as readonly string[]).includes(raw) ? (raw as RoleKey) : null;
}

export default async function HomePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const localeKey = locale as (typeof routing.locales)[number];
  if (routing.locales.includes(localeKey)) {
    setRequestLocale(localeKey);
  }

  const cookieStore = await cookies();
  const isLoggedIn = AUTH_COOKIE_NAMES.some((name) => Boolean(cookieStore.get(name)));
  if (isLoggedIn) redirect("/app");

  const initialRole = readInitialRole(cookieStore.get(ROLE_COOKIE_NAME)?.value);
  const sectionLocale: "zh" | "en" = localeKey === "en" ? "en" : "zh";

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg-base)" }}>
      <PublicHeader />
      <main>
        <HeroSection role={initialRole} locale={sectionLocale} />
        <ProblemSection />
        <FeaturesSection />
        <ScreenshotSection />
        <ExclusiveSection initialRole={initialRole} locale={sectionLocale} />
        <PricingSnapshotSection />
        <CTAFooterSection />
      </main>
      <PublicFooter />
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd apps/web && ./node_modules/.bin/tsc --noEmit`

Expected: no errors.

- [ ] **Step 3: Smoke the page renders**

Start the dev server if not running (preview_start name `web-dev`), then open http://localhost:3000/ with the `auth_state` cookie cleared. Verify via preview_snapshot that:
- The hero heading is visible.
- A section with `aria-label` "✦ 为你精选 · 独家" exists.
- The empty state title `选择你的身份，解锁定制内容` is present.
- Clicking the 研究生 chip replaces the empty state with cards (presence of `文献综述自动整理`).

- [ ] **Step 4: Commit**

```bash
git add apps/web/app/[locale]/page.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(web): mount ExclusiveSection + pass role to HeroSection on /

Homepage reads mrai_landing_role from the request cookie during
SSR and passes the validated RoleKey to both HeroSection (for the
badge) and ExclusiveSection (for the initial populated state).
Section is inserted between ScreenshotSection and PricingSnapshot.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Playwright e2e smoke

**Files:**
- Create: `apps/web/tests/role-personalized-landing.spec.ts`

- [ ] **Step 1: Write the e2e test**

Create `apps/web/tests/role-personalized-landing.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test.use({ locale: "zh-CN" });

test.describe("Role-personalized landing", () => {
  test.beforeEach(async ({ context }) => {
    await context.clearCookies();
  });

  test("empty state shows chips + placeholders, clicking a chip reveals content", async ({ page }) => {
    await page.goto("/");

    // Section is present with empty state.
    const section = page.locator("section.marketing-exclusive");
    await expect(section).toBeVisible();
    await expect(section.getByText("选择你的身份，解锁定制内容")).toBeVisible();

    // Pick 研究生
    await section.getByRole("radio", { name: "研究生" }).click();

    // Populated content visible
    await expect(section.getByText("文献综述自动整理")).toBeVisible();
    await expect(section.getByText("研究生 5 件套")).toBeVisible();
    await expect(section.getByText(".edu 邮箱 · Pro 免费 6 月")).toBeVisible();

    // Hero badge appears with the role label
    await expect(page.getByTestId("hero-role-badge")).toContainText("研究生");

    // Cookie persisted
    const cookies = await page.context().cookies();
    const roleCookie = cookies.find((c) => c.name === "mrai_landing_role");
    expect(roleCookie?.value).toBe("researcher");
  });

  test("switching to a different role swaps the content", async ({ page }) => {
    await page.goto("/");
    const section = page.locator("section.marketing-exclusive");
    await section.getByRole("radio", { name: "研究生" }).click();
    await expect(section.getByText("文献综述自动整理")).toBeVisible();

    await section.getByRole("radio", { name: "律师" }).click();
    await expect(section.getByText("合同摘要 10 秒出")).toBeVisible();
    await expect(section.getByText("文献综述自动整理")).toHaveCount(0);
  });

  test("switch button clears the role and returns to empty state", async ({ page }) => {
    await page.goto("/");
    const section = page.locator("section.marketing-exclusive");
    await section.getByRole("radio", { name: "医生" }).click();
    await expect(section.getByText("门诊随手记结构化")).toBeVisible();

    await section.getByRole("button", { name: "切换" }).click();
    await expect(section.getByText("选择你的身份，解锁定制内容")).toBeVisible();
    await expect(page.getByTestId("hero-role-badge")).toHaveCount(0);
  });

  test("returning visitor sees their role on reload (SSR hydration)", async ({ page }) => {
    await page.goto("/");
    const section = page.locator("section.marketing-exclusive");
    await section.getByRole("radio", { name: "创业者" }).click();
    await expect(section.getByText("客户访谈自动提炼洞察")).toBeVisible();

    await page.reload();
    await expect(page.getByTestId("hero-role-badge")).toContainText("创业者");
    await expect(section.getByText("客户访谈自动提炼洞察")).toBeVisible();
  });
});
```

- [ ] **Step 2: Run the e2e suite**

Run: `cd apps/web && pnpm e2e -- role-personalized-landing.spec.ts`

Expected: 4 tests pass.

- [ ] **Step 3: Commit**

```bash
git add apps/web/tests/role-personalized-landing.spec.ts
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
test(web): Playwright smoke for role-personalized landing

Covers (1) empty state → chip click reveals content + cookie, (2)
role swap, (3) 切换 button resets to empty state + hero badge gone,
(4) returning visitor sees their role on reload via SSR hydration.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Analytics event stubs

**Files:**
- Create: `apps/web/lib/marketing/analytics.ts`
- Modify: `apps/web/components/marketing/ExclusiveSection.tsx`
- Test: `apps/web/tests/unit/marketing-analytics.test.ts`

- [ ] **Step 1: Write the failing test**

Create `apps/web/tests/unit/marketing-analytics.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { emitLandingEvent } from "@/lib/marketing/analytics";

describe("emitLandingEvent", () => {
  const origEnv = process.env.NODE_ENV;
  const origDebug = vi.spyOn(console, "debug");

  beforeEach(() => origDebug.mockClear());
  afterEach(() => {
    Object.defineProperty(process.env, "NODE_ENV", { value: origEnv });
  });

  it("logs in development", () => {
    Object.defineProperty(process.env, "NODE_ENV", { value: "development" });
    emitLandingEvent("landing.role.selected", { role: "researcher", locale: "zh" });
    expect(origDebug).toHaveBeenCalledWith(
      "[mrai.analytics]",
      "landing.role.selected",
      { role: "researcher", locale: "zh" },
    );
  });

  it("is a noop in production", () => {
    Object.defineProperty(process.env, "NODE_ENV", { value: "production" });
    emitLandingEvent("landing.role.selected", { role: "researcher", locale: "zh" });
    expect(origDebug).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && pnpm test:unit -- tests/unit/marketing-analytics.test.ts`

Expected: FAIL — module not found.

- [ ] **Step 3: Create the analytics module**

Create `apps/web/lib/marketing/analytics.ts`:

```ts
export type LandingEvent =
  | "landing.role.selected"
  | "landing.role.switched"
  | "landing.role.cleared"
  | "landing.role.restored"
  | "landing.offer.clicked";

export function emitLandingEvent(
  event: LandingEvent,
  payload: Record<string, string | number | null | undefined>,
): void {
  if (process.env.NODE_ENV !== "production") {
    // eslint-disable-next-line no-console
    console.debug("[mrai.analytics]", event, payload);
    return;
  }
  // TODO: wire to real analytics provider (Plausible / PostHog / Amplitude).
}
```

- [ ] **Step 4: Wire into ExclusiveSection**

Open `apps/web/components/marketing/ExclusiveSection.tsx`. At the top, add:

```ts
import { emitLandingEvent } from "@/lib/marketing/analytics";
import { useEffect, useRef } from "react";
```

Replace the inner body that calls `useRoleSelection(initialRole)` with a wrapped version that emits events. Add this block right after `const { role, setRole, clearRole } = useRoleSelection(initialRole);`:

```tsx
const restoredOnce = useRef(false);
useEffect(() => {
  if (!restoredOnce.current && role && initialRole === role) {
    restoredOnce.current = true;
    emitLandingEvent("landing.role.restored", { role, locale });
  }
}, [role, initialRole, locale]);

function handleSelect(next: RoleKey) {
  if (role && role !== next) {
    emitLandingEvent("landing.role.switched", { fromRole: role, toRole: next, locale });
  } else if (!role) {
    emitLandingEvent("landing.role.selected", { role: next, locale });
  }
  setRole(next);
}

function handleClear() {
  if (role) emitLandingEvent("landing.role.cleared", { fromRole: role, locale });
  clearRole();
}
```

Then replace `onSelect={setRole}` with `onSelect={handleSelect}` and `onClick={clearRole}` with `onClick={handleClear}` (there are 2 `setRole` call sites — one in each branch of the empty/populated conditional; update both).

For the offer CTA emission, pass a callback down into `ExclusiveOfferCard`. Update ExclusiveOfferCard first — open `apps/web/components/marketing/role-selector/ExclusiveOfferCard.tsx` and add an optional `onClick?: () => void` prop:

```tsx
interface Props {
  title: string;
  description: string;
  cta: string;
  href: string;
  badge: string;
  onClick?: () => void;
}

export default function ExclusiveOfferCard({ title, description, cta, href, badge, onClick }: Props) {
  return (
    <div className="marketing-exclusive__card marketing-exclusive__card--offer">
      <span className="marketing-exclusive__offer-badge">{badge}</span>
      <span className="marketing-exclusive__card-label marketing-exclusive__card-label--offer">
        专属优惠
      </span>
      <h4 className="marketing-exclusive__card-title">{title}</h4>
      <p className="marketing-exclusive__card-body">{description}</p>
      <Link href={href} className="marketing-exclusive__offer-cta" onClick={onClick}>
        {cta}
      </Link>
    </div>
  );
}
```

In `ExclusiveSection.tsx`, pass:

```tsx
<ExclusiveOfferCard
  title={content.offer.title[locale]}
  description={content.offer.description[locale]}
  cta={content.offer.cta[locale]}
  href={content.offer.href}
  badge={t("exclusiveSection.offerBadge")}
  onClick={() => emitLandingEvent("landing.offer.clicked", {
    role: role as string,
    offerHref: content.offer.href,
    locale,
  })}
/>
```

- [ ] **Step 5: Run tests to verify**

Run: `cd apps/web && pnpm test:unit`

Expected: all previous tests still pass; the new `marketing-analytics.test.ts` passes (2 tests). The `exclusive-section.test.tsx` still passes because identity translator + the new `handleSelect` indirection still call `setRole` internally.

- [ ] **Step 6: Commit**

```bash
git add apps/web/lib/marketing/analytics.ts \
        apps/web/components/marketing/ExclusiveSection.tsx \
        apps/web/components/marketing/role-selector/ExclusiveOfferCard.tsx \
        apps/web/tests/unit/marketing-analytics.test.ts
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(web): landing analytics stubs (selected/switched/cleared/offer)

emitLandingEvent logs to console.debug in development and is a
noop in production until a real provider is wired. ExclusiveSection
emits selected / switched / cleared / restored events; offer CTA
click emits landing.offer.clicked with the offer href.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Post-implementation verification

- [ ] **Run the full unit suite**: `cd apps/web && pnpm test:unit` — expect 0 failures.
- [ ] **Run the e2e suite**: `cd apps/web && pnpm e2e -- role-personalized-landing.spec.ts marketing-homepage.spec.ts` — expect both suites pass (marketing-homepage unaffected; role-personalized passes).
- [ ] **Typecheck**: `cd apps/web && ./node_modules/.bin/tsc --noEmit` — 0 errors.
- [ ] **Lint**: `cd apps/web && pnpm lint` — 0 new warnings.
- [ ] **Visual check via preview**: open `/` in the browser, verify (a) empty state shows chips + 3 placeholder cards; (b) picking a chip reveals the 3 cards, testimonial, logos, and hero badge; (c) refreshing keeps the selection; (d) `切换` returns to empty; (e) at 375px viewport, cards stack to 1 column.
- [ ] **Open the `/en` route** and confirm English content renders for any role.

---

## Self-review notes (plan author)

- Spec §3 flow → Tasks 9, 10, 11 (empty state, chip click, SSR hydration, switch).
- Spec §4.1 composition → Task 11 (page.tsx mount between ScreenshotSection and PricingSnapshotSection).
- Spec §4.2 hero badge → Task 10.
- Spec §4.3 layouts (empty + populated) → Task 9.
- Spec §4.4 3-card contract + warm accent → Task 5 + Task 8 (CSS).
- Spec §4.5 social proof trio → Tasks 3 (stat), 6 (testimonial + logos), 9 (composed inside section).
- Spec §5 roles → Task 1 (all 6 defined).
- Spec §6 content model → Task 1.
- Spec §7 component inventory → Tasks 3, 4, 5, 6, 9.
- Spec §8 cookie semantics → Task 2 (30-day max-age via `writeCookie`), Task 11 (SSR read + validation).
- Spec §9 interactions → Task 4 (keyboard nav), Task 8 (focus-visible CSS, reduced-motion transitions), Task 9 (switch button).
- Spec §10 a11y → Task 4 (radiogroup + aria-checked + aria-label without emoji), Task 3 (aria-live), Task 8 (focus rings, contrast).
- Spec §11 analytics → Task 13 (stub + events).
- Spec §12 i18n → Tasks 7, 10 (hero.forRole).
- Spec §13 testing → Tasks 1–6, 9, 10, 12, 13 test steps.
- Spec §14 out of scope — honored: no URL param, no real-time stats, no bitmap logos, no pricing CTA change.
- Spec §15 open questions — placeholder cards static (implemented in Task 9 as a plain div); illustrative counts with `asOf` tooltip (Task 7 key + Task 9 tooltip wiring).
