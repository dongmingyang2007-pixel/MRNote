# MRAI AI 笔记系统开发总说明（给 Claude / vibe coding）

> 这份文档是给 Claude/Codex 一类编程助手的直接开发说明。
> 目标是在**现有 MRAI / MRNote monorepo**上，增量实现一个 **AI-native 笔记软件 / 个人工作与认知系统**。
> 不要推翻现有架构，不要重写 Memory V3，不要另起一个新项目。请直接在现有 monorepo 内迭代实现。

---

## 0. 执行原则

### 0.1 总目标
把当前的工作台系统升级成一个以“页面/笔记”为中心的 AI 产品：

- 用户可以写文档
- 用户可以写代码
- 用户可以写 LaTeX
- 用户可以手绘 / 草图
- 用户可以上传书、资料、文件
- 用户可以在页面里直接让 AI 改写、总结、问答、查资料、头脑风暴、初步搭建
- AI 会根据用户长期写下来的内容，逐渐理解用户本人和用户的工作
- 所有这些内容都应该成为 Memory V3 的高质量证据源
- AI 最终不是“聊一次”，而是“长期服务”

### 0.2 不要做的事
- 不要删除或替换现有 Memory V3
- 不要把这个产品做成单纯聊天壳
- 不要新起独立前后端仓库
- 不要一开始追求复杂多人协作 OT/CRDT
- 不要为了新编辑器而重构整个应用壳
- 不要把用户个性化直接写进模型权重；个性化优先落在 profile / memory / playbook / evidence 层
- 不要一开始做复杂按 token 计费；先做订阅 + entitlement + usage ledger

### 0.3 实施风格
- 直接写代码，不要只给解释
- 采用增量式 PR/commit 风格
- 每完成一个大块就补测试
- 尽量复用现有：
  - Next.js Web
  - FastAPI API
  - Celery Worker
  - Postgres
  - MinIO
  - Memory V3
  - model catalog / pipeline / workspace auth
- 对不确定的局部，可以做合理工程假设，先让系统跑起来

---

## 1. 产品定义

一句话定义：

**这是一个 AI-native 的笔记与工作系统。用户在这里写文档、代码、公式、草图、读书笔记、项目想法；系统一边帮助用户完成当前工作，一边把这些内容转化成长期记忆，让 AI 越来越了解用户本人和用户的工作方式。**

### 1.0 产品终极定位

不是 Notion + ChatGPT 的简单拼接。  
更像是：**NotebookLM + Notion + Personal Memory Graph + Agentic Workspace**

核心不是”能写”，而是：  
**用户每一次写作、提问、阅读、画图、整理资料，都在反过来塑造一个越来越懂用户的长期知识人格。**

MRAI 当前最有价值的资产：
- Memory V3 内核已经很强（triage / promote / supersede / concept-parent / evidence 全链路）
- Notebook 数据层已经存在
- Notebook AI 接口已经存在
- 文件索引链已经存在

**只差把它们真正打通成一个产品闭环。**

### 1.1 核心价值
产品必须同时覆盖两条线，但底层只有一个内核：

1. **越来越了解你**
   - 理解用户目标、偏好、习惯、学习方式、表达风格、长期关注点
   - 帮助用户反思、整理、提醒、成长

2. **越来越了解你的工作**
   - 理解项目、任务、上下文、方法、复用套路
   - 帮助用户推进工作、沉淀 playbook、生成下一步

### 1.2 产品主循环
所有功能都要围绕这条主循环：

**记录 → 理解 → 记忆 → 服务 → 复盘**

### 1.3 第一性原则
- 页面是内容中心
- AI 是页面内共创者，不是外置聊天框
- Memory 是后台长期大脑
- Evidence 是一切记忆的来源
- Playbook 是”这个用户通常怎么做事”的沉淀
- Outcome 是”什么方法真的有效”的反馈
- Health 是”哪些记忆 stale/冲突/需要重确认”的治理机制

### 1.4 实施优先级（P0 → P3）

**P0：真正接入 Memory V3（从”AI 能陪写”到”AI 会持续理解你”的分水岭）**

当前 `note_memory_bridge.py` 是弱版本的提取链路；而 `worker_tasks.py` 里的 chat memory extraction 是强版本。正确做法不是在 notebook 里再抄一套，而是：

1. 把 chat 的 memory extraction / triage / promote / supersede / concept-parent / evidence 逻辑**抽成一个通用 service**（`UnifiedMemoryPipeline`），支持不同 `source_type`：
   - `chat_message`
   - `notebook_page`
   - `uploaded_document`
   - `whiteboard`
   - `book_chapter`
2. Page 的 memory/confirm 不应该只改 `decision` 字段，而应该真正调用这个 shared pipeline，把确认项写成正式 Memory 节点和完整证据链
3. 这一步做好，系统才开始真正像”越来越了解用户”的产品

**P1：Notebook AI Ask 接入 Memory + 文件检索（从”页面问答”到”长期上下文问答”）**

当前 ask 主要用页面全文和选区。下一步在进入模型前增加 **retrieval orchestration**：
1. Page current text（当前页全文）
2. Selected context（选区内容）
3. `memory/search` 命中的 subject / subgraph
4. `memory/search/explain` 的推理结果
5. Document chunks（来自上传的书籍、PDF、课程材料）
6. Page history / related pages

这样用户问 AI 时，它不是只”基于当前页回答”，而是”基于用户长期上下文 + 当前资料 + 当前页面”回答。

**P2：书籍学习做成一级工作流（从”PDF 聊天”到”知识内化系统”）**

书不是孤立文件，而是进入完整知识链：
```
Upload → Parse/Chunk → Index
  ↓
Auto-create notebook pages: 书籍概览 / 章节页 / 读书笔记页
  ↓
AI 支持：章节总结 / 段落解释 / 提问答疑 / 测验 / flashcards
  ↓
提取知识点到 Memory（包括”用户对这本书的理解和困惑”）
  ↓
Document Chunk → Page Notes → Memory Evidence → Subject Graph → Study Plan
```

这比单纯做 PDF 聊天高级很多——“书”会进入用户的长期知识图谱。

**P3：白板/手绘层（把草图也纳入知识系统）**

作为独立 block type 实现，不混在富文本里硬塞。手绘 block 存 strokes JSON，AI 在此基础上：
1. 总结白板内容（文字化）
2. 从白板内容中提炼 memory candidates

这样”草图”也能被系统学习，而不是只是一张死图。

---

## 2. 和现有 MRAI 的关系

当前代码库已经有很强的 Memory V3 能力，新的笔记系统必须把它作为**长期记忆与可解释学习内核**来用，而不是重新造一套 memory。

