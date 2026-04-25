"use client";

import type { CSSProperties, ReactNode } from "react";
import { useLocale } from "next-intl";
import {
  Bell,
  BookOpen,
  Brain,
  CheckCircle2,
  ChevronRight,
  Circle,
  FileText,
  GraduationCap,
  Layers3,
  MessageSquareText,
  Network,
  Search,
  Settings,
  Sparkles,
  Upload,
} from "lucide-react";

type PreviewLocale = "zh" | "en";

export type WorkspaceFocus = "editor" | "graph" | "ai" | "study" | "search";

type Surface = "hero" | "feature" | "screenshot";
type GraphSurface = "feature" | "memory" | "window";

function usePreviewLocale(): PreviewLocale {
  return useLocale() === "en" ? "en" : "zh";
}

function text(locale: PreviewLocale, zh: string, en: string) {
  return locale === "en" ? en : zh;
}

function focusClass(focused: boolean) {
  return focused ? " is-preview-focused" : "";
}

interface ProductWindowProps {
  title: string;
  meta?: string;
  icon?: ReactNode;
  className?: string;
  children: ReactNode;
  style?: CSSProperties;
  focused?: boolean;
}

export function MarketingProductWindow({
  title,
  meta,
  icon,
  className,
  children,
  style,
  focused = false,
}: ProductWindowProps) {
  return (
    <article
      className={`marketing-product-window${focused ? " is-preview-focused" : ""}${
        className ? ` ${className}` : ""
      }`}
      style={style}
    >
      <header className="marketing-product-window__bar">
        <span className="marketing-product-window__traffic" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
        <span className="marketing-product-window__title">
          {icon}
          <strong>{title}</strong>
        </span>
        {meta ? (
          <span className="marketing-product-window__meta">{meta}</span>
        ) : null}
      </header>
      <div className="marketing-product-window__body">{children}</div>
    </article>
  );
}

