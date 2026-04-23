export type RoleKey = "researcher" | "lawyer" | "doctor" | "teacher" | "founder" | "designer";

export const ROLE_KEYS: readonly RoleKey[] = [
  "researcher", "lawyer", "doctor", "teacher", "founder", "designer",
] as const;

// Default role used when a visitor has no cookie yet. Keeps ExclusiveSection
// populated on first paint (no "empty state" UX) while the Hero badge stays
// hidden until the visitor actively picks — so the Hero "for independent
// consultants" framing stays intact. `founder` is the closest match to that
// framing among the six roles.
export const DEFAULT_ROLE: RoleKey = "founder";

// Maps to a lucide-react icon component. RoleIcon.tsx is the sole consumer —
// keep this as a string so role-content stays a pure data module.
export type RoleIconKey =
  | "graduation-cap"
  | "scale"
  | "stethoscope"
  | "book-open"
  | "rocket"
  | "palette";

interface Localized { zh: string; en: string }

/** Hero split title — the marketing H1 is reconstructed in-order from these
 *  four parts so a single string can interleave <em> (brand-primary colour
 *  accent) and <mark> (highlighter underline) without HTML in JSON. `middle`
 *  is plain prose between the two highlights; any part may be empty. */
export interface RoleHeroTitle {
  prefix: Localized;
  emphasis: Localized;
  middle: Localized;
  mark: Localized;
  suffix?: Localized;
}

/** Persona-driven hero copy. `focusWin` tells HeroCanvasStage which of the
 *  four logical windows to bring-to-front + glow. We use 4 window ids even
 *  though the stage currently only renders 3 mocks — the id is mapped to a
 *  slot in HeroCanvasStage (see `FOCUS_WIN_TO_SLOT`). */
export type FocusWin = "page" | "memory" | "ai" | "study";

export interface RoleHeroCopy {
  kicker: Localized;
  title: RoleHeroTitle;
  sub: Localized;
  primaryCta: Localized;
  secondaryCta: Localized;
  footBadges: [Localized, Localized, Localized];
  focusWin: FocusWin;
}

/** One digest item (a single row inside a `catch` or `today` block). */
export interface DigestItemMock {
  icon: "note" | "sparkles" | "cards" | "book" | "graph" | "file" | "check";
  label: Localized;
  tag: Localized;
}

export type DigestBlockMock =
  | { kind: "catch";   title: Localized; items: DigestItemMock[] }
  | { kind: "today";   title: Localized; items: DigestItemMock[] }
  | { kind: "insight"; title: Localized; body: Localized };

export interface DailyDigestMock {
  date: Localized;
  greeting: Localized;
  blocks: [DigestBlockMock, DigestBlockMock, DigestBlockMock];
}

export interface WeeklyReflectionMock {
  range: Localized;
  headline: Localized;
  stats: Array<{ k: Localized; v: string; trend?: string; trendDir?: "up" | "down" }>;
  moves: Localized[];
  ask: Localized;
  options: Localized[];
  sparkline: number[]; // 7 normalized points (0–1)
}

export interface RoleDigestMock {
  daily: DailyDigestMock;
  weekly: WeeklyReflectionMock;
}

export interface RoleContent {
  key: RoleKey;
  label: Localized;
  iconKey: RoleIconKey;
  domainNoun: Localized;
  stat: { count: number; asOf: string };
  demo: { title: Localized; description: Localized; animationKey: string };
  templatePack: { title: Localized; items: Localized[]; cta: Localized };
  offer: { title: Localized; description: Localized; cta: Localized; href: string };
  testimonial: { quote: Localized; name: string; title: Localized; avatarInitial: string };
  institutions: string[];
  /** Persona-driven hero copy. Optional: consumers fall back to static i18n
   *  when a role hasn't been upgraded yet (graceful rollout). */
  hero?: RoleHeroCopy;
  /** Homepage digest/reflection mock. Optional: DigestSection hides the
   *  per-role card when missing, keeping the tab shell intact. */
  digestMock?: RoleDigestMock;
}