### 2.1 现有能力要直接复用
直接复用现有概念和 API 契约：

- search
- explain
- subgraph
- outcomes
- learning-runs
- health
- playbooks / playbook feedback
- message ↔ memory learning linkage

### 2.2 新系统定位
新的 notebook 系统不是 Memory V3 的替代品，而是：

- 更自然的内容输入端
- 更高质量的 evidence 来源
- 更强的 AI 交互前台
- 更可卖的产品壳

### 2.3 关键设计原则
Notebook/Page/Block 是内容层。  
Memory/Evidence/Outcome/Playbook/Health 是学习层。  
不要把两层混在一起，但要让它们强连接。

### 2.4 统一记忆管线（UnifiedMemoryPipeline）
Chat 和 Notebook 不应该各自维护一套 memory extraction 逻辑。必须将 `worker_tasks.py` 中的强版本 chat memory extraction 抽成通用 service，让所有来源（chat / page / document / whiteboard / book chapter）共享同一条 extract → triage → promote → supersede → evidence 管线。详见第 9.0 节。

---

## 3. 用户场景

## 3.1 场景 A：AI 笔记 / 写作
用户在页面中写文档、会议纪要、PRD、日报、博客草稿。  
AI 可以：

- 改写
- 续写
- 总结
- 拆结构
- 从历史笔记中找相似内容
- 根据用户表达习惯生成文本
- 自动抽取任务 / 观点 / 偏好 / 目标 / 关系

## 3.2 场景 B：AI Coding 页面
用户在页面里写方案、伪代码、代码片段、调试记录。  
AI 可以：

- 解释代码
- 补齐实现
- 生成脚手架
- 对比几种技术方案
- 根据项目上下文生成 next step
- 把问题-解法-结果写回 playbook / outcome

## 3.3 场景 C：AI 学习 / 读书笔记
用户上传一本书、论文、课程资料、PDF。  
AI 可以：

- 切分和索引材料
- 给出章节概览
- 生成学习路径
- 边读边问答
- 自动关联用户自己的读书笔记
- 生成抽认卡 / 测验 / 复习计划
- 抽取长期兴趣、知识短板、学习偏好

## 3.4 场景 D：AI 想法孵化 / 头脑风暴
用户输入一个模糊想法。  
AI 可以：

- 帮用户结构化
- 输出几个方向
- 给出风险、缺口、问题清单
- 生成第一页方案 / 功能树 / MVP / 技术草图
- 如有需要，生成代码块和初步项目骨架

## 3.5 场景 E：长期主动服务
系统每天/每周主动为用户提供服务：

- 今日摘要
- 今日可推进的 next action
- 本周重点
- 卡点与复盘
- 学习回顾
- 关系提醒 / 目标偏航提醒
- 需要 reconfirm 的旧记忆提醒

---

## 4. 产品边界

## 4.1 本期必须做
- Notebook / Page / Block 系统
- 页内 AI
- 项目级 AI
- 长期 Memory 接入
- 文本 / 代码 / LaTeX / 草图 / 文件块
- 上传资料并做学习
- AI 生成内容 + 自动记忆抽取
- 基础搜索
- 基础付费系统
- 后台学习任务

## 4.2 本期不强求
- 多人实时协同
- 高级权限树
- 外部分享页模板市场
- 原生移动 App
- 浏览器插件
- 复杂自动执行 agent
- 企业级审计台

---

## 5. 信息架构

## 5.1 顶层对象
新增以下核心对象：

- Workspace
- Project
- Notebook
- NotebookPage
- NotebookBlock
- NotebookPageVersion
- NotebookAttachment
- NotebookSelectionMemoryLink
- StudyAsset
- StudyChunk
- StudyDeck
- StudyCard
- AIActionLog
- UsageEvent
- Subscription / Entitlement（如果仓库还没有）

### 5.1.1 Notebook
语义：一个笔记本 / 一个知识空间 / 一个项目册

字段建议：
- id
- workspace_id
- project_id（可空；允许 personal notebook）
- title
- slug
- description
- icon
- cover_image_url
- notebook_type: `personal | work | study | scratch`
- visibility: `private | workspace`
- created_by
- created_at
- updated_at
- archived_at

### 5.1.2 NotebookPage
语义：一页内容，类似文档页/卡片页/白板页

字段建议：
- id
- notebook_id
- parent_page_id（支持树状层级）
- title
- slug
- page_type: `document | canvas | mixed | study`
- summary_text
- ai_keywords_json
- ai_status_json
- sort_order
- is_pinned
- is_archived
- created_by
- created_at
- updated_at
- last_edited_at

### 5.1.3 NotebookBlock
语义：页面内容块

字段建议：
- id
- page_id
- block_type
- sort_order
- content_json
- plain_text
- metadata_json
- created_by
- created_at
- updated_at

block_type 先支持：
- heading
- paragraph
- bullet_list
- numbered_list
- checklist
- quote
- code（Monaco/CodeMirror，带语法高亮和语言选择）
- latex（KaTeX 渲染，支持 display/inline 模式）
- whiteboard（独立画布 block，存 strokes JSON，Excalidraw 嵌入；AI 可总结白板内容并提取 memory candidates）
- image
- file（文件嵌入/预览）
- ai_output（AI 生成内容，带 source 引用）
- callout
- divider
- reference（引用另一个页面/记忆/文档 chunk）
- task（任务项，可标记完成状态，可触发 outcome 记录）
- flashcard（学习卡片，可嵌入页面内）

### 5.1.4 NotebookPageVersion
语义：页面快照，用于恢复、对比、异步学习

字段建议：
- id
- page_id
- version_no
- snapshot_json
- snapshot_text
- created_by
- created_at
- source: `autosave | manual | ai_action`

### 5.1.5 NotebookAttachment
语义：页面关联文件；尽量复用现有 data item / MinIO 体系

字段建议：
- id
- page_id
- data_item_id
- attachment_type: `pdf | image | audio | video | other`
- title
- created_at

### 5.1.6 StudyAsset
语义：用户用于学习的书籍/资料/文章

字段建议：
- id
- notebook_id
- page_id（可空）
- data_item_id
- asset_type: `book | pdf | article | slides | notes_bundle`
- title
- author
- language
- ingest_status
- chunk_count
- metadata_json
- created_by
- created_at
- updated_at

### 5.1.7 StudyChunk
语义：被切分后的学习内容

字段建议：
- id
- study_asset_id
- ord
- raw_text
- summary
- keywords_json
- embedding_ref / vector strategy（可根据现有 embedding 方案复用）
- metadata_json

### 5.1.8 AIActionLog
语义：记录 AI 在页面上的一次操作，便于追踪与恢复