export function WorkspaceEditorContent() {
  const locale = usePreviewLocale();
  const tasks = [
    text(
      locale,
      "把访谈里的原话放回正文",
      "Bring interview quotes back into the page",
    ),
    text(
      locale,
      "对比 3 份竞品资料里的共同问题",
      "Compare common issues across 3 competitor notes",
    ),
    text(
      locale,
      "列出下周要验证的 3 件事",
      "List 3 things to validate next week",
    ),
  ];

  return (
    <div className="marketing-product-note">
      <div className="marketing-product-note__crumb">
        <BookOpen size={13} />
        <span>{text(locale, "产品方案草稿", "Product plan draft")}</span>
        <ChevronRight size={12} />
        <span>{text(locale, "项目线索", "Project thread")}</span>
      </div>
      <h3>{text(locale, "新版编辑器草稿", "Editor redesign notes")}</h3>
      <p>
        {text(
          locale,
          "页面、资料和助手对话保留在同一个画布里。每次回来写，相关摘录、待办和图谱节点都在旁边。",
          "Pages, sources, and assistant conversations stay on the same canvas. When writing resumes, related quotes, tasks, and graph nodes are still nearby.",
        )}
      </p>
      <div className="marketing-product-note__callout">
        <Sparkles size={14} />
        <span>
          {text(
            locale,
            "已关联 9 条来源：访谈原话、竞品截图和上周的周会记录。",
            "9 sources linked: interview quotes, competitor screenshots, and last week's meeting notes.",
          )}
        </span>
      </div>
      <ul className="marketing-product-checklist">
        {tasks.map((task) => (
          <li key={task}>
            <CheckCircle2 size={14} />
            <span>{task}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function AiPanelContent() {
  const locale = usePreviewLocale();
  return (
    <div className="marketing-product-ai">
      <div className="marketing-product-ai__message is-user">
        {text(
          locale,
          "把这页里的结论和原始摘录对上。",
          "Match this page's conclusions to the original quotes.",
        )}
      </div>
      <div className="marketing-product-ai__message is-assistant">
        <span className="marketing-product-ai__badge">
          <Brain size={13} />
          {text(locale, "记忆召回", "memory recall")}
        </span>
        <p>
          {text(
            locale,
            "找到 4 个相关节点：访谈原话、PDF 第 12 页、周会记录和复习卡。",
            "Found 4 related nodes: interview quote, page 12 of the PDF, weekly notes, and a review card.",
          )}
        </p>
        <div className="marketing-product-sources">
          <span>interview.md</span>
          <span>roadmap.pdf</span>
          <span>weekly notes</span>
        </div>
      </div>
    </div>
  );
}

export function SearchPanelContent() {
  const locale = usePreviewLocale();
  const rows = [
    {
      type: text(locale, "页面", "Page"),
      title: text(locale, "新版编辑器草稿", "Editor redesign notes"),
      snippet: text(
        locale,
        "页面、资料和助手窗口并排放着",
        "Page, sources, and assistant window sit side by side",
      ),
    },
    {
      type: text(locale, "记忆", "Memory"),
      title: text(locale, "保存时再注册", "Sign up when saving"),
      snippet: text(
        locale,
        "来自 6 个页面和 2 份资料",
        "From 6 pages and 2 sources",
      ),
    },
    {
      type: text(locale, "资料", "Source"),
      title: text(locale, "User Interviews.pdf", "User Interviews.pdf"),
      snippet: text(locale, "摘录 18 · 第 42 页", "excerpt 18 · page 42"),
    },
  ];

  return (
    <div className="marketing-product-search">
      <div className="marketing-product-search__input">
        <Search size={14} />
        <span>
          {text(
            locale,
            "搜索页面、文件、图谱和助手记录",
            "Search pages, files, graph, and assistant notes",
          )}
        </span>
      </div>
      <div className="marketing-product-search__list">
        {rows.map((row) => (
          <div
            key={`${row.type}-${row.title}`}
            className="marketing-product-search__row"
          >
            <span>{row.type}</span>
            <strong>{row.title}</strong>
            <small>{row.snippet}</small>
          </div>
        ))}
      </div>
    </div>
  );
}

export function StudyPanelContent() {
  const locale = usePreviewLocale();
  const cards = [
    text(
      locale,
      "为什么这段材料要保留页码?",
      "Why should this passage keep its page number?",
    ),
    text(
      locale,
      "解释这章和上一章的关系",
      "Explain how this chapter relates to the previous one",
    ),
    text(
      locale,
      "从原文做 3 张复习卡",
      "Make 3 review cards from the source text",
    ),
  ];

  return (
    <div className="marketing-product-study">
      <div className="marketing-product-study__asset">
        <Upload size={14} />
        <span>
          <strong>
            {text(locale, "用户研究材料.pdf", "User Research.pdf")}
          </strong>
          <small>
            {text(
              locale,
              "42 段摘录 · 已整理概览页",
              "42 excerpts · overview page ready",
            )}
          </small>
        </span>
      </div>
      <div className="marketing-product-study__progress">
        <span />
      </div>
      <div className="marketing-product-study__cards">
        {cards.map((card) => (
          <button key={card} type="button" tabIndex={-1}>
            <Layers3 size={13} />
            <span>{card}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

const graphNodes = [
  {
    id: "workspace",
    labelZh: "工作区",
    labelEn: "Workspace",
    x: 50,
    y: 30,
    role: "subject",
  },
  {
    id: "memory",
    labelZh: "项目记忆",
    labelEn: "Project memory",
    x: 31,
    y: 42,
    role: "concept",
  },
  {
    id: "source",
    labelZh: "原文摘录",
    labelEn: "Source quote",
    x: 66,
    y: 48,
    role: "fact",
  },
  {
    id: "study",
    labelZh: "学习资料",
    labelEn: "Study source",
    x: 43,
    y: 65,
    role: "summary",
  },
  {
    id: "digest",
    labelZh: "周记录",
    labelEn: "Weekly note",
    x: 72,
    y: 21,
    role: "structure",
  },
  {
    id: "cards",
    labelZh: "复习卡",
    labelEn: "Flashcards",
    x: 22,
    y: 22,
    role: "summary",
  },
] as const;

const graphEdges = [
  ["workspace", "memory", "evidence"],
  ["workspace", "source", "evidence"],
  ["memory", "study", "prerequisite"],
  ["source", "digest", "summary"],
  ["study", "cards", "related"],
  ["cards", "memory", "related"],
  ["digest", "workspace", "summary"],
] as const;

function GraphMiniCanvas({ dark = false }: { dark?: boolean }) {
  const locale = usePreviewLocale();
  const byId = Object.fromEntries(graphNodes.map((node) => [node.id, node]));

  return (
    <svg
      className="marketing-product-graph-svg"
      viewBox="0 0 100 78"
      role="img"
      aria-label={text(
        locale,
        "实际记忆图谱预览",
        "Actual memory graph preview",
      )}
    >
      <defs>
        <filter
          id={dark ? "mkt-graph-dark-glow" : "mkt-graph-glow"}
          x="-60%"
          y="-60%"
          width="220%"
          height="220%"
        >
          <feGaussianBlur stdDeviation="2.4" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <rect width="100" height="78" rx="4" fill="transparent" />
      {graphEdges.map(([a, b, rel]) => {
        const from = byId[a];
        const to = byId[b];
        return (
          <g key={`${a}-${b}`}>
            <line
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              className={`marketing-product-graph-edge is-${rel}`}
            />
          </g>
        );
      })}
      {graphNodes.map((node) => (
        <g
          key={node.id}
          className={`marketing-product-graph-node is-${node.role}${
            node.id === "workspace" ? " is-selected" : ""
          }`}
          transform={`translate(${node.x} ${node.y})`}
        >
          <circle r={node.id === "workspace" ? 6.4 : 4.8} />
          <text y={node.id === "workspace" ? 15 : 12}>
            {locale === "en" ? node.labelEn : node.labelZh}
          </text>
        </g>
      ))}
    </svg>
  );
}

export function MarketingGraphPreview({
  variant = "light",
  surface = "feature",
}: {
  variant?: "light" | "dark";
  surface?: GraphSurface;
}) {
  const locale = usePreviewLocale();
  const dark = variant === "dark";

  return (
    <div
      className={`marketing-product-screen marketing-product-screen--graph marketing-product-screen--${surface}${
        dark ? " is-dark" : ""
      }`}
    >
      <header className="marketing-graph-preview__header">
        <div>
          <span>{text(locale, "Memory Graph", "Memory Graph")}</span>
          <strong>{text(locale, "产品方案草稿", "Product plan draft")}</strong>
        </div>
        <div className="marketing-graph-preview__actions" aria-hidden="true">
          <button type="button" tabIndex={-1}>
            2D
          </button>
          <button type="button" tabIndex={-1}>
            3D
          </button>
          <button type="button" tabIndex={-1}>
            {text(locale, "重排", "Fit")}
          </button>
        </div>
      </header>
      <div className="marketing-graph-preview__filters">
        <span>
          <Search size={13} />
          {text(locale, "保存时再注册", "sign up when saving")}
        </span>
        <span>{text(locale, "线索 32", "32 threads")}</span>
        <span>{text(locale, "摘录 128", "128 quotes")}</span>
      </div>
      <div className="marketing-graph-preview__main">
        <div className="marketing-graph-preview__canvas">
          <GraphMiniCanvas dark={dark} />
        </div>
        <aside className="marketing-graph-preview__drawer">
          <span className="marketing-graph-preview__drawer-kicker">
            {text(locale, "选中节点", "Selected node")}
          </span>
          <h3>{text(locale, "工作区", "Workspace")}</h3>
          <p>
            {text(
              locale,
              "和项目记忆、原文摘录、周记录、复习卡都连在一起。",
              "Connected to project memory, source quotes, weekly notes, and review cards.",
            )}
          </p>
          <div className="marketing-graph-preview__neighbors">
            <span>{text(locale, "项目记忆", "Project memory")}</span>
            <span>{text(locale, "原文摘录", "Source quote")}</span>
            <span>{text(locale, "周记录", "Weekly note")}</span>
          </div>
        </aside>
      </div>
    </div>
  );
}

export function MarketingStudyPreview({
  surface = "feature",
}: {
  surface?: Surface;
}) {
  const locale = usePreviewLocale();
  return (
    <div
      className={`marketing-product-screen marketing-product-screen--study marketing-product-screen--${surface}`}
    >
      <aside className="marketing-study-preview__rail">
        <span className="marketing-study-preview__rail-kicker">
          {text(locale, "学习素材", "Study assets")}
        </span>
        <strong>User Research.pdf</strong>
        <small>
          {text(
            locale,
            "42 段摘录 · 7 页 · 18 张卡",
            "42 excerpts · 7 pages · 18 cards",
          )}
        </small>
        <div className="marketing-study-preview__tabs">
          <span className="is-active">{text(locale, "概览", "Overview")}</span>
          <span>{text(locale, "问答", "Q&A")}</span>
          <span>{text(locale, "复习", "Review")}</span>
        </div>
      </aside>
      <main className="marketing-study-preview__main">
        <section className="marketing-study-preview__reader">
          <span>{text(locale, "整理出的页面", "Prepared page")}</span>
          <h3>
            {text(
              locale,
              "第 3 章 · 如何做复习",
              "Chapter 3 · How review works",
            )}
          </h3>
          <p>
            {text(
              locale,
              "MRNote 会保留原文页码。你做笔记、提问或复习时，都能回到那一段材料。",
              "MRNote keeps the original page numbers so notes, questions, and review cards can point back to the same passage.",
            )}
          </p>
          <div className="marketing-study-preview__chunk-list">
            <span>
              {text(locale, "摘录 18 · 第 42 页", "excerpt 18 · p.42")}
            </span>
            <span>
              {text(locale, "摘录 21 · 第 48 页", "excerpt 21 · p.48")}
            </span>
          </div>
        </section>
        <aside className="marketing-study-preview__cards">
          <StudyPanelContent />
        </aside>
      </main>
    </div>
  );
}

export function MarketingWorkspacePreview({
  focus,
  surface = "hero",
}: {
  focus?: WorkspaceFocus | null;
  surface?: Surface;
}) {
  const locale = usePreviewLocale();
  const nav = [
    {
      icon: BookOpen,
      label: text(locale, "工作区", "Workspace"),
      active: true,
    },
    { icon: Search, label: text(locale, "搜索", "Search"), active: false },
    { icon: Network, label: text(locale, "图谱", "Graph"), active: false },
    { icon: Bell, label: text(locale, "Digest", "Digest"), active: false },
  ];

  return (
    <div
      className={`marketing-product-screen marketing-product-screen--workspace marketing-product-screen--${surface}`}
      data-focus={focus ?? "none"}
    >
      <aside className="marketing-workspace-preview__sidebar">
        <div className="marketing-workspace-preview__brand">
          <span>MR</span>
          <strong>MRNote</strong>
        </div>
        <nav
          className="marketing-workspace-preview__nav"
          aria-label={text(
            locale,
            "产品预览导航",
            "Product preview navigation",
          )}
        >
          {nav.map((item) => (
            <span key={item.label} className={item.active ? "is-active" : ""}>
              <item.icon size={15} />
              <span>{item.label}</span>
            </span>
          ))}
        </nav>
        <div className="marketing-workspace-preview__notebooks">
          <span>{text(locale, "Notebooks", "Notebooks")}</span>
          <strong>{text(locale, "产品方案草稿", "Product plan draft")}</strong>
          <strong>{text(locale, "用户研究材料", "User research")}</strong>
          <strong>{text(locale, "每周记录", "Weekly notes")}</strong>
        </div>
      </aside>
      <main className="marketing-workspace-preview__main">
        <header className="marketing-workspace-preview__topbar">
          <div className="marketing-workspace-preview__crumb">
            <BookOpen size={14} />
            <strong>
              {text(locale, "产品方案草稿", "Product plan draft")}
            </strong>
            <ChevronRight size={13} />
            <span>{text(locale, "今日画布", "Today's canvas")}</span>
          </div>
          <div className="marketing-workspace-preview__tools">
            <span>
              <Search size={13} />
              {text(locale, "全局搜索", "Global search")}
            </span>
            <Settings size={15} />
          </div>
        </header>
        <div className="marketing-workspace-preview__canvas">
          <MarketingProductWindow
            title={text(locale, "页面 · 新版编辑器", "Page · Editor redesign")}
            meta={text(locale, "auto-saved", "auto-saved")}
            icon={<FileText size={14} />}
            className={`marketing-workspace-window marketing-workspace-window--editor${focusClass(focus === "editor")}`}
          >
            <WorkspaceEditorContent />
          </MarketingProductWindow>
          <MarketingProductWindow
            title={text(locale, "助手", "Assistant")}
            meta={text(locale, "4 条来源", "4 sources")}
            icon={<MessageSquareText size={14} />}
            className={`marketing-workspace-window marketing-workspace-window--ai${focusClass(focus === "ai")}`}
          >
            <AiPanelContent />
          </MarketingProductWindow>
          <MarketingProductWindow
            title={text(locale, "Memory Graph", "Memory Graph")}
            meta={text(locale, "32 条线索", "32 threads")}
            icon={<Network size={14} />}
            className={`marketing-workspace-window marketing-workspace-window--graph${focusClass(focus === "graph")}`}
          >
            <div className="marketing-product-window__graph-slot">
              <GraphMiniCanvas />
            </div>
          </MarketingProductWindow>
          <MarketingProductWindow
            title={text(locale, "学习素材", "Study material")}
            meta={text(locale, "42 段摘录", "42 excerpts")}
            icon={<GraduationCap size={14} />}
            className={`marketing-workspace-window marketing-workspace-window--study${focusClass(focus === "study")}`}
          >
            <StudyPanelContent />
          </MarketingProductWindow>
          <MarketingProductWindow
            title={text(locale, "统一搜索", "Unified search")}
            meta={text(
              locale,
              "pages · memory · files",
              "pages · memory · files",
            )}
            icon={<Search size={14} />}
            className={`marketing-workspace-window marketing-workspace-window--search${focusClass(focus === "search")}`}
          >
            <SearchPanelContent />
          </MarketingProductWindow>
        </div>
      </main>
    </div>
  );
}

export function ProductStatusStrip() {
  const locale = usePreviewLocale();
  return (
    <div className="marketing-product-status-strip">
      <span>
        <Circle size={7} fill="currentColor" />
        {text(locale, "记忆同步完成", "Memory synced")}
      </span>
      <span>{text(locale, "9 条证据链", "9 evidence trails")}</span>
      <span>{text(locale, "3 个待继续窗口", "3 windows to continue")}</span>
    </div>
  );
}
