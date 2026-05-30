# Multi-Agent Runtime

This document describes Tommy's production foundation for externalized agents,
bounded worker execution, lead-controlled teams, declarative workflows, and
inspectable multi-agent runtime state.

## Production Runtime DT: 2026-05-30

This DT is the source of truth for the production multi-agent backend runtime.
Implementation, tests, and acceptance criteria must map back to these
requirements.

### Runtime Model

Multi-agent runtime state must be queryable through explicit database columns
and tables. JSON metadata is allowed only for backward compatibility,
debug-only details, or auxiliary non-queryable context.

Queryable state includes:

- parent and child run lineage: `parent_run_id`, `child_session_id`,
  `child_run_id`, `subagent_run_id`
- agent/team/workflow lineage: `role_id`, `agent_definition_id`, `team_id`,
  `team_run_id`, `team_task_id`, `workflow_run_id`, `phase_run_id`,
  `workflow_phase_id`, `worker_run_id`
- approvals and execution status: `approval_id`, `status`, `started_at`,
  `finished_at`, `error_type`, `error_message`
- cross-boundary references: artifact ids, event ids, cache key, and input hash

`ChildRunService` is the canonical child execution path. `SubagentDelegator`
remains a compatibility adapter. Team and workflow workers must schedule
through `WorkerPool`, which defaults to `ChildRunService`.

### Persistence

The database must model team executions separately from team definitions:

- `agent_teams` stores team definitions.
- `agent_team_runs` stores a specific execution of a team definition, including
  `team_id`, parent lineage, approval, status, goal, summary, timestamps, and
  auxiliary metadata.
- `agent_team_tasks` stores task board state and links to the active team run
  when tasks execute.
- `agent_team_messages` stores bounded mailbox messages.

`subagent_runs` must expose production lineage columns for roles, agent
definitions, team/workflow linkage, approvals, status, errors, and timestamps.
Existing metadata fields may mirror these values for compatibility, but must
not be the primary query path.

`workflow_runs`, `workflow_phase_runs`, and `workflow_worker_runs` must persist
status and lineage. `workflow_worker_runs.subagent_run_id` is the canonical
reference to the child execution. Worker output stored on worker rows must be
bounded.

Large cross-boundary outputs belong in `artifacts`, with explicit owner fields,
artifact kind, URI/path/hash/size, summary, and creation time. Parent prompts
must receive artifact references and bounded summaries, not full transcripts.

### Background Queue

Team and workflow tool calls must enqueue execution and return immediately with
compact handles. `BackgroundRunQueue` owns in-process asyncio task tracking,
persists status, supports status reads, cancellation, active listing, and
restart orphan handling. Cancellation must be visible to team and workflow
runtimes before scheduling future work.

### Event Bridge

Team, workflow, worker, phase, and background cancellation progress must be
persisted as run events compatible with the existing event style. Events must be
queryable by parent run through `run_events.run_id` and by `team_run_id` or
`workflow_run_id` through event payload fields.

### Team Runtime

`create_agent_team` creates a team definition and optional initial tasks. It
does not synchronously run the team.

`run_agent_team` starts an `agent_team_runs` execution and enqueues
`TeamRuntime`. If no tasks exist, the lead planner creates schema-validated
tasks from the goal, with a hard maximum task count. Ready tasks execute through
`WorkerPool` in dependency order. Independent ready tasks may run in parallel.
Workers receive bounded team context: assigned task, task board summary, latest
mailbox messages, and role constraints. Lead synthesis runs after task
execution and stores a bounded final summary.

Child agents must not be able to spawn teams or workflows.

### Workflow Runtime

`run_agent_workflow` validates a declarative workflow spec, persists a
`workflow_run`, enqueues execution, and returns immediately. Workflow execution
must not use a synchronous async-thread bridge.

`WorkflowRuntime` is executed by `BackgroundRunQueue` and delegates phase work
to `PhaseRunner`. The runtime enforces max worker count, max wall seconds,
phase timeout, and available worker timeout. Cancellation must be honored
between phases and before scheduling workers. Progress events and phase/worker
statuses must be persisted.

Worker cache keys may skip deterministic duplicate work when they include role,
prompt/input, workflow spec identity/version, and agent definition version or
prompt hash. Cache hits must be recorded explicitly.

### Prompt Context

Prompt context may include bounded sections only when relevant:

- `active_team_role`
- `team_task_board`
- `team_mailbox`
- `workflow_phase_context`
- `child_constraints`
- `parent_multi_agent_summary`

No full child transcript may be injected into parent, team, or workflow
prompts. Prompt snapshots must make these bounded sections inspectable.

### Tools and Permissions

Required tools:

- `create_agent_team`
- `run_agent_team`
- `get_agent_team_status`
- `cancel_agent_team_run`
- `run_agent_workflow`
- `get_agent_workflow_status`
- `cancel_agent_workflow_run`
- `rerun_failed_workflow_phase`

Run and cancellation tools require approval. Status tools are read-only and do
not require approval. Child registries must exclude team/workflow creation,
execution, status, cancellation, and rerun tools.

### Retention

The storage layer must expose deterministic cleanup hooks for old completed
child runs, large child outputs, orphan artifacts, and interrupted background
jobs. A scheduler is optional; repository methods and tests are required.

### Test Requirements

