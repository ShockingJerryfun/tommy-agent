# Child Run Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make delegated child-agent execution resolve real `AgentDefinition` files, inherit immutable runtime context, and pass through `ChildRunService` as the single child-run chokepoint.

**Architecture:** Add a frozen `ChildRunContext` as the canonical lineage/constraint DTO, an `AgentDefinitionResolver` for built-in/data/workspace precedence, and a `ChildRunService` that owns definition resolution, scoped registry construction, recursion guard, persistence, production runner invocation, and structured failure results. Keep `SubagentDelegator` as a compatibility adapter and make `WorkerPool`, Team, and Workflow pass context rather than re-resolve definitions.

**Tech Stack:** Python 3.11 dataclasses, existing pytest tests with injected fake runners, existing `PostgresAgentStore` repositories, existing `ToolRegistry` and subagent runner callable contract.

---

### Task 1: ChildRunContext

**Files:**
- Create: `backend/app/agent_framework/workers/context.py`
- Test: `backend/tests/subagents/test_child_run_context.py`

- [ ] **Step 1: Write failing tests** covering working directory inheritance from `parent_metadata["frontend_settings"]["workingDirectory"]`, command scope inheritance, rejection of unrestricted widening, rejection of permission widening, depth increment, lineage metadata inclusion, and exclusion of `approval_id` from model-visible lineage.
- [ ] **Step 2: Run red tests**

```bash
cd backend
uv run pytest -q tests/subagents/test_child_run_context.py
```

Expected: import failure for `app.agent_framework.workers.context`.

- [ ] **Step 3: Implement minimal context module** with frozen `ChildRunContext`, `derive_child_context`, `as_metadata`, `lineage_metadata`, allow-listed metadata copying, depth increment, and narrowing helpers for command scope and permission mode.
- [ ] **Step 4: Run green tests**

```bash
cd backend
uv run pytest -q tests/subagents/test_child_run_context.py
```

Expected: all new context tests pass.

### Task 2: AgentDefinitionResolver

**Files:**
- Create: `backend/app/agent_framework/agents/resolver.py`
- Modify: `backend/app/agent_framework/agents/__init__.py`
- Test: `backend/tests/subagents/test_agent_definition_resolver.py`
- Update: `backend/tests/subagents/test_agent_definitions.py`

- [ ] **Step 1: Write failing tests** for built-in fallback, `data/{agent_id}/agents/*.md` override, workspace override wins, unknown role `KeyError`, unknown tool `ValueError`, `disallowed_tools` removal, and workspace reviewer override.
- [ ] **Step 2: Run red tests**

```bash
cd backend
uv run pytest -q tests/subagents/test_agent_definition_resolver.py tests/subagents/test_agent_definitions.py
```

Expected: import failure for `AgentDefinitionResolver`.

- [ ] **Step 3: Implement resolver** using existing loader/registry, precedence built-ins -> data -> workspace, default known-tool set from current default registry, and exports.
- [ ] **Step 4: Run green tests**

```bash
cd backend
uv run pytest -q tests/subagents/test_agent_definition_resolver.py tests/subagents/test_agent_definitions.py
```

Expected: resolver and existing loader tests pass.

### Task 3: Context-Aware Roles

**Files:**
- Modify: `backend/app/agent_framework/subagents/roles.py`
- Modify: `backend/app/agent_framework/subagents/__init__.py`
- Test: update `backend/tests/subagents/test_subagents.py`

- [ ] **Step 1: Write failing tests** that built-in researcher still works, workspace `.tommy/agents/reviewer.md` affects `registry_for_role("reviewer", child_context=...)`, disallowed tools are removed, and unknown tools fail validation.
- [ ] **Step 2: Run red role tests**

```bash
cd backend
uv run pytest -q tests/subagents/test_subagents.py tests/subagents/test_agent_definition_resolver.py
```

Expected: `registry_for_role` lacks context-aware parameters.

- [ ] **Step 3: Implement `resolve_role` and extend `registry_for_role`** to use `ChildRunContext.working_directory`, preserve model/permission/budget metadata, and build registries only from validated definitions.
- [ ] **Step 4: Run green role tests**

```bash
cd backend
uv run pytest -q tests/subagents/test_subagents.py tests/subagents/test_agent_definition_resolver.py
```

Expected: existing and new role tests pass.

### Task 4: ChildRunService Chokepoint

**Files:**
- Create: `backend/app/agent_framework/workers/child_run_service.py`
- Modify: `backend/app/agent_framework/workers/__init__.py`
- Test: `backend/tests/subagents/test_child_run_service.py`

