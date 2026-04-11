# MRAI 结构重构设计：以笔记本为核心的 AI 工作系统

## 概述

将 MRAI 从"AI 助手管理控制台"重构为"以笔记本为核心的 AI 工作系统"。笔记本成为产品的绝对中心，聊天和记忆降级为笔记本的子模块。

## 核心原则

- **笔记本 = 工作空间**：每个笔记本绑定一个 AI 对话 + 一个记忆空间
- **智能首页**：登录后进入"今日工作台"
- **上下文切换侧栏**：进入笔记本后侧栏完全替换为笔记本内导航

---

## 1. 全局导航

### 1.1 全局侧栏（56px 图标栏）

仅 4 项：

| 位置 | 图标 | 名称 | 路由 |
|------|------|------|------|
| 顶部 | Logo | 品牌 | — |
| 导航1 | LayoutDashboard | 工作台 | `/app` |
| 导航2 | BookOpen | 笔记本 | `/app/notebooks` |
| 导航3 | Settings | 设置 | `/app/settings` |
| 底部 | 头像 | 用户 | 弹出菜单 |

### 1.2 移除的全局导航项

| 原路由 | 处理方式 |
|--------|----------|
| `/app/chat` | 迁移到 `/app/notebooks/[id]/chat` |
| `/app/memory` | 迁移到 `/app/notebooks/[id]/memory` |
| `/app/assistants/*` | 合并到笔记本设置 |
| `/app/discover/*` | 暂时移除 |

### 1.3 笔记本内侧栏

进入笔记本后，56px 图标栏完全替换为笔记本内导航：

| 位置 | 图标 | 名称 | 行为 |
|------|------|------|------|
| 顶部 | ArrowLeft | 返回 | 返回笔记本列表 |
| Tab1 | FileText | 页面 | 展开页面树面板 (240px) |
| Tab2 | MessageSquare | AI 对话 | 展开对话列表面板 |
| Tab3 | Brain | 记忆 | 展开记忆面板 |
| Tab4 | BookOpen | 学习 | 展开学习资料面板 |
| 底部 | Settings | 设置 | 笔记本设置页 |

点击图标展开 240px 面板，再点收起。编辑器宽度弹性适应。

---

## 2. 路由结构

### 2.1 新路由表

```
/app                                    → 今日工作台（智能首页）
/app/notebooks                          → 笔记本列表
/app/notebooks/[id]                     → 笔记本工作区（默认显示页面树 + 空编辑器）
/app/notebooks/[id]/pages/[pid]         → 编辑某个页面
/app/notebooks/[id]/chat                → 笔记本的 AI 对话
/app/notebooks/[id]/memory              → 笔记本的记忆
/app/notebooks/[id]/learn               → 笔记本的学习资料
/app/notebooks/[id]/settings            → 笔记本设置（含 AI 模型配置）
/app/settings                           → 全局设置（账号/语言/订阅）
/login                                  → 登录
/register                               → 注册
```

### 2.2 删除的路由

```
/app/chat              → 删除（迁移到笔记本内）
/app/memory            → 删除（迁移到笔记本内）
/app/assistants/*      → 删除（合并到笔记本设置）
/app/discover/*        → 删除
/app/memory/list-preview → 删除
```

### 2.3 Notebook ↔ Project 映射

每个 `Notebook` 通过 `project_id` 关联一个 `Project`。现有的聊天和记忆 API 全部通过 `project_id` 工作，因此：
- 创建 Notebook 时自动创建 Project（如果 `project_id` 为空）
- 笔记本内的 AI 对话复用现有 `ChatInterface` 组件，传入 `project_id`
- 笔记本内的记忆复用现有记忆页面组件，传入 `project_id`

---

## 3. 页面设计

### 3.1 今日工作台 (`/app`)

居中布局 (max-width: 960px)，三个区块：

1. **欢迎区**：用户名 + 今日概要（页面数、对话数）
2. **继续写作**：最近编辑的 3 个页面卡片（跨笔记本），点击直接进入编辑
3. **我的笔记本**：所有笔记本卡片网格 + 新建按钮
4. **最近对话**：跨笔记本的最近对话列表

### 3.2 笔记本列表 (`/app/notebooks`)

居中布局 (max-width: 960px)：
- 标题 + 新建按钮
- 笔记本卡片网格（玻璃态卡片，显示图标、标题、描述、类型徽章、页面数、更新时间）
- 空状态引导

