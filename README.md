# QIHANG Monorepo

QIHANG 是一套面向 AI assistant 的完整工作台与服务端系统。这个仓库当前包含：

- 公共官网与在线 Demo
- 登录后的 Console / Workspace
- FastAPI + Celery + Postgres 的后端服务
- 一套正在收口为 Beta 的 `Memory V3` 记忆图谱系统

当前主线目标已经不是“做一个能存向量的记忆模块”，而是把记忆升级成：

**可解释、可复盘、可持续学习、可对外服务的记忆图谱系统**

## 当前重点：Memory V3

Memory V3 目前已经具备这些能力：

- unified layered memory search
- `search + explain + subgraph` 三层检索/解释接口
- `episodes / evidences / outcomes / learning-runs / health / playbook feedback`
- 固定六阶段学习闭环：
  - `observe`
  - `extract`
  - `consolidate`
  - `graphify`
  - `reflect`
  - `reuse`
- nightly sleep cycle：
  - compaction
  - graph repair
  - playbook refresh
  - health refresh
  - reflection backfill
- 工作台诊断视图：
  - `Graph`
  - `List`
  - `Views`
  - `Evidence`
  - `Learning`
  - `Health`

更完整的 Beta 收口说明见：

- [Memory V3 Beta Readiness](/Users/dog/Desktop/铭润/docs/superpowers/specs/2026-04-11-memory-v3-beta-readiness.md)

## 仓库结构

- `apps/web`：Next.js 16 前端
- `apps/api`：FastAPI + SQLAlchemy + Celery 后端
- `docker`：本地依赖服务与容器化运行配置
- `scripts/dev.sh`：一键启动本地开发环境
- `scripts/run_memory_benchmark.py`：Memory V3 benchmark harness
- `docs/superpowers/specs`：当前功能规范与收口说明

## 技术栈

### 前端

- Next.js 16
- React 18
- TypeScript
- Playwright

### 后端

- Python 3.11+
- FastAPI
- SQLAlchemy 2
- Celery + Redis
- Postgres

### 依赖服务

- Postgres
- Redis
- MinIO

## 环境要求

建议本地至少准备：

- Node.js `>=20.9.0`
- Python `>=3.11`
- Docker / Docker Compose
- macOS 下如果用 Colima，需要先启动 Colima 并切到对应 docker context

建议先检查：

```bash
node -v
python3 --version
docker info
docker context ls
```

如果你在 macOS 上用 Colima：

```bash
colima start
docker context use colima
```

## 快速启动

首次启动前建议先复制环境文件：

```bash
cp .env.example .env
```

然后在仓库根目录执行：

```bash
./scripts/dev.sh
```

默认是“本机快速模式”：

- `postgres`、`redis`、`minio` 通过 Docker Compose 启动
- `api`、`worker`、`web` 以本机进程启动
- `api` 使用 `uvicorn --reload`
- `web` 使用 `next dev`
- 再次执行会先停旧进程，再以当前代码重启

启动完成后可访问：