export const ROLE_CONTENT: Record<RoleKey, RoleContent> = {
  researcher: {
    key: "researcher",
    label: { zh: "研究生", en: "Researcher" },
    iconKey: "graduation-cap",
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
    hero: {
      kicker: {
        zh: "给需要跨论文、跨实验串线的你",
        en: "For when papers, experiments, and ideas need to connect",
      },
      title: {
        prefix: { zh: "让论文、实验与灵感在", en: "Let papers, experiments, and ideas " },
        emphasis: { zh: "", en: "grow their own edges" },
        middle: { zh: "", en: " inside " },
        mark: { zh: "同一张记忆图谱", en: "one memory graph" },
        suffix: { zh: "里自己长出边。", en: "." },
      },
      sub: {
        zh: "PDF、实验记录、对 AI 的追问都可追溯到源页面。每一个结论都挂着 evidence，下周再读也认得出自己的思路。",
        en: "PDFs, experiment logs, and every AI follow-up trace back to the source page. Every claim carries its evidence — your reasoning still reads like yours next week.",
      },
      primaryCta: { zh: "研究者免费开始", en: "Start free as a researcher" },
      secondaryCta: { zh: "阅读 Memory V3 白皮书", en: "Read the Memory V3 paper" },
      footBadges: [
        { zh: "支持 PDF / LaTeX / Zotero", en: "PDF / LaTeX / Zotero" },
        { zh: "引用级 evidence 追溯", en: "Citation-grade evidence trace" },
        { zh: "私有部署可选", en: "Private deployment available" },
      ],
      focusWin: "memory",
    },
    digestMock: {
      daily: {
        date: { zh: "星期三 · 4 月 22 日", en: "Wednesday · Apr 22" },
        greeting: {
          zh: "早。昨日有 2 篇论文被你标注过又没回来。",
          en: "Morning. Two papers you highlighted yesterday haven't looped back.",
        },
        blocks: [
          {
            kind: "catch",
            title: { zh: "被挂起的线索", en: "Threads left hanging" },
            items: [
              {
                icon: "note",
                label: {
                  zh: "Ghosh et al. 2024 · 你在 p.6 留了一个问号：evidence 的置信度如何传递？",
                  en: "Ghosh et al. 2024 · p.6 — you left a ? on how evidence confidence propagates.",
                },
                tag: { zh: "PDF · arxiv 2403.7721", en: "PDF · arxiv 2403.7721" },
              },
              {
                icon: "graph",
                label: {
                  zh: "memory graph 里有 3 个孤立节点，没挂证据",
                  en: "3 isolated nodes in the memory graph — still no evidence attached.",
                },
                tag: { zh: "evidence missing · graph#12", en: "evidence missing · graph#12" },
              },
            ],
          },
          {
            kind: "today",
            title: { zh: "今日值得推进", en: "Worth moving forward today" },
            items: [
              {
                icon: "sparkles",
                label: {
                  zh: "跑一次 FSRS × edge.confidence 的联动实验",
                  en: "Run the FSRS × edge.confidence pilot.",
                },
                tag: { zh: "代码草稿在 page#3840", en: "draft code · page#3840" },
              },
              {
                icon: "file",
                label: {
                  zh: "把 Ghosh 那个问号转成一条 RFC",
                  en: "Turn the Ghosh question into an RFC draft.",
                },
                tag: { zh: "3 段 · page#3907", en: "3 sections · page#3907" },
              },
              {
                icon: "cards",
                label: {
                  zh: "8 张文献卡到期复习（记忆系统方向）",
                  en: "8 lit-cards due today — memory-systems track.",
                },
                tag: { zh: "14 min · FSRS", en: "14 min · FSRS" },
              },
            ],
          },
          {
            kind: "insight",
            title: { zh: "一个跨 notebook 的联想", en: "A cross-notebook connection" },
            body: {
              zh: "你上周写的「可解释长期记忆」和昨天读的 Ghosh 论文，有一个共同假设被忽略了：短期 replay buffer 的容量上限。",
              en: "Your \"explainable long-term memory\" draft and yesterday's Ghosh paper share one quiet assumption — short-term replay buffer capacity.",
            },
          },
        ],
      },
      weekly: {
        range: { zh: "4 月 14 日 – 4 月 20 日", en: "Apr 14 – Apr 20" },
        headline: {
          zh: "Memory V3 的证据链比上周牢了。",
          en: "Your Memory V3 evidence chain held tighter this week.",
        },
        stats: [
          { k: { zh: "新增节点", en: "New nodes" }, v: "42" },
          { k: { zh: "带证据的边", en: "Edges w/ evidence" }, v: "31", trend: "+11", trendDir: "up" },
          { k: { zh: "被召回次数", en: "Recall events" }, v: "94" },
          { k: { zh: "孤立节点", en: "Isolated nodes" }, v: "8", trend: "-3", trendDir: "down" },
        ],
        moves: [
          {
            zh: "三篇论文的观点已经交叉引用，不再是孤岛。",
            en: "Three papers now cross-cite each other — no more islands.",
          },
          {
            zh: "你开始在每一个结论后面写 evidence#id，像写公式。",
            en: "You started appending evidence#id to each claim, like writing a formula.",
          },
          {
            zh: "跨 notebook 的一次自发联想：FSRS × replay buffer。",
            en: "One spontaneous cross-notebook link: FSRS × replay buffer.",
          },
        ],
        ask: { zh: "下周你最想攻一块？", en: "Which block do you want to take on next?" },
        options: [
          { zh: "写 memory.confidence 的数学定义", en: "Formalize memory.confidence math" },
          { zh: "跑 FSRS × memory 联动实验", en: "Run FSRS × memory pilot" },
          { zh: "把 3 条 insight 写成博文", en: "Turn 3 insights into a post" },
          { zh: "清掉剩下的孤立节点", en: "Clear remaining isolated nodes" },
        ],
        sparkline: [0.3, 0.42, 0.38, 0.58, 0.55, 0.72, 0.82],
      },
    },
  },
  lawyer: {
    key: "lawyer",
    label: { zh: "律师", en: "Lawyer" },
    iconKey: "scale",
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
    hero: {
      kicker: { zh: "给同时处理五份合同的你", en: "For when five contracts move at once" },
      title: {
        prefix: { zh: "别再把案件时间线", en: "Stop retyping the " },
        emphasis: { zh: "一条条往表格里抄", en: "case timeline" },
        middle: { zh: "。让 ", en: " into a spreadsheet. Let " },
        mark: { zh: "notebook 替你拼起来", en: "notebook stitch it for you" },
        suffix: { zh: "。", en: "." },
      },
      sub: {
        zh: "合同、邮件、庭审纪要、客户群聊都拖进同一个案件 notebook。开庭前半小时打开，整条时间线已经自己拼好。",
        en: "Contracts, email threads, hearing notes, and client chats land in one case notebook. Open 30 min before hearing — the full timeline is already stitched.",
      },
      primaryCta: { zh: "律师免费开始", en: "Start free as a lawyer" },
      secondaryCta: { zh: "看合同摘要演示", en: "See contract summary demo" },
      footBadges: [
        { zh: "合同风险条款 10 秒拎出", en: "Contract risk clauses in 10s" },
        { zh: "庭前证据自动索引", en: "Pre-hearing evidence auto-indexed" },
        { zh: "客户 / 案件分 workspace", en: "Per-client workspaces" },
      ],
      focusWin: "ai",
    },
    digestMock: {
      daily: {
        date: { zh: "星期三 · 4 月 22 日", en: "Wednesday · Apr 22" },
        greeting: {
          zh: "早。昨天 3 份合同被你翻过又没归档。",
          en: "Morning. Three contracts you opened yesterday never landed in the file.",
        },
        blocks: [
          {
            kind: "catch",
            title: { zh: "昨天留下的尾巴", en: "Threads left hanging" },
            items: [
              {
                icon: "note",
                label: {
                  zh: "Partnership draft § 7.2 —— 还没和 Ming 对齐",
                  en: "Partnership draft § 7.2 — not aligned with Ming yet.",
                },
                tag: { zh: "page#4102 · 2 天前", en: "page#4102 · 2d ago" },
              },
              {
                icon: "sparkles",
                label: {
                  zh: "群里 @李总 昨晚的一句提醒还没转成待办",
                  en: "Reminder from @Li yesterday still not turned into a todo.",
                },
                tag: { zh: "chat#6821", en: "chat#6821" },
              },
            ],
          },
          {
            kind: "today",
            title: { zh: "今天 3 件要事", en: "3 things worth doing today" },
            items: [
              {
                icon: "file",
                label: {
                  zh: "整理开庭前备忘：把 3 条邮件要点并进案件笔记",
                  en: "Pre-hearing memo: fold 3 email threads into the case note.",
                },
                tag: { zh: "case#22 · 40 min", en: "case#22 · 40 min" },
              },
              {
                icon: "check",
                label: {
                  zh: "发定价合同给对方法务",
                  en: "Send the pricing draft to counsel.",
                },
                tag: { zh: "page#4115", en: "page#4115" },
              },
              {
                icon: "graph",
                label: {
                  zh: "review：近两周 NDA 条款的 5 条讨论聚成一个模板",
                  en: "Cluster recent NDA discussions into one reusable template.",
                },
                tag: { zh: "5 条 · 2 周", en: "5 threads · 2 weeks" },
              },
            ],
          },
          {
            kind: "insight",
            title: { zh: "我注意到的一个模式", en: "A pattern I noticed" },
            body: {
              zh: "过去两周 NDA 类条款来回改了 3 次 —— 要不要起一个风险模板，下次直接调用？",
              en: "NDA-style clauses bounced back 3 times in the past two weeks — worth turning into a reusable risk template?",
            },
          },
        ],
      },
      weekly: {
        range: { zh: "4 月 14 日 – 4 月 20 日", en: "Apr 14 – Apr 20" },
        headline: {
          zh: "这周你的案件时间线终于收齐了。",
          en: "Your case timeline finally came together this week.",
        },
        stats: [
          { k: { zh: "新归档页面", en: "Pages filed" }, v: "18" },
          { k: { zh: "带 evidence 的节点", en: "Nodes w/ evidence" }, v: "43", trend: "+12", trendDir: "up" },
          { k: { zh: "待办清零", en: "Todos cleared" }, v: "12", trend: "+4", trendDir: "up" },
          { k: { zh: "客户共享页面", en: "Client-shared pages" }, v: "5" },
        ],
        moves: [
          {
            zh: "3 次零散沟通合并成了一份开庭备忘。",
            en: "Three scattered chats collapsed into one pre-hearing memo.",
          },
          {
            zh: "每条决策后面都挂上了 evidence#id，像做判例。",
            en: "Every decision now carries an evidence#id — like a proper precedent.",
          },
          {
            zh: "M 公司公测的 22 条反馈聚成了 5 个清晰风险点。",
            en: "22 M-Co beta notes clustered into 5 clean risk themes.",
          },
        ],
        ask: { zh: "下周的主线放在哪里？", en: "Which thread should lead next week?" },
        options: [
          { zh: "统一 NDA / 保密条款模板", en: "Unify the NDA / confidentiality template" },
          { zh: "把历年判例做成 subject graph", en: "Turn 10 yrs of precedent into a subject graph" },
          { zh: "给客户做 weekly 简报", en: "Ship a weekly client brief" },
          { zh: "清掉剩下的开庭待办", en: "Close remaining pre-hearing todos" },
        ],
        sparkline: [0.25, 0.38, 0.45, 0.52, 0.48, 0.66, 0.78],
      },
    },
  },
  doctor: {
    key: "doctor",
    label: { zh: "医生", en: "Doctor" },
    iconKey: "stethoscope",
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
    hero: {
      kicker: { zh: "给夜班口述到天亮的你", en: "For the clinician dictating through the night" },
      title: {
        prefix: { zh: "让随手一段", en: "Let a bedside " },
        emphasis: { zh: "口述", en: "dictation" },
        middle: { zh: "，自动拆成 ", en: " auto-split into " },
        mark: { zh: "主诉 / 现病史 / 处置", en: "CC / HPI / Plan" },
        suffix: { zh: "。", en: "." },
      },
      sub: {
        zh: "门诊、交班、查房、文献笔记都挂在同一个病人 timeline 上。下次遇到同样的症状组合，不必从头推理。",
        en: "Consults, handoffs, rounds, and literature notes hang on the same patient timeline. Next time the symptom cluster shows up, you don't reason from scratch.",
      },
      primaryCta: { zh: "医学生免费开始", en: "Start free as a med student" },
      secondaryCta: { zh: "看交班单生成演示", en: "See handoff-note demo" },
      footBadges: [
        { zh: "主诉 / HPI / 体检 / 处置自动拆", en: "CC / HPI / exam / plan auto-split" },
        { zh: "值班交接减 20 分钟", en: "~20 min saved per handoff" },
        { zh: "医学院邮箱永久免费", en: ".edu med email free forever" },
      ],
      focusWin: "memory",
    },
    digestMock: {
      daily: {
        date: { zh: "星期三 · 4 月 22 日", en: "Wednesday · Apr 22" },
        greeting: {
          zh: "早。昨晚 2 份交班还没写完整。",
          en: "Morning. Two handoffs from last night still missing pieces.",
        },
        blocks: [
          {
            kind: "catch",
            title: { zh: "昨天留下的尾巴", en: "Unclosed from last night" },
            items: [
              {
                icon: "note",
                label: {
                  zh: "3B 床 p.2 —— 你留的 ECG 读图问号没回复",
                  en: "Bed 3B p.2 — your ECG question never got an answer.",
                },
                tag: { zh: "chart#882", en: "chart#882" },
              },
              {
                icon: "file",
                label: {
                  zh: "查房笔记 × 3 还没转进病人 timeline",
                  en: "Three round notes haven't landed in the patient timeline.",
                },
                tag: { zh: "3 份 · page#3117", en: "3 notes · page#3117" },
              },
            ],
          },
          {
            kind: "today",
            title: { zh: "今天 3 件要事", en: "Three to handle today" },
            items: [
              {
                icon: "cards",
                label: {
                  zh: "15 张文献卡到期（心内方向）",
                  en: "15 literature cards due — cardiology track.",
                },
                tag: { zh: "22 min · FSRS", en: "22 min · FSRS" },
              },
              {
                icon: "book",
                label: {
                  zh: "Dr. Wang 术后随访继续 —— 上次停在 p.4",
                  en: "Continue Dr. Wang post-op — last stopped at p.4.",
                },
                tag: { zh: "page#3409", en: "page#3409" },
              },
              {
                icon: "check",
                label: {
                  zh: "把 3 份查房纪要并成一条 timeline",
                  en: "Fold 3 round notes into one timeline entry.",
                },
                tag: { zh: "2 条新 evidence", en: "2 new evidences" },
              },
            ],
          },
          {
            kind: "insight",
            title: { zh: "一个安静的模式", en: "A quiet pattern" },
            body: {
              zh: "最近 3 次问 AI 都是 ECG 读图 —— 要不要把这一章拆成一个子 notebook，整理成自己的速查手册？",
              en: "Three of your last AI questions were ECG-reading — worth splitting the topic into its own sub-notebook?",
            },
          },
        ],
      },
      weekly: {
        range: { zh: "4 月 14 日 – 4 月 20 日", en: "Apr 14 – Apr 20" },
        headline: {
          zh: "这周你在心内的反射速度比上周快了。",
          en: "Your cardiology instincts were faster this week.",
        },
        stats: [
          { k: { zh: "新病历页面", en: "New chart pages" }, v: "31" },
          { k: { zh: "查房 → timeline", en: "Rounds → timeline" }, v: "19", trend: "+8", trendDir: "up" },
          { k: { zh: "未闭合 todos", en: "Open todos" }, v: "5", trend: "-3", trendDir: "down" },
          { k: { zh: "flashcards 通过率", en: "Flashcard pass rate" }, v: "81%", trend: "+4%", trendDir: "up" },
        ],
        moves: [
          {
            zh: "开始主动把 AI 的推理写成自己的笔记。",
            en: "Started rewriting AI reasoning into your own notes.",
          },
          {
            zh: "三次交班连续没漏项 —— 第一次。",
            en: "Three handoffs in a row with nothing missed — a first.",
          },
          {
            zh: "跨科室联想：这一例的病史让你想起上个月另一个病例。",
            en: "A cross-ward recall: this case pulled up one from last month.",
          },
        ],
        ask: { zh: "下周想主攻哪一块？", en: "Which block to lead next week?" },
        options: [
          { zh: "把 ECG 读图整理成速查手册", en: "Compile an ECG quick-ref of your own" },
          { zh: "继续心内文献精读", en: "Continue cardiology deep-read" },
          { zh: "把常见交班坑做成 checklist", en: "Turn handoff pitfalls into a checklist" },
          { zh: "清完本周 5 条未闭合 todo", en: "Close the 5 remaining todos" },
        ],
        sparkline: [0.32, 0.42, 0.4, 0.55, 0.62, 0.7, 0.76],
      },
    },
  },
  teacher: {
    key: "teacher",
    label: { zh: "老师", en: "Teacher" },
    iconKey: "book-open",
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
    hero: {
      kicker: { zh: "给同一个知识点备课三遍的你", en: "For teachers who prep the same topic three times" },
      title: {
        prefix: { zh: "让 ", en: "Let " },
        emphasis: { zh: "教案、作业、题库", en: "lesson, homework, question bank" },
        middle: { zh: "，指向 ", en: " point to " },
        mark: { zh: "同一张知识卡", en: "one concept card" },
        suffix: { zh: "。", en: "." },
      },
      sub: {
        zh: "反思、学生常错点、同类题挂在一个知识点下。三年前写过的例题，一句话就调得出。",
        en: "Reflections, common mistakes, and related questions all hang off one concept. A lesson example from three years ago? One query away.",
      },
      primaryCta: { zh: "教师免费开始", en: "Start free as a teacher" },
      secondaryCta: { zh: "看题库联动演示", en: "See lesson↔bank demo" },
      footBadges: [
        { zh: "教案 / 作业 / 题库一体化", en: "Lesson + homework + bank unified" },
        { zh: "学生错题自动聚类", en: "Auto-cluster student mistakes" },
        { zh: "学校邮箱包年 5 折", en: "School email · 50% off annual" },
      ],
      focusWin: "study",
    },
    digestMock: {
      daily: {
        date: { zh: "星期三 · 4 月 22 日", en: "Wednesday · Apr 22" },
        greeting: {
          zh: "早。三年前写过的那道例题，昨晚又被搜了一次。",
          en: "Morning. Someone pulled up an example you wrote three years ago — again.",
        },
        blocks: [
          {
            kind: "catch",
            title: { zh: "昨天留下的尾巴", en: "Unfinished from yesterday" },
            items: [
              {
                icon: "note",
                label: {
                  zh: "月考反思还没落进学情表",
                  en: "Monthly exam reflection hasn't landed in the student log.",
                },
                tag: { zh: "page#2811", en: "page#2811" },
              },
              {
                icon: "file",
                label: {
                  zh: "家长沟通草稿 × 2 还没发",
                  en: "Two parent-note drafts still unsent.",
                },
                tag: { zh: "draft · 1 天前", en: "draft · 1d ago" },
              },
            ],
          },
          {
            kind: "today",
            title: { zh: "今天 3 件要事", en: "Three to prioritize" },
            items: [
              {
                icon: "cards",
                label: {
                  zh: "14 张 flashcards 到期（同余理论）",
                  en: "14 flashcards due — congruence theory.",
                },
                tag: { zh: "15 min · FSRS", en: "15 min · FSRS" },
              },
              {
                icon: "book",
                label: {
                  zh: "高三 § 5.3 教案继续 —— 上次停在例题 3",
                  en: "Senior § 5.3 lesson continue — stopped at example 3.",
                },
                tag: { zh: "page#3110", en: "page#3110" },
              },
              {
                icon: "graph",
                label: {
                  zh: "把本周错题自动聚类送进题库",
                  en: "Fold this week's mistakes into the bank.",
                },
                tag: { zh: "12 道 · 3 类", en: "12 q · 3 themes" },
              },
            ],
          },
          {
            kind: "insight",
            title: { zh: "一个学情信号", en: "A student-log signal" },
            body: {
              zh: "最近教到二次曲线时，学生平均停留时间比上学期长 40% —— 要不要补一节 visual 版？",
              en: "On conic sections, average dwell time is 40% longer than last term — worth adding a visual-first session?",
            },
          },
        ],
      },
      weekly: {
        range: { zh: "4 月 14 日 – 4 月 20 日", en: "Apr 14 – Apr 20" },
        headline: {
          zh: "这周你的题库变成了一本自己能读的书。",
          en: "Your question bank became a book you can actually read.",
        },
        stats: [
          { k: { zh: "新教案页面", en: "New lesson pages" }, v: "9" },
          { k: { zh: "并入题库的题", en: "Items folded into bank" }, v: "47", trend: "+18", trendDir: "up" },
          { k: { zh: "学情标注", en: "Student-log entries" }, v: "28" },
          { k: { zh: "家长沟通", en: "Parent notes" }, v: "6" },
        ],
        moves: [
          {
            zh: "高三错题自动归入 3 个主题，不再手抄。",
            en: "Senior mistakes auto-sorted into 3 themes — no more retyping.",
          },
          {
            zh: "你把 5 年前写过的反思挂回了这学期的教案上。",
            en: "A 5-year-old reflection reattached itself to this term's lesson.",
          },
          {
            zh: "一次跨班级的观察：两班在同一个点都卡了。",
            en: "A cross-class observation: both cohorts stalled on the same step.",
          },
        ],
        ask: { zh: "下周主线想放在哪一块？", en: "Where to focus next week?" },
        options: [
          { zh: "把本月错题做成专题讲义", en: "Turn this month's mistakes into a handout" },
          { zh: "给二次曲线补 visual 一节", en: "Add a visual session for conics" },
          { zh: "和家长做一次学期复盘", en: "Run a term recap with parents" },
          { zh: "把旧教案的例题索引一次", en: "Index examples from older lesson plans" },
        ],
        sparkline: [0.28, 0.35, 0.45, 0.42, 0.58, 0.65, 0.72],
      },
    },
  },
  founder: {
    key: "founder",
    label: { zh: "创业者", en: "Founder" },
    iconKey: "rocket",
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
    hero: {
      kicker: { zh: "给一天同时推进六个方向的你", en: "For when you're running six directions at once" },
      title: {
        prefix: { zh: "别再一遍遍给新会议 ", en: "Stop " },
        emphasis: { zh: "重述上下文", en: "re-explaining context" },
        middle: { zh: "。", en: " to every new meeting. Let " },
        mark: { zh: "让 notebook 替你记得", en: "notebook remember for you" },
        suffix: { zh: "。", en: "." },
      },
      sub: {
        zh: "spec、用研、反馈和 AI 摘要都留在这个 project 的 notebook。新成员打开，5 分钟就能读懂这事为什么这么定。",
        en: "Specs, research, feedback, and AI summaries all live in one project notebook. A new teammate opens it — 5 minutes and they get why this was decided.",
      },
      primaryCta: { zh: "免费开始，无需信用卡", en: "Start free, no credit card" },
      secondaryCta: { zh: "看创始人工作流演示", en: "See founder workflow demo" },
      footBadges: [
        { zh: "spec / research / RFC 统一画布", en: "Spec / research / RFC unified" },
        { zh: "每日 digest 防止跟进遗漏", en: "Daily digest stops follow-up leaks" },
        { zh: "团队共享上下文", en: "Team-shared context" },
      ],
      focusWin: "ai",
    },
    digestMock: {
      daily: {
        date: { zh: "星期三 · 4 月 22 日", en: "Wednesday · Apr 22" },
        greeting: {
          zh: "早上好，船长。昨天在 3 个 project 里推进了 7 个页面。",
          en: "Morning, captain. Yesterday you pushed 7 pages across 3 projects.",
        },
        blocks: [
          {
            kind: "catch",
            title: { zh: "没收尾的承诺", en: "Promises still open" },
            items: [
              {
                icon: "note",
                label: {
                  zh: "答应 @linyi 今天给出 Memory V3 定价初稿",
                  en: "Promised @linyi a Memory V3 pricing draft today.",
                },
                tag: { zh: "昨日会议 · 11:40", en: "meeting · yesterday 11:40" },
              },
              {
                icon: "sparkles",
                label: {
                  zh: "AI 帮你起草的 RFC 还没发出去",
                  en: "The AI-drafted RFC hasn't been sent.",
                },
                tag: { zh: "draft · 4 天前", en: "draft · 4d ago" },
              },
            ],
          },
          {
            kind: "today",
            title: { zh: "今天 3 件要事", en: "Three to move today" },
            items: [
              {
                icon: "graph",
                label: {
                  zh: "review：Memory V3 公测的 22 条用户反馈",
                  en: "Review 22 beta reports — already clustered into 5.",
                },
                tag: { zh: "已聚成 5 个簇", en: "5 clusters" },
              },
              {
                icon: "cards",
                label: {
                  zh: "和研发对齐 evidence API 形状",
                  en: "Align with eng on the evidence API shape.",
                },
                tag: { zh: "page#3912", en: "page#3912" },
              },
              {
                icon: "file",
                label: {
                  zh: "发布定价初稿到 #pricing-v3",
                  en: "Ship pricing v1 to #pricing-v3.",
                },
                tag: { zh: "2 位审阅者", en: "2 reviewers" },
              },
            ],
          },
          {
            kind: "insight",
            title: { zh: "我注意到的节奏", en: "A rhythm I noticed" },
            body: {
              zh: "过去两周你每周三下午都会被打断 3 次以上 —— 要不要在日历里锁 3-5 点做深度决策？",
              en: "Wed afternoons have been interrupted 3+ times for two weeks running — worth locking 3-5 PM for deep calls?",
            },
          },
        ],
      },
      weekly: {
        range: { zh: "4 月 14 日 – 4 月 20 日", en: "Apr 14 – Apr 20" },
        headline: {
          zh: "你把 Memory V3 从模糊推到了具体。",
          en: "You pushed Memory V3 from fuzzy into concrete.",
        },
        stats: [
          { k: { zh: "页面推进", en: "Pages moved" }, v: "37" },
          { k: { zh: "会议纪要 → spec", en: "Meetings → spec" }, v: "9" },
          { k: { zh: "未跟进项", en: "Open follow-ups" }, v: "4", trend: "-6", trendDir: "down" },
          { k: { zh: "团队共享页面", en: "Team-shared pages" }, v: "18" },
        ],
        moves: [
          {
            zh: "3 次零散会议合并成了一份 Memory V3 公测 RFC。",
            en: "Three scattered meetings collapsed into one Memory V3 beta RFC.",
          },
          {
            zh: "定价讨论从 slack 回到了带 evidence 的页面。",
            en: "Pricing moved from Slack back onto evidence-backed pages.",
          },
          {
            zh: "每日 digest 让你这周少漏了 6 个跟进。",
            en: "Daily digest caught 6 follow-ups you would've missed.",
          },
        ],
        ask: { zh: "下周的主线想放在哪里？", en: "Which thread should lead next week?" },
        options: [
          { zh: "Memory V3 公测 → GA", en: "Memory V3 beta → GA" },
          { zh: "把用研闭环做到团队共享", en: "Close the research loop for the team" },
          { zh: "RFC：multiplayer notebook", en: "RFC: multiplayer notebook" },
          { zh: "做一次 org-wide context audit", en: "Run an org-wide context audit" },
        ],
        sparkline: [0.35, 0.48, 0.42, 0.68, 0.62, 0.75, 0.85],
      },
    },
  },
  designer: {
    key: "designer",
    label: { zh: "设计师", en: "Designer" },
    iconKey: "palette",
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
    hero: {
      kicker: { zh: "给情绪板散在四个工具的你", en: "For when mood boards live across four tools" },
      title: {
        prefix: { zh: "让三个月前收藏的那张 ", en: "Let that " },
        emphasis: { zh: "灵感卡", en: "inspiration card" },
        middle: { zh: "，在 ", en: " from three months ago meet you in " },
        mark: { zh: "同一个搜索框里", en: "one search box" },
        suffix: { zh: "等你。", en: "." },
      },
      sub: {
        zh: "Pinterest 截图、Figma 板、线下速写都进同一个画布；按颜色 / 情绪 / 结构，都能搜回来。",
        en: "Pinterest screenshots, Figma boards, and quick sketches land on one canvas. Search by color, mood, or structure — it all comes back.",
      },
      primaryCta: { zh: "独立设计师首月 ¥1", en: "¥1 first month · freelancer" },
      secondaryCta: { zh: "看灵感检索演示", en: "See inspiration-search demo" },
      footBadges: [
        { zh: "按颜色 / 情绪 / 结构搜", en: "Search by color / mood / structure" },
        { zh: "项目简报 / 竞品 / 评审统一", en: "Brief / scan / review unified" },
        { zh: "Figma / Notion 一键迁入", en: "1-click import from Figma / Notion" },
      ],
      focusWin: "page",
    },
    digestMock: {
      daily: {
        date: { zh: "星期三 · 4 月 22 日", en: "Wednesday · Apr 22" },
        greeting: {
          zh: "早。昨晚你又找了那张三个月前收藏的卡片 12 分钟。",
          en: "Morning. You spent 12 min last night chasing a card you saved 3 months ago.",
        },
        blocks: [
          {
            kind: "catch",
            title: { zh: "没归档的线索", en: "Threads left open" },
            items: [
              {
                icon: "note",
                label: {
                  zh: "Atlas 品牌情绪板还挂在 Figma 没迁回来",
                  en: "Atlas brand mood board still stranded in Figma.",
                },
                tag: { zh: "4 天前", en: "4d ago" },
              },
              {
                icon: "sparkles",
                label: {
                  zh: "品牌 review 会上的 4 条反馈没转成待办",
                  en: "Four review notes from the brand sync haven't become todos.",
                },
                tag: { zh: "review · chat#412", en: "review · chat#412" },
              },
            ],
          },
          {
            kind: "today",
            title: { zh: "今天 3 件要事", en: "Three to make today" },
            items: [
              {
                icon: "file",
                label: {
                  zh: "Atlas 品牌先写 brief",
                  en: "Draft the Atlas brand brief first.",
                },
                tag: { zh: "page#2207", en: "page#2207" },
              },
              {
                icon: "graph",
                label: {
                  zh: "昨天 12 张收藏聚成 3 个主题",
                  en: "Cluster last night's 12 saves into 3 themes.",
                },
                tag: { zh: "inspiration#18", en: "inspiration#18" },
              },
              {
                icon: "check",
                label: {
                  zh: "审 3 张竞品卡，给 Atlas 做参考",
                  en: "Scan 3 competitor cards for Atlas direction.",
                },
                tag: { zh: "3 张 · 10 min", en: "3 cards · 10 min" },
              },
            ],
          },
          {
            kind: "insight",
            title: { zh: "一个我注意到的品味", en: "A taste I noticed" },
            body: {
              zh: "最近收藏频率高的色系都是「暖灰 + 低饱橙」—— 要不要固定一个 palette？",
              en: "Recent saves cluster around warm-gray + low-sat orange — worth locking a palette?",
            },
          },
        ],
      },
      weekly: {
        range: { zh: "4 月 14 日 – 4 月 20 日", en: "Apr 14 – Apr 20" },
        headline: {
          zh: "这周你的灵感库第一次像一本自己的书。",
          en: "Your inspiration library read like a book of yours for the first time.",
        },
        stats: [
          { k: { zh: "新增灵感卡", en: "Inspirations filed" }, v: "28" },
          { k: { zh: "项目简报", en: "Project briefs" }, v: "4" },
          { k: { zh: "评审决定", en: "Review decisions" }, v: "11", trend: "+5", trendDir: "up" },
          { k: { zh: "跨项目复用", en: "Cross-project reuse" }, v: "7" },
        ],
        moves: [
          {
            zh: "把 Atlas 的三次评审合并成一份 one-pager。",
            en: "Three Atlas reviews merged into a single one-pager.",
          },
          {
            zh: "开始在每张灵感卡上写 3 个关键词，像打 tag。",
            en: "Started tagging each inspiration card with 3 keywords.",
          },
          {
            zh: "一个品牌主题自己长了出来：暖灰 + 低饱橙。",
            en: "A brand theme emerged on its own: warm-gray + low-sat orange.",
          },
        ],
        ask: { zh: "下周主线放在哪？", en: "Where should next week lead?" },
        options: [
          { zh: "锁一个 Atlas 核心 palette", en: "Lock an Atlas core palette" },
          { zh: "给灵感库补上情绪 tag", en: "Add mood tags to the library" },
          { zh: "把评审反馈做成模板", en: "Turn review feedback into a template" },
          { zh: "清掉 Figma 里剩下的情绪板", en: "Pull remaining Figma boards in" },
        ],
        sparkline: [0.22, 0.36, 0.48, 0.42, 0.56, 0.62, 0.74],
      },
    },
  },
};

// TODO: replace placeholder testimonials with real-person consented quotes before launch.