字段建议：
- id
- workspace_id
- notebook_id
- page_id
- block_id（可空）
- action_type
- scope: `selection | page | notebook | project | user_memory | study_asset`
- input_json
- output_json
- model_id
- status
- duration_ms
- usage_json
- created_by
- created_at

---

## 6. 前端产品结构

## 6.1 新路由
在现有 `/app` 体系下新增：

- `/app/notebooks` — 笔记本列表页
- `/app/notebooks/[notebookId]` — 笔记本工作区（自由窗口画布）
- `/app/notebooks/[notebookId]/settings` — 笔记本设置

注意：页面不再有独立路由。页面、文件、AI 对话等内容均以浮动窗口形式在笔记本工作区 (`/app/notebooks/[notebookId]`) 内打开，通过 WindowManager 管理。URL 可使用 query param 记录当前打开的窗口状态（如 `?windows=page_abc,file_xyz`）以支持刷新恢复。

后续可扩展：
- `/app/notebooks/[notebookId]/daily`
- `/app/notebooks/[notebookId]/insights`

## 6.2 首页
新增 Notebook 首页，但保留现有 dashboard/workspace 结构。

首页模块建议：
- 最近页面
- 继续写作
- 最近学习材料
- AI 今日摘要
- 我最近的工作主题
- 我最近的长期关注点
- 推荐继续推进的 3 个页面

## 6.3 笔记本工作区布局：自由窗口化画布

笔记本工作区采用**纯窗口化设计**，不使用固定栏。所有内容（页面、文件、AI 对话、记忆面板等）均以浮动窗口形式呈现在自由画布上。

### 整体结构

```
┌──────────────────────────────────────────────────────┐
│ NotebookWorkspace                                     │
│ ┌────────┐                                            │
│ │ 侧栏    │  ┌─ WindowManager (canvas) ─────────────┐ │
│ │ 56px    │  │                                       │ │
│ │         │  │  ┌─Window────────┐ ┌─Window────────┐  │ │
│ │ 页面树  │  │  │ 读书笔记.md   │ │ chapter1.pdf  │  │ │
│ │ 对话    │  │  │               │ │               │  │ │
│ │ 记忆    │  │  │ [NoteEditor]  │ │ [FileViewer]  │  │ │
│ │ 学习    │  │  │               │ │               │  │ │
│ │         │  │  └───────────────┘ └───────────────┘  │ │
│ │─────── │  │        ┌─Window────────┐               │ │
│ │ 最小化  │  │        │ AI 对话        │               │ │
│ │ 窗口列表│  │        │ [ChatWindow]  │               │ │
│ │         │  │        └───────────────┘               │ │
│ └────────┘  └────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

### 侧栏（56px 图标栏 + 可展开 240px 面板）

上半部分 — 笔记本导航：
- 返回（回到笔记本列表）
- 页面树（展开页面列表面板）
- AI 对话（展开对话列表面板）
- 记忆（展开记忆面板）
- 学习资料（展开学习材料面板）
- 设置

下半部分 — 最小化窗口托盘：
- 被最小化的窗口以图标+标题缩略形式列在侧栏底部
- 点击可恢复窗口到画布上
- 类似 VS Code 的面板列表风格

### 窗口管理器 (WindowManager)

管理画布上所有浮动窗口的状态：

| 属性 | 说明 |
|------|------|
| 位置 (x, y) | 窗口在画布上的坐标 |
| 尺寸 (width, height) | 窗口宽高，支持拖拽调整 |
| z-index | 窗口层级，点击窗口自动置顶 |
| 状态 | normal / minimized / maximized |

### 窗口 (Window)

每个窗口包含：
- **标题栏**：窗口标题 + 最小化/最大化/关闭按钮
- **拖拽**：通过标题栏拖拽移动
- **缩放**：四边和四角缩放手柄
- **边界约束**：窗口不可完全拖出可视区域，至少保留标题栏部分可见，确保用户始终能把窗口拉回来

### 窗口内容类型

| 窗口类型 | 内容 | 打开方式 |
|----------|------|----------|
| `note` | TipTap 混合 Block 编辑器 | 从页面树点击页面 |
| `code` | 纯代码编辑器（Monaco/CodeMirror） | 创建代码类型页面 |
| `canvas` | 手绘画布（Excalidraw） | 创建画布类型页面 |
| `file` | 文件查看器（PDF/图片/文本等） | 从学习资料点击文件 |
| `chat` | AI 对话界面 | 从侧栏打开对话 |
| `memory` | 记忆浏览/管理面板 | 从侧栏打开记忆 |
| `ai_panel` | 页面级 AI 面板（摘要/相关/Trace） | 从笔记窗口内触发 |
| `study` | 学习卡片/复习/测验 | 从学习资料打开 |

### 窗口交互规则

- **自由拖拽**：窗口可在画布上自由拖动，不做自动吸附/snap
- **重叠**：窗口可互相重叠，点击任意窗口将其提升到最上层
- **最大化**：窗口填满整个画布区域（不覆盖侧栏）
- **最小化**：窗口缩入侧栏底部的最小化托盘
- **关闭**：关闭窗口（不删除内容，下次可从侧栏重新打开）
- **多开**：同一个页面/文件可以在多个窗口中打开（但应标识）

### 典型使用场景

1. **读书笔记**：左边打开 PDF 文件窗口，右边打开笔记页窗口，边读边记
2. **AI 辅助写作**：一个笔记窗口 + 一个 AI 对话窗口并排
3. **代码参考**：一个代码窗口 + 一个文档窗口 + 一个 AI 窗口叠放
4. **对比学习**：两个不同笔记页窗口并排对比

---

## 7. 编辑器设计

## 7.1 技术建议
优先使用成熟组合，避免自己造富文本内核：

- 富文本/块编辑器：**Tiptap** 或兼容 block 的方案
- 代码块：**Monaco Editor**
- LaTeX 渲染：**KaTeX**
- 手绘：**Excalidraw**（先嵌入，后续再看 tldraw）
- Markdown 导入导出：必须支持
- 页面快照：序列化为 JSON + plain text

原则：
- 不要求第一版是最优雅的 block editor
- 先让“写 + AI + 记忆”闭环成立
- 编辑器的内部数据结构必须稳定、可快照、可做异步学习

## 7.2 块级能力
每种 block 都需要有：

- 渲染
- 编辑
- 拖拽排序
- 删除
- AI 操作入口
- 提取纯文本的 fallback
- 可快照序列化

## 7.3 选区 AI
当用户在页面里选中一段文本、代码或公式时，支持：

- 改写
- 总结
- 展开
- 压缩
- 翻译
- 修正表达
- 解释代码
- 解释公式
- 提炼观点
- 变成清单
- 生成下一步

## 7.4 页面级 AI
在页面级支持：
- 总结本页
- 输出大纲
- 发现未完成项
- 给本页打标签
- 抽取记忆候选
- 找相关历史页面
- 基于本页继续头脑风暴
- 基于本页生成 PRD / 方案 / 代码草稿

---

## 8. AI 作用域设计（P1 优先级）

AI 交互时必须允许用户选择作用域。

### 8.1 作用域枚举
- `selection`
- `page`
- `notebook`
- `project`
- `user_memory`
- `study_asset`
- `web`

### 8.2 默认规则
- 选中内容时：默认 `selection + page`
- 在 AI 面板窗口提问：默认 `page + notebook`
- 明显工作问题：允许 `project + memory`
- 明显个人成长/偏好问题：允许 `user_memory`
- 学习材料问答：允许 `study_asset + page notes`
- 外部资料问题：用户显式开启 `web`

### 8.3 Retrieval Orchestration（检索编排层）

这是从"页面问答"进化到"长期上下文问答"的关键。在 AI 请求进入模型前，自动组装多层上下文：

```
用户提问
  ↓
