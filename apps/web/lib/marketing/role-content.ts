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
  },
};

// TODO: replace placeholder testimonials with real-person consented quotes before launch.
