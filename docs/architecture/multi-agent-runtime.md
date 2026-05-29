# Multi-Agent Runtime

This document describes Tommy's first production foundation for externalized
agents, bounded worker execution, lead-controlled teams, and declarative
workflows.

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