Tests must avoid live LLM calls and use fake planners, fake workers, or
deterministic services. Coverage must include DB lineage columns, artifacts,
background queue success/failure/cancellation/orphans, event ordering, team
planning/dependencies/parallel execution/synthesis/status/cancel, mailbox
injection, child registry recursion guards, workflow enqueue/status/timeout/
cancellation/failure/cache where implemented, bounded parent context, no
transcript leakage, approval behavior, and existing `delegate_task` behavior.

## AgentDefinition

`AgentDefinition` lives under `backend/app/agent_framework/agents/`. It is the
source of truth for reusable child-agent personas:

- `id`, `title`, `description`
- `system_prompt`
- `tool_names` and `disallowed_tool_names`
- `max_turns`, `max_wall_seconds`
- optional `model`, `permission_mode`, and `metadata`

Built-ins cover the existing `researcher`, `analyst`, and `writer` roles plus
`architect`, `reviewer`, `tester`, `explorer`, and `implementer`.

The existing `SubagentRole` API remains as a compatibility DTO. Calls such as
`list_role_ids()`, `get_role()`, `role_registry()`, and `registry_for_role()`
now derive their data from `AgentDefinition` while preserving scoped tool
registries.

## External Agent Files

Workspace agents can be added with `.tommy/agents/*.md`:

```markdown
---
id: reviewer
title: Reviewer
description: Reviews code for correctness and regressions.
tools:
  - list_workspace
  - read_workspace_file
disallowed_tools:
  - write_local_file
max_turns: 8
max_wall_seconds: 180
permission_mode: read_only
---
You are a strict reviewer.
```

Loader order is:

1. built-ins
2. `data/agents/{agent_id}/agents/*.md`
3. workspace `.tommy/agents/*.md`

Later definitions override earlier definitions by `id`. Disallowed tools are
removed from the final allowlist.

## WorkerPool

`WorkerPool` lives under `backend/app/agent_framework/workers/`. It is the
shared execution primitive for teams and workflows.

Properties:

- bounded concurrency with `asyncio.Semaphore`
- input-order result preservation
- injectable sync or async fake runners for tests
- default execution through `SubagentDelegator`
- stopped parent runs short-circuit before child execution
- worker failures become structured `WorkerResult(status="failed")`

Worker results carry bounded final responses and references such as
`subagent_id` and `child_session_id`; parent prompts do not receive raw child
transcripts.

## Team Runtime MVP

`TeamService` lives under `backend/app/agent_framework/teams/`.

The MVP is lead-controlled:

- callers create teams and tasks explicitly
- `run_team()` dispatches queued tasks through `WorkerPool`
- tasks are assigned by role/member
- results are stored on `agent_team_tasks`
- `team_summary_section()` returns compact Team Results for prompt injection

There are no autonomous peer-to-peer loops in this version.

## Workflow Runtime MVP

`WorkflowRuntime` lives under `backend/app/agent_framework/workflows/`.

Workflow YAML is declarative only. Tommy does not execute arbitrary Python,
JavaScript, shell scripts, or model-generated code from workflow specs.

Example workflow YAML:

```yaml
id: repo_test_gap_audit
name: Repository Test Gap Audit
description: Audit modules for missing tests.
max_concurrency: 4
budget:
  max_workers: 20
  max_wall_seconds: 900
inputs:
  modules:
    - backend/app/agent_framework/graph
    - backend/app/agent_framework/subagents
phases:
  - id: inspect_modules
    kind: fanout
    agent: explorer
    input: inputs.modules
    prompt: |
      Inspect this module for missing tests and risky branches:
      {{ item }}
  - id: synthesize
    kind: reduce
    agent: architect
    input: phases.inspect_modules.outputs
    prompt: |
      Produce a prioritized implementation plan from these findings:
      {{ item }}
```

Supported phase kinds:

- `single`
- `fanout`
- `map`
- `reduce`

Template support is intentionally small: `{{ item }}` and `{{ inputs.foo }}`.
Reduce phases join prior outputs into bounded summaries before sending one
worker task to the reducer agent.

## Persistence

The additive schema version `v0005_multi_agent` adds:

- `agent_teams`
- `agent_team_members`
- `agent_team_tasks`
- `agent_team_messages`
- `workflow_specs`
- `workflow_runs`
- `workflow_phase_runs`
- `workflow_worker_runs`

Existing `subagent_runs` remain the child-run audit table used by
`SubagentDelegator`.

## Safety Constraints

Safety rules in this version:

- child agents receive bounded role-specific tool registries
- team/workflow tools are present only in the parent default registry
- child workers cannot recursively spawn teams or workflows by default
- tool permissions require approval for `create_agent_team` and
  `run_agent_workflow`
- workflow specs are declarative YAML only
- outputs flow back through bounded summaries and result references
- prompt context includes Team Results and Subagent Results, not full child
  transcripts

## Tool Integration

Two parent tools exist:

- `create_agent_team`
- `run_agent_workflow`

Both require approval. Without approval they return compact queued JSON. With
approval, `create_agent_team` creates the team and queued tasks, while
`run_agent_workflow` validates and executes a declarative workflow.

Tool responses are compact JSON containing:

- `status`
- `team_id` or `workflow_run_id`
- `summary`
- `child_run_references`

## Bounded Summaries

Team and workflow summaries are designed for prompt injection:

- bounded summaries are truncated before entering parent context
- child run references are preserved for audit and follow-up
- raw child transcripts stay outside the parent prompt
