# MRAI / MRNote Monorepo

这个仓库已经不是一个只做 `Memory V3` 的实验仓库了。

它现在是一套以 notebook 为中心的 AI 工作系统，当前主产品形态是 `MRNote`：用户可以在同一个工作区里写页面、上传资料、与 AI 协作、进行学习复习、做全局/笔记本搜索，并把长期内容沉淀进可解释的记忆系统。

## 命名说明

这个仓库里同时存在三套命名，需要先看懂：

- `MRAI`：仓库 / 工作区 / 顶层产品方案名称
- `MRNote`：当前 Web 端面向用户的产品名称，也是默认数据库、Docker/环境变量、bucket 和 Python package 命名
- `Mingrun Tech / 铭润科技`：公司 / 法务主体名称，主要出现在法律页、邮件发件方和站点页脚

它们不是三个不同系统，而是同一个代码库在不同阶段留下的命名层。

## 这个仓库当前包含什么

- 面向 `MRNote` 的营销官网、定价页、法律页和认证流程
- 登录后的 notebook-centric AI workspace
- 基于窗口系统的 notebook 画布：页面、AI 面板、文件、记忆、记忆图谱、学习、digest、搜索
- FastAPI 后端，覆盖 auth / notebooks / pages / chat / memory / study / search / billing / realtime / digests 等能力
- Celery worker + beat 后台任务系统
- Postgres + pgvector、Redis、MinIO 的本地开发栈
- 一套仍在持续演进的 `Memory V3` 长期记忆图谱和学习闭环
- 仍保留的老能力：`projects / datasets / models / pipeline / model catalog`

如果你把它理解成“一个以 notebook 为中心、把聊天、学习、检索和长期记忆打通的 AI 工作系统”，会比把它理解成“chat app + memory 模块”更接近现状。

## 核心产品能力

### 1. Notebook 工作区

- 路由中心是 `/app/notebooks`
- 登录后工作台会展示 notebooks、continue writing、recommended pages、recent study、AI today、work themes、long-term focus
- 单个 notebook 工作区使用窗口管理器，支持这些窗口类型：
  - `note`
  - `ai_panel`
  - `file`
  - `memory`
  - `memory_graph`
  - `study`
  - `digest`
  - `search`

### 2. 页面编辑与页面内 AI

- 页面数据存为 TipTap/ProseMirror `content_json`
- 编辑器扩展已覆盖：
  - AI output block
  - callout
  - file block
  - flashcard block
  - inline / block math
  - reference block
  - task block
  - whiteboard block
- 页面支持：
  - attachment upload
  - snapshot / versions
  - export
  - page → memory extract / confirm / reject / trace
- AI 面板当前有这些 tab：
  - Ask
  - Summary
  - Related
  - Memory
  - Study
  - Trace

### 3. Chat 与 Realtime

- `/api/v1/chat` 提供 conversation/message、SSE stream、voice、dictate、speech、image 等接口
- chat mode 当前有三种：
  - `standard`
  - `omni_realtime`
  - `synthetic_realtime`
- 前端有完整的 realtime voice / camera / dictation hooks 和 Playwright 覆盖
- message inspector 能显示 reasoning、retrieval trace、memory write、memory learning 等调试信息

### 4. Memory V3

后端 `apps/api/app/routers/memory.py` 仍是很重的一块，当前代码里已经包含：

- graph/list/detail/subgraph
- layered search + search explain
- evidences / views / playbooks / health / learning runs / outcomes
- memory file linking
- edge create/delete
- backfill / promote / supersede / visibility / metadata 相关处理
- chat / notebook / study 内容到 memory 的统一沉淀链

### 5. 学习系统

- notebook 内可上传 study assets
- 支持 chunking、ingest、insights
- 支持 AI ask / flashcards / quiz
- 支持 decks / cards / review
- 复习调度使用 `FSRS`
- study confusion 可进入 memory 流水线

### 6. 搜索与主动服务

- `/api/v1/search/global`
- `/api/v1/notebooks/{notebook_id}/search`
- `/api/v1/pages/{page_id}/related`
- `/api/v1/digests/*` 提供 unread count、列表、详情、read/dismiss、generate-now

### 7. 认证、计费与权限

