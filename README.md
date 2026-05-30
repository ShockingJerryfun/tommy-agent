# Tommy Agent

**English** | [中文](#tommy-agent-中文)

Tommy Agent is a local-first AI agent workbench for long-running, tool-using conversations. It combines a LangGraph runtime, a FastAPI backend, PostgreSQL persistence, and a Next.js workspace UI for streaming chat, approvals, memory, context management, skills, and run inspection.

> Project status: active product prototype. The codebase is optimized for local development and clear module boundaries.

## Highlights

- **LangGraph runtime** for controllable agent execution and streaming state updates.
- **FastAPI service** for sessions, messages, runs, approvals, memory, prompts, skills, and search.
- **PostgreSQL persistence** for conversations, run events, checkpoints, memory records, tool calls, and skill data.
- **Next.js workbench** with chat, session management, run state, settings, approvals, memory, and skill panels.
- **Human approval flow** for sensitive tool actions.
- **Context Pact and memory proposals** to keep long conversations structured and reviewable.
- **Provider-flexible models** through DeepSeek, OpenRouter, or OpenAI-compatible APIs.
- **Optional Tavily search** for web-enabled tool calls.
- **English / Chinese UI switching** in the frontend.

## Architecture

```text
backend/
  app/agent_framework/
    server/          # FastAPI app and API schemas
    runtime/         # run manager, events, attachments, model/runtime helpers
    graph/           # LangGraph graph builder, nodes, routing
    storage/         # PostgreSQL store, repositories, schema bootstrap
    prompt_context/  # context building and prompt rendering
    tool_runtime/    # tool registry, permissions, execution, approvals
    tool_modules/    # built-in tool implementations
    skills_forge/    # skill catalog and proposal workflow
    subagents/       # delegated task orchestration
frontend/
  app/               # Next.js App Router
  components/        # workbench UI components
  lib/               # frontend utilities, i18n, stream helpers
docs/
  architecture/      # architecture notes and design context
```

Runtime data is stored in PostgreSQL. Local secrets live in `backend/.env`; generated data, virtual environments, caches, and frontend build outputs should not be committed.

## Requirements

- Python 3.11+
- PostgreSQL 17+
- Go 1.25+ for the local shell runner
- Node.js 20+
- npm
- uv

## Quickstart

Run commands from the repository root unless a step says to `cd` elsewhere.

### 1. Check local tools

Install `uv` if it is missing:

```bash
python3 -m pip install uv
```

Use Node 20 for all frontend commands. This matters when an older `/usr/local/bin/node`
appears earlier in `PATH`:

```bash
export PATH="/opt/homebrew/opt/node@20/bin:$PATH"
node --version
npm --version
```

If `go` is not installed globally, install a project-local Go toolchain:

```bash
mkdir -p .bin/toolchains .tmp
curl -fL "https://go.dev/dl/go1.26.3.darwin-arm64.tar.gz" \
  -o .tmp/go1.26.3.darwin-arm64.tar.gz
rm -rf .bin/toolchains/go1.26.3 .bin/go
tar -C .bin/toolchains -xzf .tmp/go1.26.3.darwin-arm64.tar.gz
mv .bin/toolchains/go .bin/toolchains/go1.26.3
ln -s toolchains/go1.26.3 .bin/go
export PATH="$PWD/.bin/go/bin:$PATH"
go version
```

### 2. Start PostgreSQL

PostgreSQL only needs to be reachable on `127.0.0.1:5432`. If Homebrew works on
your machine, use:

```bash
brew services start postgresql@17
/opt/homebrew/opt/postgresql@17/bin/createdb tommy_agent 2>/dev/null || true
```

If Homebrew cannot start services, use whichever PostgreSQL installation is already
on your `PATH` and create the database there:

```bash
pg_isready -h 127.0.0.1 -p 5432
createdb -h 127.0.0.1 -p 5432 tommy_agent 2>/dev/null || true
```

### 3. Configure the backend

```bash
cd backend
test -f .env || cp .env.example .env
```

Edit `backend/.env` and set:

```dotenv
TOMMY_POSTGRES_DSN=dbname=tommy_agent
DEEPSEEK_API_KEY=your_key_here
# or another OpenAI-compatible provider key/base URL
```

### 4. Run the backend

Build and start the Go shell runner sidecar in a separate terminal for the fastest
local command execution path:

```bash
export PATH="$PWD/.bin/go/bin:$PATH"
cd runner
go build -o bin/tommy-runner ./cmd/tommy-runner
./bin/tommy-runner serve --addr 127.0.0.1:8765
```

Then start the backend in another terminal:

```bash
cd backend
uv sync --extra dev
set -a
source .env
set +a
TOMMY_GO_RUNNER_URL=http://127.0.0.1:8765 \
  .venv/bin/uvicorn app.agent_framework.server.app:app --reload --host 0.0.0.0 --port 8000
```

If `TOMMY_GO_RUNNER_URL` is not set, the backend still executes shell tools through the
Go runner CLI (`runner/bin/tommy-runner` when present, otherwise `go run`). Python no
longer executes model-requested shell commands directly.

### 5. Run the frontend

Start the frontend in a third terminal:

```bash
cd frontend
export PATH="/opt/homebrew/opt/node@20/bin:$PATH"
npm ci
npm run dev
```

The frontend proxies API requests to `http://127.0.0.1:8000` by default. To point it elsewhere:

```bash
NEXT_PUBLIC_AGENT_API_URL=http://127.0.0.1:8000 npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### 6. Verify the local app

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS -I http://127.0.0.1:3000
curl -fsS http://127.0.0.1:3000/agent-api/health
```

All three commands should succeed. Stop the runner, backend, and frontend terminals
with `Ctrl-C` when you are done.

## Development Commands

Backend:

```bash
cd backend
uv run pytest -q
uv run ruff check .
```

Frontend:

```bash
cd frontend
npm run typecheck
npm run lint
npm run e2e:desktop
```

## Safety Notes

- Do not commit `backend/.env`, `data/`, `.venv/`, `node_modules/`, `.next/`, or local caches.
- Do not publish real API keys, tokens, private network details, personal paths, or conversation records.
- Tool calls can touch local files or shell commands depending on configuration. Review approval settings before using Tommy with sensitive workspaces.
- PostgreSQL data may contain messages, tool outputs, memory proposals, run logs, and local paths.

## Roadmap

- Stronger production deployment story.
- More complete multilingual coverage across every secondary view.
- Deeper observability for run quality, memory quality, and tool safety.
- More granular subagent roles and skill lifecycle controls.

---

# Tommy Agent 中文

[English](#tommy-agent) | **中文**

Tommy Agent 是一个本地优先的 AI Agent 工作台，用于承载长对话、工具调用、审批、记忆、上下文管理、Skill 提案和运行状态检查。它由 LangGraph 运行时、FastAPI 后端、PostgreSQL 持久化和 Next.js 前端工作台组成。

> 项目状态：活跃产品原型。当前代码库重点优化本地开发体验、清晰模块边界和可持续迭代。

## 核心能力

- **LangGraph 运行时**：支持可控的 Agent 执行流程和流式状态更新。
- **FastAPI 服务**：提供会话、消息、运行、审批、记忆、提示词、Skill 和搜索接口。
- **PostgreSQL 持久化**：保存对话、运行事件、检查点、记忆、工具调用和 Skill 数据。
- **Next.js 工作台**：包含聊天、会话管理、运行状态、设置、审批、记忆和 Skill 面板。
- **人工审批流程**：敏感工具动作可以进入审批队列。
- **Context Pact 与记忆提案**：让长对话保持结构化、可检查、可确认。
- **模型服务可替换**：支持 DeepSeek、OpenRouter 或 OpenAI 兼容 API。
- **可选 Tavily 搜索工具**：用于启用联网搜索工具调用。
- **前端中英文切换**：工作台可在 English / 中文 之间切换。

## 架构

```text
backend/
  app/agent_framework/
    server/          # FastAPI app 与 API schema
    runtime/         # RunManager、事件、附件、模型与运行辅助模块
    graph/           # LangGraph 图构建、节点和路由
    storage/         # PostgreSQL store、仓储与 schema 初始化
    prompt_context/  # 上下文构建与提示词渲染
    tool_runtime/    # 工具注册、权限、执行与审批
    tool_modules/    # 内置工具实现
    skills_forge/    # Skill catalog 与提案工作流
    subagents/       # 子 Agent 委派任务编排
frontend/
  app/               # Next.js App Router
  components/        # 工作台 UI 组件
  lib/               # 前端工具、i18n、流式错误处理
docs/
  architecture/      # 架构说明与设计上下文
```

运行数据写入 PostgreSQL。本地密钥放在 `backend/.env`；生成数据、虚拟环境、缓存和前端构建产物不应提交。

## 环境要求

- Python 3.11+
- PostgreSQL 17+
- Go 1.25+，用于本地 shell runner
- Node.js 20+
- npm
- uv

## 快速开始

除非步骤里特别 `cd` 到子目录，否则都从仓库根目录执行。

### 1. 检查本地工具链

如果没有 `uv`，先安装：

```bash
python3 -m pip install uv
```

前端命令必须使用 Node 20。如果旧的 `/usr/local/bin/node` 排在 `PATH` 前面，
`npm run dev` 会误用旧 Node：

```bash
export PATH="/opt/homebrew/opt/node@20/bin:$PATH"
node --version
npm --version
```

如果没有全局 `go`，可以安装项目本地 Go 工具链：

```bash
mkdir -p .bin/toolchains .tmp
curl -fL "https://go.dev/dl/go1.26.3.darwin-arm64.tar.gz" \
  -o .tmp/go1.26.3.darwin-arm64.tar.gz
rm -rf .bin/toolchains/go1.26.3 .bin/go
tar -C .bin/toolchains -xzf .tmp/go1.26.3.darwin-arm64.tar.gz
mv .bin/toolchains/go .bin/toolchains/go1.26.3
ln -s toolchains/go1.26.3 .bin/go
export PATH="$PWD/.bin/go/bin:$PATH"
go version
```

### 2. 启动 PostgreSQL

PostgreSQL 只需要能在 `127.0.0.1:5432` 访问。如果本机 Homebrew 可用：

```bash
brew services start postgresql@17
/opt/homebrew/opt/postgresql@17/bin/createdb tommy_agent 2>/dev/null || true
```

如果 Homebrew services 因系统版本等原因不可用，使用当前 `PATH` 上已有的 PostgreSQL：

```bash
pg_isready -h 127.0.0.1 -p 5432
createdb -h 127.0.0.1 -p 5432 tommy_agent 2>/dev/null || true
```

### 3. 配置后端

```bash
cd backend
test -f .env || cp .env.example .env
```

编辑 `backend/.env`，至少确认：

```dotenv
TOMMY_POSTGRES_DSN=dbname=tommy_agent
DEEPSEEK_API_KEY=your_key_here
# 或其他 OpenAI 兼容模型服务的 key/base URL
```

### 4. 启动后端

为了获得最快的本地命令执行路径，先在另一个终端构建并启动 Go shell runner：

```bash
export PATH="$PWD/.bin/go/bin:$PATH"
cd runner
go build -o bin/tommy-runner ./cmd/tommy-runner
./bin/tommy-runner serve --addr 127.0.0.1:8765
```

再在另一个终端启动后端：

```bash
cd backend
uv sync --extra dev
set -a
source .env
set +a
TOMMY_GO_RUNNER_URL=http://127.0.0.1:8765 \
  .venv/bin/uvicorn app.agent_framework.server.app:app --reload --host 0.0.0.0 --port 8000
```

如果没有设置 `TOMMY_GO_RUNNER_URL`，后端仍会通过 Go runner CLI 执行 shell 工具
（优先使用 `runner/bin/tommy-runner`，否则使用 `go run`）。Python 不再直接执行模型请求的
shell 命令。

### 5. 启动前端

第三个终端启动前端：

```bash
cd frontend
export PATH="/opt/homebrew/opt/node@20/bin:$PATH"
npm ci
npm run dev
```

前端默认代理到 `http://127.0.0.1:8000`。如果后端地址不同：

```bash
NEXT_PUBLIC_AGENT_API_URL=http://127.0.0.1:8000 npm run dev
```

打开 [http://localhost:3000](http://localhost:3000)。

### 6. 验证本地服务

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS -I http://127.0.0.1:3000
curl -fsS http://127.0.0.1:3000/agent-api/health
```

三个命令都应该成功。用完后，在 runner、backend、frontend 三个终端里按
`Ctrl-C` 关闭服务。

## 开发命令

后端：

```bash
cd backend
uv run pytest -q
uv run ruff check .
```

前端：

```bash
cd frontend
npm run typecheck
npm run lint
npm run e2e:desktop
```

## 安全说明

- 不要提交 `backend/.env`、`data/`、`.venv/`、`node_modules/`、`.next/` 或本地缓存。
- 不要发布真实 API key、访问令牌、私有网络信息、个人路径或对话记录。
- 工具调用可能访问本地文件或执行 shell 命令，具体取决于配置。处理敏感工作区前请先检查审批设置。
- PostgreSQL 数据可能包含消息、工具输出、记忆提案、运行日志和本地路径。

## 路线图

- 更完整的生产部署方案。
- 覆盖所有二级视图的多语言文案。
- 更深入的运行质量、记忆质量和工具安全观测能力。
- 更细粒度的子 Agent 角色与 Skill 生命周期控制。
