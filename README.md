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

## Quickstart

### 1. Start PostgreSQL

```bash
brew services start postgresql@17
/opt/homebrew/opt/postgresql@17/bin/createdb tommy_agent
```

If the service is already running, Homebrew will say so. Use `brew services restart postgresql@17` only when you need a restart.

### 2. Configure the backend

```bash
cd backend
cp .env.example .env
```

Edit `backend/.env` and set:

```dotenv
TOMMY_POSTGRES_DSN=dbname=tommy_agent
DEEPSEEK_API_KEY=your_key_here
# or another OpenAI-compatible provider key/base URL
```

### 3. Run the backend

Build and start the Go shell runner sidecar in a separate terminal for the fastest
local command execution path:

```bash
cd runner
go build -o bin/tommy-runner ./cmd/tommy-runner
./bin/tommy-runner serve --addr 127.0.0.1:8765
```

```bash
cd backend
uv sync
TOMMY_GO_RUNNER_URL=http://127.0.0.1:8765 \
  uv run uvicorn app.agent_framework.server.app:app --reload --host 0.0.0.0 --port 8000
```

If `TOMMY_GO_RUNNER_URL` is not set, the backend still executes shell tools through the
Go runner CLI (`runner/bin/tommy-runner` when present, otherwise `go run`). Python no
longer executes model-requested shell commands directly.

### 4. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend proxies API requests to `http://127.0.0.1:8000` by default. To point it elsewhere:

```bash
NEXT_PUBLIC_AGENT_API_URL=http://127.0.0.1:8000 npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

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

## 快速开始

### 1. 启动 PostgreSQL

```bash
brew services start postgresql@17
/opt/homebrew/opt/postgresql@17/bin/createdb tommy_agent
```

如果服务已经启动，Homebrew 会提示已启动。只有需要重启时才使用 `brew services restart postgresql@17`。

### 2. 配置后端

```bash
cd backend
cp .env.example .env
```

编辑 `backend/.env`，至少确认：

```dotenv
TOMMY_POSTGRES_DSN=dbname=tommy_agent
DEEPSEEK_API_KEY=your_key_here
# 或其他 OpenAI 兼容模型服务的 key/base URL
```

### 3. 启动后端

为了获得最快的本地命令执行路径，先在另一个终端构建并启动 Go shell runner：

```bash
cd runner
go build -o bin/tommy-runner ./cmd/tommy-runner
./bin/tommy-runner serve --addr 127.0.0.1:8765
```

```bash
cd backend
uv sync
TOMMY_GO_RUNNER_URL=http://127.0.0.1:8765 \
  uv run uvicorn app.agent_framework.server.app:app --reload --host 0.0.0.0 --port 8000
```

如果没有设置 `TOMMY_GO_RUNNER_URL`，后端仍会通过 Go runner CLI 执行 shell 工具
（优先使用 `runner/bin/tommy-runner`，否则使用 `go run`）。Python 不再直接执行模型请求的
shell 命令。

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端默认代理到 `http://127.0.0.1:8000`。如果后端地址不同：

```bash
NEXT_PUBLIC_AGENT_API_URL=http://127.0.0.1:8000 npm run dev
```

打开 [http://localhost:3000](http://localhost:3000)。

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