- 邮箱验证码注册 / 登录 / 重设密码
- Google OAuth，默认 feature-flag 关闭
- Stripe 计费：`free / pro / power / team`
- entitlement gating 已接到 notebook/page/study asset/AI action/voice/daily digest/advanced memory surfaces
- 服务端包含 TrustedHost、CORS、security headers、CSRF、防跨 workspace 访问等安全处理

## 仓库结构

| 路径 | 作用 |
| --- | --- |
| `apps/web` | Next.js 16 前端，当前主产品外壳 |
| `apps/api` | FastAPI + SQLAlchemy + Celery 后端 |
| `docker` | `docker-compose.yml` 与 API / Web / Worker Dockerfiles |
| `scripts` | 本地开发脚本、memory benchmark、Qwen catalog 同步脚本 |
| `docs/superpowers/specs` | 功能设计文档 |
| `docs/superpowers/plans` | 实施计划文档 |
| `docs/reviews` | 审计 / review 文档 |
| `design-system` | `MRAI Notebook OS` / `MRNote` 设计系统 master 文档 |
| `output` | Playwright 等测试输出目录 |
| `tmp` | 本地开发状态、日志、临时文件目录 |
| `MRAI_notebook_ai_os_build_spec.md` | 当前 notebook-centric 产品总说明 |

## 主要页面与路由

### 公共页面

- `/`
- `/pricing`
- `/privacy`
- `/terms`
- `/login`
- `/register`
- `/forgot-password`

`next-intl` 当前配置为：

- 语言：`zh` / `en`
- 默认语言：`zh`
- `zh` 走裸路径，例如 `/`
- `en` 走 `/en/*`

### 登录后页面

- `/app`
- `/app/notebooks`
- `/app/notebooks/[notebookId]`
- `/app/notebooks/[notebookId]/pages/[pageId]`
- `/app/notebooks/[notebookId]/chat`
- `/app/notebooks/[notebookId]/memory`
- `/app/notebooks/[notebookId]/settings`
- `/app/settings`
- `/app/settings/billing`

其中 `/app` 当前会重定向到 `/app/notebooks`。

## 技术栈

### 前端

- Next.js `16.2.4`
- React `19.2`
- TypeScript `5.9`
- npm `11.12.1` / `package-lock.json`
- next-intl
- TipTap
- Radix UI
- Tailwind CSS
- D3
- Three.js
- Framer Motion / GSAP
- Playwright
- Vitest

### 后端

- Python `>=3.11`
- FastAPI
- SQLAlchemy 2
- Alembic
- Celery
- Redis
- Authlib
- Stripe SDK
- boto3
- pdfplumber

### 基础设施

- Postgres / pgvector
- Redis
- MinIO
- Docker Compose

### AI / 第三方集成

- Alibaba Cloud DashScope / Qwen
- Google OAuth
- Stripe
- SMTP 邮件

## 本地开发要求

建议准备：

- Node.js `24.15.0`
- npm `11.12.1`
- Python `>=3.11`
- Docker
- `uv`

先复制环境文件：

```bash
cp .env.example .env
```

然后按需补充变量：

- `DASHSCOPE_API_KEY`：启用真实 AI 能力所必需
- `GOOGLE_*` / `GOOGLE_OAUTH_ENABLED`：启用 Google 登录
- `STRIPE_*`：启用 billing
- `SMTP_*`：启用验证码邮件

## 一键启动

在仓库根目录执行：

```bash
./scripts/dev.sh
```

默认是“本地快启模式”：

- `postgres` / `redis` / `minio` 通过 Docker Compose 启动
- `api` / `worker` / `beat` / `web` 作为本地进程启动
- API 使用 `uvicorn --reload`
- Web 使用 `next dev`
- 脚本会自动安装依赖：
  - API 走 `uv sync --locked --extra dev`
  - Web 走 `npm@11.12.1` + `npm ci`

启动后默认地址：