- [ ] **Step 1: Write failing tests** for fake runner result creation, workspace role override appearing in prompt, recursion guard removing team/workflow tools, lineage metadata persistence, structured failure storage, and stop short-circuit.
- [ ] **Step 2: Run red service tests**

```bash
cd backend
uv run pytest -q tests/subagents/test_child_run_service.py
```

Expected: import failure for `ChildRunService`.

- [ ] **Step 3: Implement `ChildRunRequest` and `ChildRunService.run`** to resolve roles once, create child session, create/update `subagent_runs`, call the existing runner path, score responses, persist metadata, and return `WorkerResult`.
- [ ] **Step 4: Run green service tests**

```bash
cd backend
uv run pytest -q tests/subagents/test_child_run_service.py
```

Expected: all service tests pass without live LLM calls.

### Task 5: SubagentDelegator Compatibility Adapter

**Files:**
- Modify: `backend/app/agent_framework/subagents/delegate.py`
- Update: `backend/tests/subagents/test_subagents.py`

- [ ] **Step 1: Write or update tests** proving existing dispatch API still creates child sessions, records rows, handles failures, and short-circuits stops, while optional `child_context` and `parent_metadata` flow into the service.
- [ ] **Step 2: Run red compatibility tests**

```bash
cd backend
uv run pytest -q tests/subagents/test_subagents.py
```

Expected before implementation: new context-flow assertion fails.

- [ ] **Step 3: Refactor `dispatch`** to derive or accept `ChildRunContext`, call `ChildRunService.run`, and convert `WorkerResult` to `SubagentResult`.
- [ ] **Step 4: Run green compatibility tests**

```bash
cd backend
uv run pytest -q tests/subagents/test_subagents.py
```

Expected: existing merger/delegator behavior remains compatible.

### Task 6: WorkerPool, Team, And Workflow Forwarding

**Files:**
- Modify: `backend/app/agent_framework/workers/types.py`
- Modify: `backend/app/agent_framework/workers/pool.py`
- Modify: `backend/app/agent_framework/teams/service.py`
- Modify: `backend/app/agent_framework/workflows/runtime.py`
- Update: `backend/tests/subagents/test_worker_pool.py`
- Update: `backend/tests/subagents/test_agent_teams.py`
- Update: `backend/tests/subagents/test_workflows.py`
- Update: `backend/tests/subagents/test_multi_agent_tools.py`

- [ ] **Step 1: Write failing tests** that `WorkerTask` carries `child_context` and `approval_id`, WorkerPool passes supplied contexts unchanged, Team tasks include `team_id`/`team_task_id`, and Workflow tasks include `workflow_run_id`/`phase_run_id`/`workflow_phase_id`.
- [ ] **Step 2: Run red tests**

```bash
cd backend
uv run pytest -q tests/subagents/test_worker_pool.py tests/subagents/test_agent_teams.py tests/subagents/test_workflows.py tests/subagents/test_multi_agent_tools.py
```

Expected: context fields are absent or not forwarded.

- [ ] **Step 3: Implement forwarding** without adding team planning, workflow resume, UI, or background queues.
- [ ] **Step 4: Run green tests**

```bash
cd backend
uv run pytest -q tests/subagents/test_worker_pool.py tests/subagents/test_agent_teams.py tests/subagents/test_workflows.py tests/subagents/test_multi_agent_tools.py
```

Expected: existing MVP tests and new context assertions pass.

### Task 7: Verification

**Files:**
- All touched backend modules and tests.

- [ ] **Step 1: Run focused suites**

```bash
cd backend
uv run pytest -q tests/subagents
uv run pytest -q tests/prompt_context
uv run ruff check .
```

Expected: all pass.

- [ ] **Step 2: Run full backend suite if feasible**

```bash
cd backend
uv run pytest -q
```

Expected: full suite passes or any pre-existing/environmental failure is documented with exact output.

### Task 8: Runtime Context Inheritance Closure

**Files:**
- Modify: `backend/app/agent_framework/workers/context.py`
- Modify: `backend/app/agent_framework/workers/types.py`
- Modify: `backend/app/agent_framework/workers/child_run_service.py`
- Modify: `backend/app/agent_framework/workers/pool.py`
- Modify: `backend/app/agent_framework/subagents/delegate.py`
- Modify: `backend/app/agent_framework/subagents/merger.py`
- Modify: `backend/app/agent_framework/subagents/orchestrator.py`
- Modify: `backend/app/agent_framework/tool_modules/collaboration.py`
- Modify: `backend/app/agent_framework/teams/service.py`
- Modify: `backend/app/agent_framework/workflows/runtime.py`
- Test: `backend/tests/subagents/test_child_run_context.py`
- Test: `backend/tests/subagents/test_child_run_service.py`
- Test: `backend/tests/subagents/test_worker_pool.py`
- Test: `backend/tests/subagents/test_subagents.py`
- Test: `backend/tests/subagents/test_agent_teams.py`
- Test: `backend/tests/subagents/test_workflows.py`
- Test: `backend/tests/subagents/test_multi_agent_tools.py`