### 3.3 笔记本工作区 (`/app/notebooks/[id]`)

全屏四栏布局：

```
┌──────┬──────────┬─────────────────────┬──────────┐
│图标栏 │ 展开面板  │     编辑器            │ AI 面板   │
│56px  │ 240px   │     flex-1           │ 320px    │
│固定   │可收起    │                     │可收起     │
└──────┴──────────┴─────────────────────┴──────────┘
```

- **图标栏 (56px)**：笔记本内导航（返回/页面/对话/记忆/学习/设置）
- **展开面板 (240px)**：根据选中的 tab 显示不同内容
- **编辑器 (flex-1)**：TipTap 编辑器，加载当前页面
- **AI 面板 (320px)**：右侧 AI 对话 + 记忆链接，通过右下角按钮开关

### 3.4 笔记本设置 (`/app/notebooks/[id]/settings`)

管理笔记本本身的设置：
- 笔记本名称、描述、图标
- AI 模型选择（复用现有 pipeline 配置 UI）
- 导出/导入

---

## 4. 组件架构

### 4.1 布局组件

| 组件 | 职责 |
|------|------|
| `ConsoleShell` | 全局壳：AmbientBackground + Sidebar + main |
| `GlobalSidebar` | 全局侧栏（工作台/笔记本/设置） |
| `NotebookShell` | 笔记本壳：NotebookSidebar + 内容区 |
| `NotebookSidebar` | 笔记本内侧栏（56px 图标 + 240px 展开面板） |
| `NotebookSidePanel` | 可展开面板（页面树/对话列表/记忆/学习） |

### 4.2 侧栏上下文切换逻辑

```
用户在 /app 或 /app/notebooks
  → 渲染 GlobalSidebar（工作台/笔记本/设置）

用户在 /app/notebooks/[id]/* 
  → 渲染 NotebookSidebar（返回/页面/对话/记忆/学习/设置）
```

通过 URL 路径判断当前上下文：`pathname.match(/\/app\/notebooks\/[^/]+/)` 为真时使用笔记本侧栏。

### 4.3 复用现有组件

| 现有组件 | 复用方式 |
|----------|----------|
| `ChatInterface` | 在 `/notebooks/[id]/chat` 中渲染，传入笔记本的 `project_id` |
| 记忆页面组件 | 在 `/notebooks/[id]/memory` 中渲染，传入 `project_id` |
| `NoteEditor` | 保持不变，在 `/notebooks/[id]/pages/[pid]` 中渲染 |
| `AIPanel` | 保持不变，作为编辑器右侧面板 |
| Glass 组件 | 全部保持，用于侧栏和面板 |

---

## 5. 数据模型变更

### 5.1 Notebook 自动关联 Project

创建笔记本时，如果 `project_id` 为空，后端自动创建一个 Project 并关联：

```python
# 在 notebooks.py create_notebook 端点中
if not notebook.project_id:
    project = Project(
        workspace_id=workspace_id,
        name=f"Notebook: {notebook.title or 'Untitled'}",
    )
    db.add(project)
    db.flush()
    notebook.project_id = project.id
```

这样每个笔记本天然拥有 project_id，可以复用所有现有的聊天和记忆 API。

### 5.2 无需新表

不需要新的数据库表。所有改动都是前端路由和组件层面的重构。

---

## 6. 实施策略

### 阶段 1：侧栏上下文切换
- 新建 `GlobalSidebar` 和 `NotebookSidebar` 组件
- 修改 `ConsoleShell` 根据路由切换侧栏
- 笔记本内侧栏支持展开面板

### 阶段 2：路由迁移
- 新建笔记本内的 chat/memory/settings 路由页面
- 复用现有 ChatInterface 和记忆组件
- 创建笔记本时自动创建 Project
- 更新首页为今日工作台

### 阶段 3：清理
- 删除旧的 `/app/chat`、`/app/memory`、`/app/assistants` 路由
- 更新 GlassTopBar 面包屑
- 更新 CommandPalette
- 全面测试

---

## 7. 风险和约束

- **后端零改动风险**：所有 API 通过 `project_id` 工作，前端只需正确传入笔记本的 `project_id`
- **渐进迁移**：可以先添加新路由再删除旧路由，过渡期两者共存
- **移动端**：笔记本内四栏布局在移动端需要折叠处理（面板改为全屏覆盖）
