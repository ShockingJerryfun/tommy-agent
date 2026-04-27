# Tommy Agent

Tommy Agent 是一个本地优先的 Agent 工作台示例项目，后端基于 FastAPI、LangGraph 和 PostgreSQL，前端基于 Next.js 和 React。它提供流式对话、工具调用审批、会话状态、长期记忆提案、Context Pact、Skill 提案和运行过程检查面板。

## 2026.4.26: Agent练习项目 Vibe 7 小时出的，勿喷。。。慢慢加功能

## 功能

- LangGraph 驱动的 Agent 运行时，支持流式事件输出。
- FastAPI 后端，提供会话、消息、审批、记忆、Skill 和压缩接口。
- Next.js 前端，包含聊天界面、运行图、工具结果、审批队列和设置面板。
- PostgreSQL 持久化，用于会话、检查点、记忆和运行事件。
- 可配置 DeepSeek、OpenRouter 或 OpenAI 兼容模型。
- Tavily Web Search 工具可选启用。

## 项目结构

```text
backend/
  app/agent_framework/   # Agent 运行时、API、工具、记忆和审批逻辑
  .env.example           # 环境变量模板
frontend/
  app/                   # Next.js App Router
  components/            # 前端工作台组件
examples/
  quickstart.py          # 命令行快速启动示例
```

运行时数据会写入 `data/`，本地密钥放在 `backend/.env`。这些文件已经在 `.gitignore` 中排除，不应该提交到公开仓库。

## 环境要求

- Python 3.11+
- PostgreSQL 17+
- Node.js 20+
- npm

## 后端启动

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

确保 PostgreSQL 服务已启动，并创建本地数据库：

```bash
brew services start postgresql@17
/opt/homebrew/opt/postgresql@17/bin/createdb tommy_agent
```

编辑 `backend/.env`，填入你自己的模型服务密钥，并确认 `TOMMY_POSTGRES_DSN=dbname=tommy_agent`。然后加载环境变量并启动 API：

```bash
set -a
source .env
set +a
uvicorn app.agent_framework.api:app --reload --host 127.0.0.1 --port 8000
```

## 前端启动

```bash
cd frontend
npm install
npm run dev
```

默认前端会通过 Next.js API route 代理到 `http://127.0.0.1:8000`。如果后端地址不同，可以设置 `AGENT_API_URL`：

```bash
AGENT_API_URL=http://127.0.0.1:8000 npm run dev
```

## 命令行示例

```bash
python examples/quickstart.py
```

运行前请确保后端依赖已安装，并且当前 Shell 已加载必要的模型 API 环境变量。

## 安全说明

- 不要提交 `backend/.env`、`data/`、`.venv/`、`node_modules/`、`.next/` 或任何本地缓存。
- 不要把真实 API key、访问令牌、私有 IP、个人路径或会话记录写入公开仓库。
- `data/` 中可能包含聊天记录、工具调用、记忆和本地路径，发布前应始终保持忽略。