Retrieval Orchestration
  ├── 1. Page current text（当前页全文）
  ├── 2. Selected context（选区内容，如有）
  ├── 3. memory/search 命中 → 相关 subject / subgraph
  ├── 4. memory/search/explain 推理结果
  ├── 5. Document chunks（上传的书籍/PDF/课程材料）
  └── 6. Page history / related pages
  ↓
Context Assembly（按 token budget 裁剪和排序）
  ↓
Model Call
```

原则：
- 不是每次都全量检索所有源——根据问题意图决定检索哪些层
- 使用 token budget 控制总上下文长度
- 检索结果要带 source 标记，以便在回答中展示引用

### 8.4 可解释性要求
所有使用了长期 memory 或学习资料的回答，必须尽量在 UI 中展示：
- 参考页面
- 参考记忆
- 参考证据
- 参考文档 chunk
- 检索来源标记（来自 memory / document / page history）
- 为什么选中它们

---

## 9. Memory 接入设计（最关键——P0 优先级）

## 9.0 核心架构决策：统一记忆管线

**不要在 notebook 里重新实现一套弱版 memory extraction。**

当前状况：
- `worker_tasks.py` 里的 chat memory extraction 是**强版本**（triage / promote / supersede / concept-parent / evidence 全链路）
- `note_memory_bridge.py` 是**弱版本**（只做候选提取，不走完整链路）

正确做法：把 chat 的完整 memory pipeline 抽成通用 service。

### 9.0.1 UnifiedMemoryPipeline

```python
class UnifiedMemoryPipeline:
    “””统一的记忆提取/写入管线，支持多种来源。”””
    
    def extract_and_promote(
        self,
        content: str,
        source_type: SourceType,  # chat_message | notebook_page | uploaded_document | whiteboard | book_chapter
        source_ref: str,          # 来源 ID（message_id / page_id / chunk_id 等）
        project_id: str,
        workspace_id: str,
        user_id: str,
        context: dict | None = None,  # 额外上下文（页面标题、笔记本类型等）
    ) -> MemoryExtractionResult:
        “””
        完整链路：
        1. 抽取 memory candidates
        2. Triage（分类、去重、合并）
        3. 与已有 subject / concept / playbook 做链接
        4. Promote 为正式 Memory 节点（或标记为 pending_confirmation）
        5. 写入 evidence 链（source_type + source_ref）
        6. Supersede 旧版本记忆
        7. 更新 health 信号
        “””
```

### 9.0.2 source_type 枚举

| source_type | 来源 | 典型内容 |
|-------------|------|----------|
| `chat_message` | 聊天消息 | 用户和 AI 的对话 |
| `notebook_page` | 笔记页面 | 用户写的文档/代码/笔记 |
| `uploaded_document` | 上传文件 | PDF/docx 解析后的文本 |
| `whiteboard` | 手绘白板 | 白板内容的文字化描述 |
| `book_chapter` | 书籍章节 | StudyChunk 的内容 |

### 9.0.3 Confirm/Reject 必须走完整链路

Page 的 `memory/confirm` 不应该只改 `decision` 字段。当用户确认一条候选记忆时，必须：
1. 调用 `UnifiedMemoryPipeline.promote()`
2. 创建正式 Memory 节点
3. 写入完整 evidence 链（指向具体 page + version + block）
4. 执行 concept-parent 链接
5. 执行 supersede 检查（是否取代旧记忆）
6. 更新相关 subject 的 health 状态

当用户拒绝时：
1. 标记为 rejected
2. 记录拒绝原因（如有）
3. 降低同类候选的未来 confidence

## 9.1 总原则
Notebook 不是 memory 本身，而是 memory 的高质量证据源。

### 9.1.1 直接来源
Notebook 内容可转化为这些 memory 证据：
- 用户写的正文
- 用户手写草图的文字化描述（AI 总结白板内容）
- 用户的代码块说明
- 用户对书的批注
- 用户给 AI 的指令
- AI 输出被用户保留/接受的结果
- 用户的页面标题、标签、页面树位置
- 用户显式确认的记忆条目

### 9.1.2 抽取的 memory 类型
抽取时优先识别：
- fact
- preference
- goal
- project context
- concept
- relationship
- playbook/procedure
- learning insight
- recurring problem
- success/failure outcome signal

## 9.2 抽取策略
不要在每次击键时抽取。采用分层策略：

### 9.2.1 同步轻量
页面保存/短暂停顿时：
- 生成 plain_text
- 更新 page summary
- 更新 page keywords
- 建立本页检索索引

### 9.2.2 异步重处理（通过 UnifiedMemoryPipeline）
Celery worker 定时或触发时：
- 切分页面版本
- 调用 `UnifiedMemoryPipeline.extract_and_promote(source_type=”notebook_page”)`
- 完整执行：抽取 → triage → promote → evidence → supersede → health
- 与已有 subject / concept / playbook 做链接
- 生成/刷新学习 run
- 触发 nightly consolidation

## 9.3 记忆写入规则
默认不要把任何一句笔记都直接升格为”永久真相”。

为每条候选记忆维护：
- evidence（完整证据链，指向 source_type + source_ref）
- confidence
- source page/version
- visibility
- scope
- freshness
- reconfirm_after
- requires_confirmation
- dedupe/supersede relation

## 9.4 用户确认机制
增加”记忆候选”确认 UI：

- AI 认为你偏好简洁 bullet 风格 → 用户可确认/拒绝
- AI 认为你正在推进某个长期项目 → 用户可确认/拒绝
- AI 认为你经常先写大纲后细化 → 用户可确认/拒绝

确认/拒绝必须走 UnifiedMemoryPipeline 完整链路（见 9.0.3），不是只改一个字段。

## 9.5 页面与 Memory 双向链接
在 AI 面板窗口中提供：
- 本页生成了哪些 memories
- 这些 memories 的证据在哪里
- 哪些 AI 答案引用了本页
- 哪些 playbooks 来源于本页

同时在 memory detail 中展示来源页面链接。

---

## 10. 学习系统（P2 优先级——一级工作流）

## 10.0 设计原则
书籍学习不是”PDF 聊天”。书不是孤立文件，而是进入用户的完整知识链：

```
Upload（PDF/docx/扫描页/任何文件）
  ↓