- [ ] **Step 1: Write failing DT tests**

Add targeted pytest cases before production code for:

- `parent_metadata_from_runtime_context()` preserving runtime aliases, frontend settings, approval id, working directory, command scope, model, permission mode, budget, depth, team, and workflow lineage.
- `merge_child_parent_metadata()` preserving existing fields while applying parent patches without dropping aliases.
- `run_delegate_task(..., parent_metadata=...)` and `BestOfNMerger.run(..., parent_metadata=...)` forwarding workspace metadata so `.tommy/agents/reviewer.md` overrides are used.
- `ChildRunRequest.task_id` causing `WorkerResult.task_id` to remain the original worker task id while `subagent_id` remains the persisted `subagent_runs.id`.
- `WorkerPool(store=..., runner=None, delegator=None)` calling `ChildRunService` directly and preserving `WorkerTask.id`; explicit delegator and fake runner paths remain compatible.
- `TeamService` and `WorkflowRuntime` merging parent runtime metadata into worker task metadata, allowing workspace agent overrides and persisting lineage plus `working_directory`/`command_scope`.
- Child registries excluding `create_agent_team`, `run_agent_team`, `get_agent_team_status`, `run_agent_workflow`, `get_agent_workflow_status`, and `create_agent_workflow` even when workspace agents list those tools.
- Permission tests using “narrows” naming and future permission modes ranked conservatively.

- [ ] **Step 2: Run red DT tests**

```bash
cd backend
uv run pytest -q \
  tests/subagents/test_child_run_context.py \
  tests/subagents/test_child_run_service.py \
  tests/subagents/test_worker_pool.py \
  tests/subagents/test_subagents.py \
  tests/subagents/test_agent_teams.py \
  tests/subagents/test_workflows.py \
  tests/subagents/test_multi_agent_tools.py
```

Expected: failures in the new assertions because parent metadata helpers, direct WorkerPool `ChildRunService` default, original task id preservation, and Team/Workflow parent metadata propagation are not yet implemented.

- [ ] **Step 3: Implement metadata normalization and forwarding**

Add `parent_metadata_from_runtime_context()` and `merge_child_parent_metadata()` in `workers/context.py`. Normalize aliases without dropping originals, derive effective workspace from `frontend_settings.workingDirectory`/`workingDirectory`/`working_directory`, derive effective command scope from `commandScope`/`command_scope`, and keep approval id in metadata only. Extend `run_delegate_task()`, `BestOfNMerger.run()`, `SubagentDelegator.dispatch()`, `create_agent_team()`, and `run_agent_workflow()` to pass this parent metadata.

- [ ] **Step 4: Implement child-run execution closure**

Extend `ChildRunRequest` with `task_id`, return `WorkerResult.task_id = request.task_id or subagent_run_id`, and pass `WorkerTask.id` when `WorkerPool` calls `ChildRunService` directly. Refactor `WorkerPool` so custom runner wins, explicit delegator remains compatible, and no-runner/no-explicit-delegator uses `ChildRunService(store).run(...)`.

- [ ] **Step 5: Implement Team and Workflow metadata propagation**

Merge team/task metadata with parent metadata using the helper before constructing `WorkerTask`. Extend `WorkflowRuntime.run(..., parent_metadata=None)` and merge workflow lineage into each worker task. Preserve existing lineage fields and avoid permission or command scope widening by relying on `derive_child_context()`.

- [ ] **Step 6: Run green DT tests**

```bash
cd backend
uv run pytest -q \
  tests/subagents/test_child_run_context.py \
  tests/subagents/test_child_run_service.py \
  tests/subagents/test_worker_pool.py \
  tests/subagents/test_subagents.py \
  tests/subagents/test_agent_teams.py \
  tests/subagents/test_workflows.py \
  tests/subagents/test_multi_agent_tools.py
```

Expected: all targeted context inheritance closure tests pass without live LLM calls.

- [ ] **Step 7: Run required verification**

```bash
cd backend
uv run pytest -q tests/subagents
uv run pytest -q tests/prompt_context
uv run ruff check .
```

Expected: all required checks pass, or exact failures are documented.