- Web: [http://localhost:3000](http://localhost:3000)
- API: [http://localhost:8000](http://localhost:8000)
- API Health: [http://localhost:8000/health](http://localhost:8000/health)
- MinIO Console: [http://localhost:9001](http://localhost:9001)

所有默认端口只绑定到 `127.0.0.1`。

## 启动脚本常用参数

强制重装本机依赖：

```bash
./scripts/dev.sh --rebuild
```

清掉旧进程、旧容器和本地临时产物：

```bash
./scripts/dev.sh --clean
```

切回完整 Docker 构建模式：

```bash
./scripts/dev.sh --docker
```

如果脚本无执行权限：

```bash
chmod +x ./scripts/dev.sh
```

## 本地开发默认值

一键启动时，脚本会把容器内网地址自动改写成适合本机开发的地址，常见值包括：

- `COOKIE_DOMAIN=""`
- `COOKIE_SECURE=false`
- `S3_ENDPOINT=http://localhost:9000`
- `S3_PRESIGN_ENDPOINT=http://localhost:9000`
- `S3_PRIVATE_BUCKET=qihang-private`
- `S3_DEMO_BUCKET=qihang-demo`
- `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`
- `NEXT_PUBLIC_ASSET_ORIGIN=http://localhost:9000`

根目录 `.env` 是本地开发的优先入口。敏感信息也统一放在 `.env`，不要写进 compose 文件。

## MinIO 默认值

默认本地对象存储账号：

- 用户名：`minioadmin`
- 密码：`minioadmin`

默认 buckets：

- `qihang-private`
- `qihang-demo`

其中：

- `qihang-private` 用于数据集、训练产物、模型产物
- `qihang-demo` 用于匿名 Demo 临时文件

## Gmail SMTP

如果你要在本地启用 Gmail 验证码邮件，编辑根目录 `.env`：

```bash
SMTP_USER=your-mailbox@gmail.com
SMTP_PASSWORD=your-16-char-gmail-app-password
SMTP_FROM_ADDRESS=your-mailbox@gmail.com
```

建议只使用 Gmail App Password，不要使用邮箱登录密码。

## 手动启动各个子应用

### 启动 API

```bash
cd apps/api
uv pip install -e '.[dev]'
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 启动 Worker

```bash
cd apps/api
celery -A app.tasks.celery_app.celery_app worker -l info
```

### 启动 Web

```bash
cd apps/web
npm install
npm run dev
```

## 关键 API

### 通用

- API 前缀：`/api/v1`
- 统一错误结构：

```json
{
  "error": {
    "code": "string_enum",
    "message": "human_readable",
    "details": {},
    "request_id": "uuid"
  }
}
```

### Memory V3

Memory 模块当前保留并收口为正式 Beta 契约的接口包括：

- `POST /api/v1/memory/search`
- `POST /api/v1/memory/search/explain`
- `POST /api/v1/memory/{memory_id}/subgraph`
- `POST /api/v1/memory/outcomes`
- `GET /api/v1/memory/learning-runs`
- `GET /api/v1/memory/learning-runs/{id}`
- `GET /api/v1/memory/health`
- `GET /api/v1/memory/playbooks`
- `POST /api/v1/memory/playbooks/{id}/feedback`
- `GET /api/v1/chat/messages/{message_id}/memory-learning`

前端侧可复用的最小 SDK 在：

- [memory-sdk.ts](/Users/dog/Desktop/铭润/apps/web/lib/memory-sdk.ts)

## Memory V3 Benchmark

仓库内提供了一个可重复执行的 benchmark harness：

- [run_memory_benchmark.py](/Users/dog/Desktop/铭润/scripts/run_memory_benchmark.py)
- [memory_benchmark.sample.json](/Users/dog/Desktop/铭润/scripts/fixtures/memory_benchmark.sample.json)

先查看参数：

```bash
python3 scripts/run_memory_benchmark.py --help
```

示例：

```bash
python3 scripts/run_memory_benchmark.py \
  --fixture scripts/fixtures/memory_benchmark.sample.json \
  --api-base-url http://127.0.0.1:8000 \
  --workspace-id <workspace-id> \
  --cookie "auth_state=1; mingrun_workspace_id=<workspace-id>" \
  --csrf-token <csrf-token>
```

这个脚本会校验：

- 命中预期 memory
- 返回预期 result types
- explain trace 是否包含关键字段

失败时会返回非零退出码，适合接进发布前验证或 CI 包装脚本。

## 数据库迁移

```bash
cd apps/api
uv pip install -e '.[dev]'
alembic upgrade head
```

本地一键启动默认会自动建表，但在显式迁移或升级环境时仍建议执行 `alembic upgrade head`。

## 测试

### 后端集成测试

```bash
cd apps/api
uv venv .venv
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/python -m pytest -q
```

### 前端 lint

```bash
cd apps/web
npm install
npm run lint
```

### Playwright

```bash
cd apps/web
npx playwright test
```

### 本轮 Memory V3 关键回归

后端：

```bash
cd apps/api
python3 -m pytest tests/test_api_integration.py -k 'memory_search_explain_returns_trace_suppressed_candidates_and_subgraph or memory_subgraph_route_returns_parent_edge_for_visible_neighbors or memory_sleep_cycle_task_backfills_reflection_and_health or learning_runs_routes_hide_private_memory_runs_from_viewer or playbook_feedback_route_rejects_private_playbook_for_viewer or memory_search_returns_layered_mixed_hits_for_playbook_queries'
```

前端：

```bash
cd apps/web
PLAYWRIGHT_PORT=3101 npx playwright test tests/console-shell.spec.ts -g 'memory workbench surfaces learning and health panels|memory detail panel reflects promote immediately without reopening|memory detail panel surfaces V3 diagnostics and episode context|context inspector surfaces V3 selection diagnostics from layered traces'
```

## 人工验收建议

建议至少走一遍：

1. 打开 `/` 与 `/demo`
2. 注册账号并进入 `/app`
3. 创建项目并确认工作台可正常进入
4. 打开 `/app/memory`
5. 确认 `Graph / List / Views / Evidence / Learning / Health` 六个主视图
6. 在 `Learning` 中点一条 run，确认 detail 打开到 `学习记录`
7. 在 `Health` 中点 stale / playbook 项，确认 detail 落到正确 tab
8. 在 chat inspector 中确认 retrieval trace / evidence / outcome linkage 可见
9. 跑一次 benchmark harness，确认 explain trace 不退化

## 故障排查

### 1. `./scripts/dev.sh` 无权限

```bash
chmod +x ./scripts/dev.sh
```

### 2. Web / API 没起来

```bash
curl -I http://localhost:3000
curl -I http://localhost:8000/health
docker compose -f docker/docker-compose.yml ps
```

### 3. Playwright 启动时报 `next dev` lock

这是 `.next/dev/lock` 的陈旧锁文件问题，先删掉：

```bash
rm -f apps/web/.next/dev/lock
```

然后换一个端口重跑：

```bash
cd apps/web
PLAYWRIGHT_PORT=3101 npx playwright test
```

### 4. Worker 代码修改后没生效

`worker` 默认没有像 `web` / `api` 那样的热更新。改了 Celery 任务代码后，直接重新执行：

```bash
./scripts/dev.sh
```

### 5. 只想停止服务

```bash
pkill -F tmp/dev-local/pids/web.pid 2>/dev/null || true
pkill -F tmp/dev-local/pids/api.pid 2>/dev/null || true
pkill -F tmp/dev-local/pids/worker.pid 2>/dev/null || true
docker compose -f docker/docker-compose.yml down
```

## 相关文档

- [Memory V3 Beta Readiness](/Users/dog/Desktop/铭润/docs/superpowers/specs/2026-04-11-memory-v3-beta-readiness.md)
- [Memory Module Redesign](/Users/dog/Desktop/铭润/docs/superpowers/specs/2026-04-08-memory-module-redesign.md)

## 当前状态

这个仓库当前最强的能力已经不是“普通 memory search”。

你真正应该把它理解成：

**一个正在进入 Beta 的 AI 自主循环学习记忆图谱系统。**

它的主价值在于：

- 记住事实
- 保留证据
- 累积方法
- 记录结果
- 形成健康信号
- 在下一轮检索中把这些结果真正用回来