Parse → Chunk → Index
  ↓
Auto-create notebook pages:
  ├── 书籍概览页
  ├── 章节页（每章一个 page）
  └── 读书笔记页（用户自己的笔记）
  ↓
AI 支持（在窗口中并排操作）:
  ├── 章节总结
  ├── 段落解释
  ├── 提问答疑
  ├── 测验 / flashcards
  └── 提取知识点到 Memory
  ↓
知识内化链路:
  Document Chunk → Page Notes → Memory Evidence → Subject Graph → Study Plan
```

关键区别：不只是提取书中的知识——**”用户对这本书的理解和困惑”也要记下来**，成为 memory evidence 的一部分。

## 10.1 学习模式目标
用户上传一本书或资料后，AI 不只是回答问题，而是帮助用户形成自己的学习过程。

## 10.2 核心能力
- 上传任何文件类型（PDF / docx / 扫描页 / 图片 / 代码文件 / slides）
- 自动解析文本（复用现有 data item / MinIO 体系）
- 切分 chunk 并建立索引
- 建立 asset → chunk → note/page 关联
- 自动创建笔记本页面（概览 / 章节 / 笔记）
- 生成章节大纲和关键概念图
- 页面内问答（通过 Retrieval Orchestration 层，结合 chunk + memory + 笔记）
- 自动出复习题 / 抽认卡（flashcard block type）
- 将用户笔记与原文相关 chunk 双向关联
- 追踪学习进度
- 通过 UnifiedMemoryPipeline 将书中知识点和用户的理解/困惑写入长期记忆

## 10.3 新对象
- StudyAsset
- StudyChunk
- StudyDeck
- StudyCard
- StudySession（可选）

## 10.4 学习卡片
AI 可根据用户笔记自动生成：
- 概念问答卡
- 定义回忆卡
- 应用题
- 错题重练卡

学习卡片同时作为 `flashcard` block type 可嵌入笔记页面中。

## 10.5 学习服务闭环
- 用户上传书
- 系统自动解析并生成知识地图 + 笔记本页面
- 用户在一个窗口看书，另一个窗口写笔记（窗口化工作区的典型场景）
- AI 抽取用户的理解盲点
- 生成复习计划
- 通过 Memory Pipeline 将学习成果写入长期知识图谱
- 每周总结”你真正学会了什么”

---

## 11. Idea-to-Build（想法到初步搭建）

## 11.1 产品目标
当用户在页面里描述一个想法时，AI 要能帮忙把“模糊想法”变成“可执行草案”。

## 11.2 支持输出
- 一页方案
- 需求树
- MVP 范围
- 风险清单
- 数据模型草稿
- API 草稿
- 前端页面树
- 技术栈建议
- 页面中的代码块 / 文件草案

## 11.3 生成形式
生成结果不要只丢进聊天消息。优先生成：
- 新页面
- 当前页追加 section
- 一组结构化 block
- 代码块
- checklists / tasks

---

## 12. 搜索系统

## 12.1 用户可见搜索
搜索范围：
- 当前 notebook 页面
- 当前 project 页面
- study assets
- memory
- playbooks
- recent AI actions

## 12.2 搜索类型
- 关键词搜索
- 全文搜索
- 语义搜索
- “问一句”搜索（交给 AI）

## 12.3 搜索结果呈现
结果要分组展示：
- Pages
- Blocks
- Files
- Study assets
- Memory
- Playbooks

---

## 13. 后端 API 设计

> API 前缀沿用 `/api/v1`

## 13.1 Notebook 基础 API
- `GET /api/v1/notebooks`
- `POST /api/v1/notebooks`
- `GET /api/v1/notebooks/{id}`
- `PATCH /api/v1/notebooks/{id}`
- `DELETE /api/v1/notebooks/{id}`

## 13.2 Page API
- `GET /api/v1/notebooks/{notebook_id}/pages`
- `POST /api/v1/notebooks/{notebook_id}/pages`
- `GET /api/v1/pages/{page_id}`
- `PATCH /api/v1/pages/{page_id}`
- `DELETE /api/v1/pages/{page_id}`
- `POST /api/v1/pages/{page_id}/duplicate`
- `POST /api/v1/pages/{page_id}/move`
- `POST /api/v1/pages/{page_id}/snapshot`
- `GET /api/v1/pages/{page_id}/versions`

## 13.3 Block API
- `POST /api/v1/pages/{page_id}/blocks`
- `PATCH /api/v1/blocks/{block_id}`
- `DELETE /api/v1/blocks/{block_id}`
- `POST /api/v1/pages/{page_id}/reorder-blocks`

## 13.4 Attachment / Study Asset API
- `POST /api/v1/pages/{page_id}/attachments`
- `DELETE /api/v1/attachments/{id}`
- `POST /api/v1/notebooks/{notebook_id}/study-assets`
- `GET /api/v1/notebooks/{notebook_id}/study-assets`
- `GET /api/v1/study-assets/{id}`
- `POST /api/v1/study-assets/{id}/ingest`
- `GET /api/v1/study-assets/{id}/chunks`
- `POST /api/v1/study-assets/{id}/generate-deck`

## 13.5 Notebook AI API
- `POST /api/v1/ai/notebook/selection-action`
- `POST /api/v1/ai/notebook/page-action`
- `POST /api/v1/ai/notebook/brainstorm`
- `POST /api/v1/ai/notebook/ask`
- `POST /api/v1/ai/notebook/generate-page`
- `POST /api/v1/ai/study/ask`
- `POST /api/v1/ai/study/quiz`
- `POST /api/v1/ai/study/flashcards`

## 13.6 Search API
- `GET /api/v1/notebooks/{id}/search`
- `GET /api/v1/pages/{page_id}/related`
- `GET /api/v1/search/global?q=...`

## 13.7 Memory 连接 API
在不破坏现有 memory 契约的基础上补充：

- `POST /api/v1/pages/{page_id}/memory/extract` — 触发 UnifiedMemoryPipeline（source_type=notebook_page）
- `GET /api/v1/pages/{page_id}/memory/links` — 本页关联的 memory 节点和证据链
- `POST /api/v1/pages/{page_id}/memory/confirm` — 走完整 promote 链路（不只改 decision）
- `POST /api/v1/pages/{page_id}/memory/reject` — 走完整 reject 链路（降低同类 confidence）
- `GET /api/v1/pages/{page_id}/memory/trace` — 完整的 memory trace（evidence → memory → subject → playbook）

说明：
- 真正的 memory search/explain/subgraph/outcomes 等仍优先走现有 `/api/v1/memory/*`
- Notebook 只是补页面视角接口
- confirm/reject 必须通过 UnifiedMemoryPipeline 执行完整链路，不可只改数据库字段

---

## 14. 后台任务 / Worker 设计

新增 Celery 任务：

### 14.1 页面处理
- `notebook_page_plaintext_task`
- `notebook_page_snapshot_task`
- `notebook_page_summary_task`

### 14.2 记忆处理（通过 UnifiedMemoryPipeline）
- `unified_memory_extract_task(source_type, source_ref, content, ...)` — 统一入口，替代分散的弱版提取
- `notebook_page_memory_extract_task` — 调用 unified pipeline with source_type=notebook_page
- `notebook_page_memory_link_task` — 建立 page ↔ memory 双向链接
- `notebook_page_relevance_refresh_task` — 刷新相关性
- `whiteboard_memory_extract_task` — 调用 unified pipeline with source_type=whiteboard（先文字化白板内容，再提取）
- `document_memory_extract_task` — 调用 unified pipeline with source_type=uploaded_document

### 14.3 学习处理
- `study_asset_ingest_task` — 解析上传文件（不限 PDF）
- `study_asset_chunk_task` — 切分和索引
- `study_asset_auto_pages_task` — 自动创建概览/章节/笔记页面
- `study_asset_deck_generate_task` — 生成 flashcards
- `study_asset_memory_extract_task` — 调用 unified pipeline with source_type=book_chapter
- `study_asset_review_recommendation_task` — 复习推荐

### 14.4 主动服务
- `daily_notebook_digest_task`
- `weekly_notebook_reflection_task`

### 14.5 计费/用量
- `usage_rollup_task`
- `subscription_sync_repair_task`

---

## 15. 计费与收费（Stripe）

## 15.1 原则
- 先做订阅，不做复杂按量扣费
- 先做用户可理解的 plan
- 同时保留 usage ledger 以便未来升级计费方式

## 15.2 推荐套餐
### Free
- 1 个 notebook
- 50 页
- 每月有限 AI 次数
- 1 个 study asset
- 无主动服务
- 无高级 memory insights

### Pro
- 无限 notebook / 更高页面上限
- 更多 AI 调用
- study mode
- page/page selection AI
- notebook/project memory
- daily digest
- basic voice（可选）

### Power
- 更高 AI 配额
- 更大文件上传
- 更强模型
- book decks / advanced study
- brainstorm to build
- 工作台级 playbooks / outcomes

### Team
- shared notebook / workspace
- seat-based
- 团队 memory 视图
- 管理员计费

## 15.3 数据表
新增或补足：
- `plans`
- `subscriptions`
- `subscription_items`
- `entitlements`
- `usage_events`
- `billing_events`
- `customer_accounts`

## 15.4 API
- `POST /api/v1/billing/checkout`
- `POST /api/v1/billing/portal`
- `POST /api/v1/billing/webhook`
- `GET /api/v1/billing/me`

## 15.5 Entitlement 示例
- `notebooks.max`
- `pages.max`
- `study_assets.max`
- `ai.actions.monthly`
- `book_upload.enabled`
- `daily_digest.enabled`
- `voice.enabled`
- `advanced_memory_insights.enabled`

## 15.6 Webhook
至少处理：
- `checkout.session.completed`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.paid`
- `invoice.payment_failed`

## 15.7 用量账本
每次 AI 行为记录 usage：
- model_id
- prompt tokens
- completion tokens
- audio seconds
- file ingest count
- page action count
- study quiz generation count
- web search count

先用于内部成本对账，不一定立刻展示给用户。

---

## 16. 模型路由策略

## 16.1 原则
- 强模型只用在高价值阶段
- 便宜模型做摘要、标签、抽取、整理
- 作用域越大，越要谨慎控制成本

## 16.2 建议路由
- 页面改写 / 简单总结：轻量模型
- 代码解释 / 复杂 brainstorm：较强模型
- 学习资料大纲 / deck 生成：中档模型批处理
- 语音 / dictation：现有 realtime / asr / tts 管线复用
- 长期 memory explain：复用现有 memory explain 方案

## 16.3 不要做的事
- 所有请求都走最强模型
- 所有用户个性化都靠 fine-tune
- 每次问答都全量塞入全部 notebook 内容

---

## 17. 安全与隐私

必须支持：
- 用户删除页面时，对应 memory evidence 的可追踪处理
- 用户拒绝某条 memory 时，不要继续高频使用
- 页面/记忆权限遵循 workspace/project/user 可见性
- 附件访问必须鉴权
- 后端沿用现有 auth/csrf/rate limit 风格
- AI 引用外部资料时要标注来源

---

## 18. MVP 开发顺序（请直接按这个顺序落地）

## Phase 1：数据模型与基础路由
实现：
- Notebook / Page / Block / PageVersion / Attachment / StudyAsset 基础表
- Alembic migration
- 基础 CRUD API
- 页面快照

完成标准：
- 能创建 notebook
- 能创建页面
- 能插入/编辑 block
- 能保存和恢复页面

## Phase 2：窗口管理器 + 前端编辑器
实现：
- `/app/notebooks`
- `/app/notebooks/[notebookId]` — 笔记本工作区（画布）
- WindowManager 核心：窗口状态管理（位置/尺寸/z-index/最小化/最大化）
- Window 通用壳：标题栏、拖拽、缩放、关闭、边界约束（防止拖出屏幕）
- MinimizedTray：侧栏底部最小化窗口列表
- NoteWindow：TipTap block editor 运行在窗口容器内
- 代码块 / latex / file / ai_output / drawing 块
- autosave
- 侧栏页面树（点击页面 → 在画布上打开窗口）

完成标准：
- 用户可以从侧栏打开多个页面窗口
- 窗口可自由拖拽、缩放、重叠、最小化、最大化
- 窗口不可完全拖出可视区域
- 最小化的窗口出现在侧栏底部，可点击恢复
- 用户可以稳定写内容，重进页面后内容仍在
- 可新增/删除/排序 block

## Phase 3：页内 AI + 文件窗口
实现：
- selection actions
- page actions
- AIPanelWindow：AI 面板作为独立浮动窗口（替代固定右侧面板）
- FileWindow：文件查看器窗口（PDF/图片/文本等）
- ChatWindow：AI 对话窗口
- 生成 ai_output block
- AIActionLog

完成标准：
- 用户可以选中一段文字让 AI 改写
- 用户可以对整个页面做总结/续写/大纲整理
- AI 输出能写回页面
- 用户可以在一个窗口里看 PDF，另一个窗口里写笔记
- AI 对话以独立窗口形式打开，可和笔记并排使用

## Phase 4：Memory V3 真正接入（P0 — 最高优先级）
实现：
- **UnifiedMemoryPipeline**：从 `worker_tasks.py` 的 chat memory extraction 逻辑中抽出通用 service
  - 支持 source_type: `chat_message | notebook_page | uploaded_document | whiteboard | book_chapter`
  - 完整链路: extract → triage → promote → supersede → concept-parent → evidence
- 将现有 chat memory extraction 迁移为调用 UnifiedMemoryPipeline
- Notebook page 的异步记忆处理调用 UnifiedMemoryPipeline（替代弱版 `note_memory_bridge.py`）
- Page memory/confirm 走完整 promote 链路（不只改 decision 字段）
- Page memory/reject 走完整 reject 链路（降低同类 confidence）
- MemoryWindow：记忆面板作为浮动窗口，展示双向链接
- 与现有 memory/search/explain/subgraph 连接

完成标准：
- 页面编辑一段时间后能通过 UnifiedMemoryPipeline 产生真正的 Memory 节点（不只是候选）
- 用户确认候选记忆后，能看到完整的证据链（page → evidence → memory → subject）
- Chat 和 Notebook 使用同一套 memory pipeline，行为一致
- 页面可查看关联 memory，memory 可追溯来源页面
- AI 回答可显示相关 evidence/memory

## Phase 4.5：Retrieval Orchestration（P1）
实现：
- AI Ask 请求前的多层检索编排
  - Page current text + selected context
  - memory/search 命中 subject / subgraph
  - memory/search/explain 推理结果
  - Document chunks（上传文件）
  - Page history / related pages
- Token budget 控制和上下文裁剪
- 回答中展示引用来源标记

完成标准：
- 用户在 AI 窗口提问时，回答能引用长期记忆中的内容
- 用户能看到回答引用了哪些 memory / page / document chunk
- 回答质量明显优于只用当前页全文的版本

## Phase 5：学习系统（P2 — 一级工作流）
实现：
- 上传任何文件类型（不限 PDF）
- 自动解析/分 chunk/索引
- 自动创建笔记本页面（书籍概览 / 章节页 / 读书笔记页）
- study ask（通过 Retrieval Orchestration，结合 chunk + memory + 笔记）
- 自动生成知识点和 deck（flashcard block type）
- 将用户笔记关联到 study asset
- 通过 UnifiedMemoryPipeline(source_type="book_chapter") 将知识点写入 Memory
- 同时记录"用户的理解和困惑"到 Memory

完成标准：
- 上传一本书后自动生成概览页和章节页
- 在一个窗口看书、另一个窗口写笔记
- 能生成学习卡片（嵌入页面 flashcard block）
- 用户笔记可关联章节
- 书中知识点能进入 Memory 的 Subject Graph
- 学习过程中的理解/困惑也被记忆

## Phase 6：收费
实现：
- Stripe checkout
- portal
- webhook
- entitlements
- Free/Pro plan gating

完成标准：
- 用户能升级订阅
- 不同计划看到不同能力
- webhook 幂等可靠

## Phase 7：主动服务
实现：
- daily digest
- weekly reflection
- stale/reconfirm reminders

完成标准：
- 用户第二天能看到系统给出的继续建议
- 用户能收到学习/工作推进提醒

---

## 19. 前端交互细节

## 19.1 slash menu
输入 `/` 时可插入：
- 文本
- 标题
- 清单
- 代码
- 公式
- 草图
- 文件
- AI 总结块
- AI brainstorm 块
- 学习问答块

## 19.2 右键 / 选区菜单
显示：
- 改写
- 总结
- 扩展
- 解释
- 转任务
- 提炼记忆
- 查相关页面
- 查相关记忆

## 19.3 窗口标题栏
每个窗口的标题栏展示：
- 窗口图标（根据内容类型：页面/文件/对话/记忆等）
- 内容标题（页面名/文件名/对话名）
- 窗口操作按钮：最小化（缩入侧栏）、最大化（填满画布）、关闭

页面类型窗口标题栏额外展示：
- 页面 emoji/icon
- 页面类型标签
- 最近更新时间
- 自动保存状态指示

## 19.4 AI 面板窗口
AI 面板不再是固定右侧栏，而是一个独立浮动窗口，可从笔记窗口内触发打开。

AI 窗口内标签页：
- Ask（向 AI 提问）
- Summary（页面摘要）
- Related（相关页面/记忆/资料）
- Memory（本页关联的记忆）
- Study（学习卡片/测验）
- Trace（调试模式，开发者可见）

AI 窗口可以：
- 和任意笔记窗口并排使用
- 同时打开多个 AI 窗口（绑定不同页面上下文）
- 最小化到侧栏

## 19.5 最小化托盘（侧栏底部）
- 所有被最小化的窗口以图标 + 缩略标题列在侧栏下半部分
- 点击恢复窗口到原位置和尺寸
- 右键可关闭窗口
- 风格类似 VS Code 的面板列表

---

## 20. 页面与块的数据格式建议

`NotebookBlock.content_json` 举例：

### paragraph
```json
{
  "text": "这是一段正文"
}
```

### code
```json
{
  "language": "typescript",
  "code": "export function hello() {}",
  "filename": "hello.ts"
}
```

### latex
```json
{
  "source": "\\int_a^b f(x) dx",
  "display_mode": true
}
```

### drawing
```json
{
  "tool": "excalidraw",
  "scene": {}
}
```

### file
```json
{
  "attachment_id": "att_123",
  "title": "chapter1.pdf"
}
```

### ai_output
```json
{
  "action_type": "summarize_page",
  "source_scope": "page",
  "content_markdown": "AI 生成的内容",
  "references": [
    {
      "type": "page",
      "id": "page_123"
    }
  ]
}
```

---

## 21. 数据抽取与服务逻辑建议

## 21.1 页面摘要
每次 autosave 后异步更新：
- summary
- key topics
- open loops
- extracted todos

## 21.2 记忆候选抽取
从页面中识别：
- 用户目标
- 用户偏好
- 用户工作方式
- 用户项目状态
- 用户知识点掌握情况
- 反复出现的问题

## 21.3 playbook 形成条件
当系统观察到：
- 多次类似任务
- 有明确步骤
- 有 outcome 反馈
- 有重复复用迹象

则尝试形成或更新 playbook。

## 21.4 outcome 记录
当用户采纳 AI 结果、勾选完成、将方案推进、将代码复制为正式实现时，可记录 success/partial/failure outcome。

---

## 22. 测试要求

## 22.1 API 测试
至少覆盖：
- notebook/page/block CRUD
- page snapshot/version
- study asset ingest
- page memory extract
- confirm/reject memory
- billing webhook idempotency

## 22.2 前端 Playwright
至少覆盖：
- 新建 notebook
- 新建页面
- 插入多种 block
- 选中文本做 AI 改写
- 上传 PDF
- AI study ask
- 查看 page memory links
- 升级付费后能力解锁

## 22.3 回归要求
不要破坏：
- 现有 `/app`
- 现有 chat
- 现有 memory workbench
- 现有 pipeline/model catalog
- 现有 auth/workspace flows

---

## 23. 代码组织建议

### Web
建议新增目录：
- `apps/web/app/app/notebooks/...`
- `apps/web/components/notebook/...`
- `apps/web/lib/notebook-sdk.ts`
- `apps/web/lib/study-sdk.ts`
- `apps/web/lib/billing-sdk.ts`

窗口管理器核心组件：
- `apps/web/components/notebook/WindowManager.tsx` — 管理画布上所有窗口的状态（位置/尺寸/z-index/最小化/最大化）
- `apps/web/components/notebook/Window.tsx` — 通用窗口壳（标题栏、拖拽、缩放、关闭、边界约束）
- `apps/web/components/notebook/WindowContent.tsx` — 多态渲染：根据窗口类型分发到对应内容组件
- `apps/web/components/notebook/MinimizedTray.tsx` — 侧栏底部最小化窗口列表
- `apps/web/components/notebook/contents/NoteWindow.tsx` — TipTap 混合编辑器窗口
- `apps/web/components/notebook/contents/CodeWindow.tsx` — 纯代码编辑器窗口
- `apps/web/components/notebook/contents/CanvasWindow.tsx` — Excalidraw 画布窗口
- `apps/web/components/notebook/contents/FileWindow.tsx` — 文件查看器窗口（PDF/图片/文本等）
- `apps/web/components/notebook/contents/ChatWindow.tsx` — AI 对话窗口
- `apps/web/components/notebook/contents/MemoryWindow.tsx` — 记忆面板窗口
- `apps/web/components/notebook/contents/AIPanelWindow.tsx` — 页面级 AI 面板窗口
- `apps/web/components/notebook/contents/StudyWindow.tsx` — 学习卡片/复习窗口

### API
建议新增：
- `apps/api/app/routers/notebooks.py`
- `apps/api/app/routers/study.py`
- `apps/api/app/routers/notebook_ai.py`
- `apps/api/app/routers/billing.py`
- `apps/api/app/services/unified_memory_pipeline.py` — **核心：统一记忆管线**（从 worker_tasks.py 的 chat extraction 抽出）
- `apps/api/app/services/retrieval_orchestration.py` — **核心：多层检索编排**（AI Ask 前的上下文组装）
- `apps/api/app/services/notebook_*`
- `apps/api/app/services/study_*`
- `apps/api/app/tasks/notebook_tasks.py`
- `apps/api/app/tasks/unified_memory_tasks.py` — 统一记忆任务入口

---

## 24. UI 风格建议

整体视觉风格延续现有 console/workspace，但 notebook 工作区要更偏”内容创作 + 桌面操作系统”：

- 干净、高可读性、少噪声
- 画布背景应微妙但可辨识，让用户感知到”这是一个工作台面”
- 窗口风格统一：半透明/毛玻璃标题栏，轻量边框，圆角
- 窗口获得焦点时有明确的视觉提示（边框高亮或阴影加深）
- AI 面板作为独立窗口，不会过度抢占空间
- 调试类视图（Memory Trace 等）放在窗口内的二级标签，不干扰主流程
- 最小化托盘融入侧栏设计，不另起新 UI 区域

---

## 25. 需要优先复用的已有系统

如果现有仓库已有对应能力，请优先复用：
- workspace auth / role
- project selector
- model catalog
- pipeline config
- realtime / asr / tts
- data item / dataset / MinIO 上传链路
- memory sdk / memory routes
- benchmark/test harness 模式
- existing API error shape

---

## 26. 实现时的工程约束

- 所有新增表必须带 migration
- 所有 AI 请求必须记 action log 和 usage
- 所有用户内容保存必须能恢复
- 所有附件必须鉴权
- 所有跨 memory 的引用最好有 trace
- 所有删除操作优先软删或保留足够审计信息
- 新功能默认 behind feature flag 或至少隔离到 notebook 路由
- 保持本地 `./scripts/dev.sh` 可运行

---

## 27. 交付标准

当这一轮开发完成时，我希望得到的不是 demo，而是一个在现有 MRAI 内可运行的真实模块，达到以下效果：

1. 我可以进入 `/app/notebooks`
2. 我可以创建一个 notebook
3. 我可以创建一个 page
4. 我可以在 page 里混合写文字、代码、LaTeX、插文件、插草图
5. 我可以选中内容让 AI 处理，并把结果写回页面
6. 我可以上传一本书，然后在这个 notebook 里做读书笔记和提问
7. 系统会把页面内容逐渐变成长期记忆候选
8. 我能看到页面和 memory 的关联
9. 我能让 AI 基于当前页、当前 notebook、当前 project、长期 memory 来帮助我
10. 我可以用 Stripe 开始收费，并对不同套餐限制不同能力

---

## 28. 给 Claude 的最后指令

请直接开始实现，不要停留在产品讨论。  
按“Phase 1 → Phase 7”顺序推进。  
每个 phase 都至少完成：

- 数据结构
- API
- 前端页面
- 最小可用交互
- 测试

优先保证“能跑通”，其次再逐步打磨。

如果某个局部实现成本过高，先交付一个工程上合理的版本，但不要破坏整体架构方向。

重点不是做一个花哨编辑器，而是做出下面这个闭环：

**用户写下一页内容 → AI 帮助当前工作 → 系统抽取长期记忆 → 第二天继续基于这些记忆提供服务**

这就是产品的核心。
