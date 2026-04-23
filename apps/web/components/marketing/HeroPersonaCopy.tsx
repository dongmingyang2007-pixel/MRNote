"use client";

import { type ReactNode, useState } from "react";
import { ArrowRight, BookOpen, Network, PlayCircle, Sparkles } from "lucide-react";
import { Link } from "@/i18n/navigation";
import HeroCanvasStage from "./HeroCanvasStage";

/**
 * Hero copy + CTA + canvas. Self-contained 3-persona segmented control
 * — NOT wired to RoleContext, because the homepage Hero is a fixed
 * bilingual "student / researcher / PM" narrative and should stay
 * consistent regardless of which of the 6 ExclusiveSection roles the
 * visitor has picked downstream.
 *
 * Each persona supplies:
 *   - pill label + icon
 *   - kicker text (the NEW pill tagline)
 *   - split title (prefix + <em> + middle + <mark> + suffix)
 *   - sub lead
 *   - primary + secondary CTA labels
 *   - three foot-dot bullets (key capabilities)
 *   - focusWin → which stage slot lifts forward
 */

type PersonaId = "student" | "researcher" | "pm";
type FocusWin = "memory" | "ai" | "study";

interface Persona {
  id: PersonaId;
  labelZh: string;
  labelEn: string;
  icon: ReactNode;
  focusWin: FocusWin;
  kickerZh: string;
  kickerEn: string;
  titleZh: ReactNode;
  titleEn: ReactNode;
  subZh: string;
  subEn: string;
  ctaPrimaryZh: string;
  ctaPrimaryEn: string;
  ctaSecondaryZh: string;
  ctaSecondaryEn: string;
  footZh: [string, string, string];
  footEn: [string, string, string];
}

const PERSONAS: Persona[] = [
  {
    id: "student",
    labelZh: "学生",
    labelEn: "Student",
    icon: <BookOpen size={13} aria-hidden="true" />,
    focusWin: "study",
    kickerZh: "为备考、论文、组会同时打开的你",
    kickerEn: "For when exams, papers, and lab meetings all pile up",
    titleZh: (
      <>
        把整学期的<em>讲义、AI 问答与复习</em>，
        <br />
        留在<mark>一块永不关闭的画布上</mark>。
      </>
    ),
    titleEn: (
      <>
        Keep a whole semester of <em>lectures, AI Q&amp;A, and revision</em>
        <br />
        on <mark>one canvas that never closes</mark>.
      </>
    ),
    subZh:
      "把教材、笔记、flashcard 和对助教的 AI 追问拖到同一块 notebook 上。考前一天打开，就是上周学到哪儿。",
    subEn:
      "Drop textbooks, notes, flashcards, and AI follow-ups onto one notebook. The day before the exam, it opens exactly where last week left off.",
    ctaPrimaryZh: "学生免费开始",
    ctaPrimaryEn: "Start free for students",
    ctaSecondaryZh: "看 2 分钟学生演示",
    ctaSecondaryEn: "Watch 2-min student demo",
    footZh: [
      "edu 邮箱永久 Pro 免费",
      "期末自动生成复习包",
      "flashcards 按 FSRS 自动排期",
    ],
    footEn: [
      ".edu email unlocks Pro free",
      "Auto-built revision packs at term end",
      "FSRS-scheduled flashcards",
    ],
  },
  {
    id: "researcher",
    labelZh: "研究者",
    labelEn: "Researcher",
    icon: <Network size={13} aria-hidden="true" />,
    focusWin: "memory",
    kickerZh: "给需要跨论文、跨实验串线的你",
    kickerEn: "For threading ideas across papers and experiments",
    titleZh: (
      <>
        让论文、实验与灵感
        <br />
        在<mark>同一张记忆图谱</mark>里<em>自己长出边</em>。
      </>
    ),
    titleEn: (
      <>
        Let papers, experiments, and ideas
        <br />
        <em>grow their own edges</em> on <mark>one memory graph</mark>.
      </>
    ),
    subZh:
      "PDF、实验记录、对 AI 的追问都可追溯到源页面。每一个结论都挂着 evidence，下周再读也认得出自己的思路。",
    subEn:
      "PDFs, lab notes, and AI follow-ups all trace back to the source page. Every conclusion is attached to evidence so next week still feels like your own thinking.",
    ctaPrimaryZh: "研究者免费开始",
    ctaPrimaryEn: "Start free as a researcher",
    ctaSecondaryZh: "阅读 Memory V3 白皮书",
    ctaSecondaryEn: "Read the Memory V3 paper",
    footZh: [
      "支持 PDF / LaTeX / Zotero",
      "引用级 evidence 追溯",
      "私有部署可选",
    ],
    footEn: [
      "PDF · LaTeX · Zotero support",
      "Citation-level evidence trail",
      "Self-hosting available",
    ],
  },
  {
    id: "pm",
    labelZh: "产品经理",
    labelEn: "Product Manager",
    icon: <Sparkles size={13} aria-hidden="true" />,
    focusWin: "ai",
    kickerZh: "给一天同时推进 6 个方向的你",
    kickerEn: "For the PM pushing six directions at once",
    titleZh: (
      <>
        别再一遍遍给新会议
        <br />
        <em>重述上下文</em>。<mark>让 notebook 替你记得。</mark>
      </>
    ),
    titleEn: (
      <>
        Stop <em>re-explaining context</em>
        <br />
        at every new meeting. <mark>Let the notebook remember.</mark>
      </>
    ),
    subZh:
      "spec、用研、反馈和 AI 摘要都留在这个 project 的 notebook。新成员打开，5 分钟就能读懂这事为什么这么定。",
    subEn:
      "Specs, user research, feedback, and AI summaries all live on the project notebook. A new teammate opens it and understands why it's shaped this way in five minutes.",
    ctaPrimaryZh: "免费开始，无需信用卡",
    ctaPrimaryEn: "Start free — no credit card",
    ctaSecondaryZh: "看 PM 工作流演示",
    ctaSecondaryEn: "Watch the PM workflow demo",
    footZh: [
      "spec / research / RFC 统一画布",
      "每日 digest 防止跟进遗漏",
      "团队共享上下文",
    ],
    footEn: [
      "Spec · research · RFC on one canvas",
      "Daily digest catches every follow-up",
      "Shared team context",
    ],
  },
];

