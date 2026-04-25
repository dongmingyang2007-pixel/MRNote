"use client";

import { type ReactNode, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  Network,
  PlayCircle,
  Sparkles,
} from "lucide-react";
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
    kickerZh: "先把要写的东西放下来",
    kickerEn: "Start with the page in front of you",
    titleZh: (
      <>
        讲义、摘录、复习题，
        <br />
        先放进<mark>同一张 notebook</mark>。
      </>
    ),
    titleEn: (
      <>
        Lectures, quotes, and revision notes
        <br />
        belong in <mark>one notebook</mark>.
      </>
    ),
    subZh:
      "先写一页，试试手感。等你想保存、上传资料或整理复习卡时，再创建账号也来得及。",
    subEn:
      "Write a page first and see how it feels. Create an account only when you want to save, upload sources, or build review cards.",
    ctaPrimaryZh: "先写一页",
    ctaPrimaryEn: "Start writing",
    ctaSecondaryZh: "看看工作台",
    ctaSecondaryEn: "See the workspace",
    footZh: ["试写无需注册", "保存时再创建账号", "资料和复习卡留到工作区"],
    footEn: [
      "No account to start",
      "Sign up when saving",
      "Sources and cards stay in workspace",
    ],
  },
  {
    id: "researcher",
    labelZh: "研究者",
    labelEn: "Researcher",
    icon: <Network size={13} aria-hidden="true" />,
    focusWin: "memory",
    kickerZh: "写论文之前，先把线索摆好",
    kickerEn: "Lay out the thread before the paper",
    titleZh: (
      <>
        论文、实验和灵感，
        <br />
        应该<mark>能互相找到</mark>。
      </>
    ),
    titleEn: (
      <>
        Papers, experiments, and ideas
        <br />
        should <mark>find each other</mark>.
      </>
    ),
    subZh:
      "先在草稿页里写下问题和证据。等需要保存、引用来源或打开图谱时，再把它放进你的账号。",
    subEn:
      "Start by writing the question and evidence. When you need to save, cite sources, or open the graph, move it into your account.",
    ctaPrimaryZh: "打开一张草稿",
    ctaPrimaryEn: "Open a draft",
    ctaSecondaryZh: "看图谱怎么工作",
    ctaSecondaryEn: "See how the graph works",
    footZh: ["草稿先在浏览器里", "保存后进入 notebook", "图谱按来源继续生长"],
    footEn: [
      "Draft locally first",
      "Save into a notebook",
      "Graph grows from sources",
    ],
  },
  {
    id: "pm",
    labelZh: "产品经理",
    labelEn: "Product Manager",
    icon: <Sparkles size={13} aria-hidden="true" />,
    focusWin: "ai",
    kickerZh: "少一点仪式感，多一点继续写",
    kickerEn: "Less ceremony. More getting back to the page.",
    titleZh: (
      <>
        打开工作台，
        <br />
        直接写下一步。
      </>
    ),
    titleEn: (
      <>
        Open the workspace
        <br />
        and write the next thing.
      </>
    ),
    subZh:
      "MRNote 不急着要你注册。先写页面；等你要保存、上传资料、让助手整理或继续到下一次，再登录。",
    subEn:
      "MRNote does not ask for signup first. Write the page; log in when you want to save, upload sources, clean it up, or come back later.",
    ctaPrimaryZh: "先写一页",
    ctaPrimaryEn: "Start writing",
    ctaSecondaryZh: "看看真实界面",
    ctaSecondaryEn: "See the real interface",
    footZh: ["不用注册也能试写", "保存时注册", "工作区接住后续动作"],
    footEn: [
      "Try writing without signup",
      "Sign up when saving",
      "Workspace holds the follow-up",
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
          href="/app/notebooks"
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