- Web: [http://localhost:3000](http://localhost:3000)
- API: [http://localhost:8000](http://localhost:8000)
- API Health: [http://localhost:8000/health](http://localhost:8000/health)
- MinIO Console: [http://localhost:9001](http://localhost:9001)

常用参数：

```bash
./scripts/dev.sh --rebuild
./scripts/dev.sh --clean
./scripts/dev.sh --docker
./scripts/dev.sh --clean-artifacts
```

含义：

- `--rebuild`：重装依赖或重建镜像
- `--clean`：先清理旧栈，再重新启动
- `--docker`：全量 Docker Compose 模式
- `--clean-artifacts`：清理 Playwright 产物

## 手动运行

### API

```bash
cd apps/api
uv sync --locked --extra dev
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Worker

```bash
cd apps/api
.venv/bin/celery -A app.tasks.celery_app:celery_app worker -l INFO -Q celery,data,cleanup,inference,memory
```

### Beat

```bash
cd apps/api
.venv/bin/celery -A app.tasks.celery_app:celery_app beat -l INFO
```

### Web

```bash
cd apps/web
npm --version  # should be 11.12.1
npm ci
npm run dev
```

## 数据库、对象存储与后台任务

### 数据库

- API 启动时会自动：
  - 校验运行时配置
  - 在非 test / 非 sqlite 环境执行 `alembic upgrade head`
  - seed model catalog
- test / sqlite 模式下会走直接 schema bootstrap

手动迁移：

```bash
cd apps/api
.venv/bin/alembic upgrade head
```

### MinIO

本地 compose 默认凭据：

- 用户名：`minioadmin`
- 密码：`minioadmin`

compose 初始化脚本会创建：

- `mrnote-private`
- `mrnote-demo`

API 启动时还会按需确保这些 bucket 存在：

- `ai-action-payloads`
- `notebook-attachments`

### Celery 与计划任务

`apps/api/app/tasks/celery_app.py` 当前定义了：

- 数据处理 / 清理 / inference / memory 等任务路由
- beat schedule：
  - stale record purge
  - nightly memory sleep cycle
  - daily digests
  - weekly reflections
  - deviation reminders
  - relationship reminders
  - notebook page embedding backfill
  - one-time subscription expiry

注意：代码里存在 `memory` 队列路由，但 `scripts/dev.sh` 和当前 `docker/Dockerfile.worker` 默认只监听：

```text
celery,data,cleanup,inference
```

所以如果你要验证某些 `memory` 队列任务是否被真正消费，需要先检查 / 调整 worker 队列配置，不要在 README 层面默认假定它们已经全部接通。

## 关键环境变量

`.env.example` 提供了本地开发共享样例，但它不是所有可选配置的全集。当前最重要的变量分组如下：

### 基础运行

- `ENV`
- `DATABASE_URL`
- `REDIS_URL`
- `REDIS_NAMESPACE`
- `CORS_ORIGINS`
- `ALLOWED_HOSTS`

### 对象存储 / 上传

- `S3_ENDPOINT`
- `S3_PRESIGN_ENDPOINT`
- `S3_ACCESS_KEY`
- `S3_SECRET_KEY`
- `S3_PRIVATE_BUCKET`
- `S3_DEMO_BUCKET`
- `UPLOAD_MAX_MB`
- `UPLOAD_PUT_PROXY`

### AI / DashScope / Qwen

- `DASHSCOPE_API_KEY`
- `DASHSCOPE_MODEL`
- `DASHSCOPE_EMBEDDING_MODEL`
- `THINKING_CLASSIFIER_MODEL`
- `WEB_SEARCH_CLASSIFIER_MODEL`

如果没有 `DASHSCOPE_API_KEY`，很多 AI 能力会降级或直接失败，realtime 路由也会返回 `model_api_unconfigured`。

### 邮件 / 认证

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM_ADDRESS`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_BASE`
- `OAUTH_SESSION_SECRET`
- `GOOGLE_OAUTH_ENABLED`

### Billing / Stripe

这些变量在 `app.core.config.Settings` 中已支持，但并没有全部写进根 `.env.example`：

- `STRIPE_API_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_BILLING_PORTAL_RETURN_URL`
- `STRIPE_CHECKOUT_SUCCESS_URL`
- `STRIPE_CHECKOUT_CANCEL_URL`
- `STRIPE_PRICE_PRO_MONTHLY`
- `STRIPE_PRICE_PRO_YEARLY`
- `STRIPE_PRICE_POWER_MONTHLY`
- `STRIPE_PRICE_POWER_YEARLY`
- `STRIPE_PRICE_TEAM_MONTHLY`
- `STRIPE_PRICE_TEAM_YEARLY`

### Web

- `NEXT_PUBLIC_API_BASE_URL`
- `NEXT_PUBLIC_ASSET_ORIGIN`
- `NEXT_PUBLIC_APP_NAME`
- `NEXT_PUBLIC_DEMO_MAX_IMAGE_MB`

## 测试

### 后端

```bash
cd apps/api
.venv/bin/pytest -q
```

后端测试当前覆盖的重点包括：

- auth / Google OAuth
- notebooks / pages / attachments
- chat / realtime / quota gates
- memory / search / study / digests
- billing / entitlements

### 前端

```bash
cd apps/web
npm run lint
npm run test:unit
npm run build
npm run e2e
```

前端测试当前覆盖的重点包括：

- marketing homepage
- auth / onboarding
- notebook workspace
- editor / AI panel
- study / digests / billing / search
- realtime voice

## 仓库里可直接用的脚本

### `scripts/dev.sh`

本地开发的主入口，负责：

- 启动 / 清理本地栈
- 管理 infra compose
- 安装依赖
- 启动本地 API / worker / beat / web

### `scripts/run_memory_benchmark.py`

针对 live API 执行 `memory/search` 与 `memory/search/explain` 的 benchmark harness。

查看帮助：

```bash
python3 scripts/run_memory_benchmark.py --help
```

示例 fixture：[`scripts/fixtures/memory_benchmark.sample.json`](scripts/fixtures/memory_benchmark.sample.json)

### `scripts/sync_qwen_official_catalog.py`

抓取并刷新后端使用的 Qwen 官方模型目录快照。

### `apps/api/scripts/repair_memory_graph.py`

对单个 project 执行 memory graph repair。

```bash
cd apps/api
.venv/bin/python scripts/repair_memory_graph.py --workspace-id <workspace-id> --project-id <project-id>
```

## API 模块总览

`apps/api/app/routers/` 当前主要模块如下：

| 路由前缀 | 作用 |
| --- | --- |
| `/api/v1/auth` | 注册、登录、登出、验证码、重设密码、CSRF、Google OAuth、connected identities |
| `/api/v1/notebooks` / `/api/v1/pages` | notebook/page CRUD、home summary、versions、export、page-memory linkage、attachments |
| `/api/v1/ai/notebook` | 页面选区操作、page ask、whiteboard summarize |
| `/api/v1/chat` | conversations、stream、voice、dictate、speech、image |
| `/api/v1/memory` | graph、detail、search、explain、health、learning runs、playbooks、outcomes、edges |
| `/api/v1/realtime` | ws-ticket 与 realtime websocket 能力 |
| `/api/v1/search` / `/api/v1/notebooks/{id}/search` | 全局搜索、notebook 搜索、related pages |
| `/api/v1/notebooks/{id}/study` / `/api/v1/study-assets` | study assets、chunks、insights、ingest |
| `/api/v1/ai/study` / `/api/v1/decks` / `/api/v1/cards` | flashcards、quiz、study ask、deck/card/review |
| `/api/v1/digests` | proactive digest |
| `/api/v1/billing` | checkout、portal、me、plans、webhook |
| `/api/v1/models/catalog` / `/api/v1/pipeline` | 模型目录与 pipeline 配置 |
| `/api/v1/projects` / `/api/v1/datasets` / `/api/v1/models` | 较早期的 project/dataset/model 管理接口，当前仍在后端中保留 |

## 文档索引

如果你要继续开发这个仓库，建议先看这些文档：

- 产品总说明：
  - [`MRAI_notebook_ai_os_build_spec.md`](MRAI_notebook_ai_os_build_spec.md)
- 设计文档：
  - [`docs/superpowers/specs`](docs/superpowers/specs)
- 实施计划：
  - [`docs/superpowers/plans`](docs/superpowers/plans)
- 最近一次 Web 审计：
  - [`docs/reviews/2026-04-21-web-audit.md`](docs/reviews/2026-04-21-web-audit.md)
- 设计系统：
  - [`design-system/mrai-notebook-os/MASTER.md`](design-system/mrai-notebook-os/MASTER.md)
  - [`design-system/mrnote/MASTER.md`](design-system/mrnote/MASTER.md)

## 当前状态总结

这个仓库的“主产品方向”已经很明确：

- 前台是 `MRNote` 形式的 notebook AI workspace
- 中台是 notebooks / pages / search / study / digests / billing / auth
- 底层长期能力仍然是 `Memory V3`
- 基础设施和后端 package 默认命名已经收敛到 `mrnote`

如果你要在这个仓库继续开发，最稳妥的思路不是“再造一个新模块”，而是顺着现有 notebook-centric 架构，把页面、AI、study、search 和 memory 的闭环继续打通。
