# Production Multi-Agent Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Tommy Agent's backend multi-agent runtime so teams and workflows are persistent, queryable, cancellable, background-enqueued, evented, and bounded in prompt context.

**Architecture:** Use `docs/architecture/multi-agent-runtime.md` as the DT source of truth. Promote queryable state into first-class tables and columns, keep `ChildRunService` as the only default child execution path, run team/workflow execution through `BackgroundRunQueue`, and persist progress through `EventBridge`.

**Tech Stack:** Python 3.11, PostgreSQL via psycopg, existing repository pattern, pytest, pytest-asyncio, Ruff.

---

### Task 1: Runtime Persistence and Repositories

**Files:**
- Create: `backend/app/agent_framework/storage/schema/versions/v0006_production_multi_agent.py`
- Modify: `backend/app/agent_framework/storage/schema/registry.py`
- Modify: `backend/app/agent_framework/storage/schema/runner.py`
- Modify: `backend/app/agent_framework/storage/store.py`
- Modify: `backend/app/agent_framework/storage/repos/subagent_runs.py`
- Modify: `backend/app/agent_framework/storage/repos/agent_teams.py`
- Modify: `backend/app/agent_framework/storage/repos/workflows.py`
- Create: `backend/app/agent_framework/storage/repos/artifacts.py`
- Create tests under `backend/tests/storage/` and `backend/tests/subagents/`

- [ ] Write failing tests that query explicit lineage columns and artifacts without parsing metadata.
- [ ] Add additive schema columns/tables/indexes for production runtime lineage.
- [ ] Add repository methods for team runs, messages, artifacts, workflow status, and cleanup hooks.
- [ ] Run focused storage and subagent lineage tests.

### Task 2: Background Queue and Events

**Files:**
- Create: `backend/app/agent_framework/runtime/background_tasks.py`
- Create: `backend/app/agent_framework/runtime/event_bridge.py`
- Modify: `backend/app/agent_framework/runtime/__init__.py`
- Create tests under `backend/tests/runtime/`

- [ ] Write failing tests for background success, failure, cancellation, orphan interruption, and event order.
- [ ] Implement `BackgroundRunQueue` with persisted status callbacks and cancellation tokens.
- [ ] Implement `EventBridge` using existing run events with team/workflow payload fields.
- [ ] Run focused runtime tests.

### Task 3: Team Runtime and Tools

**Files:**
- Create: `backend/app/agent_framework/teams/runtime.py`
- Create or modify: `backend/app/agent_framework/teams/planner.py`
- Modify: `backend/app/agent_framework/teams/task_board.py`
- Modify: `backend/app/agent_framework/teams/mailbox.py`
- Modify: `backend/app/agent_framework/tool_modules/collaboration.py`
- Modify: `backend/app/agent_framework/tool_runtime/permissions.yaml`
- Create tests under `backend/tests/teams/` and update `backend/tests/subagents/`

- [ ] Write failing tests for planning, dependency order, parallel ready tasks, mailbox injection, final synthesis, enqueue/status/cancel tools, approval, and recursion guard.
- [ ] Implement `TeamRuntime` on `WorkerPool`/`ChildRunService`.
- [ ] Add read/status/cancel tools and permission entries.
- [ ] Run focused team and subagent tool tests.

### Task 4: Workflow Runtime and Tools

**Files:**
- Create: `backend/app/agent_framework/workflows/phase_runner.py`
- Create: `backend/app/agent_framework/workflows/cache.py`
- Modify: `backend/app/agent_framework/workflows/runtime.py`
- Modify: `backend/app/agent_framework/tool_modules/collaboration.py`
- Modify: `backend/app/agent_framework/tool_runtime/permissions.yaml`
- Create tests under `backend/tests/workflows/`

- [ ] Write failing tests for enqueue/status/cancel, timeout, failed worker, persisted phase/worker status, no sync async-thread bridge, and cache hooks where implemented.
- [ ] Move workflow execution behind `BackgroundRunQueue`.
- [ ] Add `PhaseRunner`, timeout/cancellation checks, status APIs, and rerun failed phase support if feasible.
- [ ] Run focused workflow tests.

### Task 5: Prompt Context and Cleanup

**Files:**
- Create: `backend/app/agent_framework/prompt_context/team_sections.py`
- Create: `backend/app/agent_framework/prompt_context/workflow_sections.py`
- Modify: `backend/app/agent_framework/prompt_context/builder.py`
- Modify: storage repositories for cleanup hooks
- Create/update tests under `backend/tests/prompt_context/` and `backend/tests/storage/`

- [ ] Write failing tests for bounded team/workflow prompt sections and no transcript leakage.
- [ ] Add bounded prompt sections only when relevant.
- [ ] Add deterministic cleanup/retention repository methods.
- [ ] Run focused prompt context and storage cleanup tests.

### Task 6: Verification and Acceptance Review

**Files:**
- Update tests as needed under `backend/tests/`

- [ ] Run `cd backend && uv run pytest -q tests/subagents tests/prompt_context`.
- [ ] Run focused new tests under `tests/runtime`, `tests/teams`, `tests/workflows`, and `tests/storage`.
- [ ] Run `cd backend && uv run ruff check .`.
- [ ] Run `cd backend && uv run pytest -q` if feasible.
- [ ] Review every DT acceptance criterion and report pass/fail with evidence.