export default function HeroPersonaCopy({ locale }: { locale: "zh" | "en" }) {
  const [personaId, setPersonaId] = useState<PersonaId>("researcher");
  const persona = PERSONAS.find((p) => p.id === personaId) ?? PERSONAS[0];

  const label = (p: Persona) => (locale === "zh" ? p.labelZh : p.labelEn);
  const kicker = locale === "zh" ? persona.kickerZh : persona.kickerEn;
  const title = locale === "zh" ? persona.titleZh : persona.titleEn;
  const sub = locale === "zh" ? persona.subZh : persona.subEn;
  const ctaPrimary =
    locale === "zh" ? persona.ctaPrimaryZh : persona.ctaPrimaryEn;
  const ctaSecondary =
    locale === "zh" ? persona.ctaSecondaryZh : persona.ctaSecondaryEn;
  const foot = locale === "zh" ? persona.footZh : persona.footEn;
  const switcherLabel = locale === "zh" ? "我是一位" : "I'm a";

  return (
    <>
      <div
        className="marketing-persona-switch"
        role="tablist"
        aria-label={switcherLabel}
      >
        <span className="marketing-persona-switch__label">{switcherLabel}</span>
        <div className="marketing-persona-switch__track">
          {PERSONAS.map((p) => (
            <button
              key={p.id}
              type="button"
              role="tab"
              aria-selected={p.id === personaId}
              className={
                p.id === personaId
                  ? "marketing-persona-switch__tab is-active"
                  : "marketing-persona-switch__tab"
              }
              onClick={() => setPersonaId(p.id)}
            >
              {p.icon}
              {label(p)}
            </button>
          ))}
        </div>
      </div>

      <div className="marketing-hero__kicker-row">
        <span className="marketing-hero__kicker-pill">NEW</span>
        <span>{kicker}</span>
        <ArrowRight size={12} aria-hidden="true" />
      </div>

      <h1 className="marketing-hero__title">{title}</h1>
      <p className="marketing-hero__sub">{sub}</p>

      <div className="marketing-hero__cta-row">
        <Link
          href="/register"
          className="marketing-btn marketing-btn--primary marketing-btn--lg"
        >
          {ctaPrimary}
          <ArrowRight size={16} aria-hidden="true" />
        </Link>
        <Link
          href="/#features"
          className="marketing-btn marketing-btn--secondary marketing-btn--lg"
        >
          <PlayCircle size={14} aria-hidden="true" />
          {ctaSecondary}
        </Link>
      </div>

      <div className="marketing-hero__foot">
        {foot.map((f) => (
          <span key={f} className="marketing-hero__foot-dot">
            {f}
          </span>
        ))}
      </div>

      <div className="marketing-hero__demo-wrap">
        <HeroCanvasStage focusWin={persona.focusWin} />
      </div>
    </>
  );
}
