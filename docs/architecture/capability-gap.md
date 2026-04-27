# Tommy Capability Gap

## Current Baseline

Tommy is now a PostgreSQL-backed LangGraph agent workbench. The current implementation
has a usable end-to-end baseline:

- FastAPI routes expose sessions, messages, runs, approvals, memory proposals, context
  pacts, skills, compaction, and streaming run events.
- The default graph lives under `agent_framework/graph/` and uses a custom `StateGraph`
  with an agent node, action node, routing, stop checks, and tool-call extraction.
- Runtime state lives in PostgreSQL through `PostgresAgentStore`.
- LangGraph thread state uses the PostgreSQL checkpointer.
- `RunManager` owns run creation, execution, SSE replay, cancellation, orphan
  reconciliation, message updates, run events, and compaction triggers.
- Tools support local file operations, shell execution, web search, skill proposals,
  context pact updates, and delegation records.
- Approvals exist for risky tools and are persisted in PostgreSQL.
- Curated prompt context reads `SOUL.md`, `USER.md`, and `MEMORY.md`.
- Memory proposals and active memories are persisted in PostgreSQL.
- Frontend can render sessions, run status, events, tool results, approvals, and settings.

This is a strong local workbench baseline, but it is still far from the capability level
of mature coding agents. The baseline is no longer a SQLite/JSONL demo; PostgreSQL and
LangGraph are now assumed foundations. The remaining gap is runtime architecture: the
agent loop works, but too many advanced capabilities still have to pass through the same
large manager, prompt function, and graph node code paths.

## Critical Path: RunManager And ContextBuilder

The highest-value next step is to split `RunManager` while introducing a real
`ContextBuilder`. These two pieces are the foundation for almost every later capability:

- `RunManager` is currently the choke point for run lifecycle, message persistence,
  streaming, cancellation, graph execution, compaction, memory proposals, and tool result
  persistence.
- `render_system_prompt` is currently the choke point for curated files, session summary,
  memory recall, context pact, skills, metadata, and tool instructions.
- Advanced memory needs a stable injection surface before pgvector, reranking, provenance,
  and review UI can pay off.
- Subagents need child run/session creation and bounded context handoff; both require
  smaller runtime services and inspectable context assembly.
- Hooks, artifacts, trace, and eval all become easier once events, prompt snapshots, tool
  calls, and run lifecycle are explicit services rather than side effects in the loop.

Recommended sequencing:

1. Keep the public API behavior stable and turn `RunManager` into a thin facade.
2. Extract event streaming/replay, assistant message flushing, graph invocation, and
   pre-run preparation into separate services.
3. Add `ContextBuilder` behind the existing `messages_with_system_prompt` facade.
4. Emit prompt/context snapshot events so later memory, trace, and eval work has a
   durable observation point.
5. Only then expand memory provider, tool runtime, hooks, artifacts, subagents, and eval
   on top of these boundaries.

## Gap 1: Runtime Service Boundaries

Current state:

- `RunManager` still owns too many responsibilities.
- API routes call a single manager that performs run creation, task scheduling, graph
  execution, assistant message flushing, event publishing, SSE replay, cancellation,
  orphan reconciliation, memory proposal creation, and compaction triggering.
- Tool call persistence is split across graph custom events and `RunManager` stream
  handling instead of a dedicated tool execution service.
- Store protocols exist, but `PostgresAgentStore` is still a large implementation class.

Target capability:

- `RunService` owns lifecycle, active-run policy, cancellation, and orphan reconciliation.
- `EventService` owns persisted events, replay, and frontend run-step mapping.
- `MessageWriter` owns assistant text/tool part accumulation and throttled persistence.
- `GraphRuntime` owns graph compilation, thread config, checkpoint integration, and
  graph-level errors.
- `ToolExecutionService` owns tool-call evaluation, runtime injection, persistence, and
  approval handling.
- `ContextBuilder` owns prompt construction and context budget.
- Store code is split into session, message, run, event, approval, skill, context, and
  memory repositories.

Why this matters:

- Mainstream agents keep orchestration, tools, memory, and UI events independently
  testable. Tommy's current monolith makes advanced workflows harder to add safely.

Near-term work:

- Split `RunManager` without changing API behavior; keep it as a facade used by routes.
- Move event publishing, persisted event mapping, subscriber queues, and SSE replay into
  `runtime/events.py` or a service package.
- Move assistant message part accumulation into a small tested writer object.
- Move pre-run preparation into a service: ensure session, append user/assistant shell
  messages, memory proposal, compaction trigger, and graph input assembly.
- Move tool-call persistence and approval flow out of `graph/nodes.py` after the event
  boundary is stable.
- Split `PostgresAgentStore` into repositories behind the existing protocols.
- Add contract tests that prove existing run creation, streaming, cancellation, tool
  events, and compaction behavior did not change during the split.

## Gap 2: Prompt And Context Builder

Current state:

- `prompts.py` directly assembles system context through `render_system_prompt`.
- Prompt construction performs store reads, file reads, skill listing, context pact
  rendering, metadata rendering, and memory recall in one function.
- Curated files are read from disk, while active memories are retrieved with simple
  PostgreSQL text matching.
- There is no explicit token budget or provenance rendering for injected memory.

Target capability:

- A `ContextBuilder` composes prompt sections in a stable order.
- Each section has a name, source, priority, budget, truncation strategy, and visibility
  in prompt snapshots.
- Retrieved memories carry provenance and confidence.
- Tool instructions, active skills, context pact, selected files, and recent run state are
  separate prompt blocks.
- Prompt rendering can be inspected and tested for a given run.
- The graph depends on `ContextBuilder` output, not direct global store reads.

Why this matters:

- Claude Code and Hermes-style systems rely on layered context. Without a builder, memory
  and rules tend to grow into one unbounded prompt.

Near-term work:

- Create `context_builder.py` with `ContextBuildRequest`, `ContextSection`, and rendered
  result objects.
- Keep `messages_with_system_prompt` as a compatibility facade while delegating to the
  builder.
- Implement deterministic section order: runtime, session summary, curated identity,
  user profile, curated memory, retrieved memory, context pact, skills, extracted context,
  metadata, workspace, tool-use policy, memory boundary.
- Add prompt snapshot events for debugging and future replay/eval.
- Store memory injection records for each run, even before pgvector lands.
- Keep curated files human-editable, but treat PostgreSQL as the runtime memory index.

## Gap 3: Memory Platform

Current state:

- Curated files exist.
- Memory proposals and active memories exist in PostgreSQL.
- Search is basic text matching.
- Compaction exists, but memory extraction is not a full provider lifecycle and
  `on_pre_compact` does not yet flush durable facts before context is shortened.
- There is no pgvector embedding index, hybrid retrieval, reranking, decay, or confidence.

Target capability:

- Four memory layers are implemented: curated, episodic, semantic, and procedural.
- `MemoryProvider` exposes prefetch, sync turn, pre-compaction flush, session-end
  extraction, memory write, and delegation hooks.
- PostgreSQL full-text search handles exact terms, paths, identifiers, and errors.
- pgvector handles semantic recall.
- Reranking considers scope, recency, confidence, importance, user confirmation, and
  source type.
- Memory records include provenance back to messages, tool calls, artifacts, and
  extraction rules.

Why this matters:

- Advanced agents retrieve useful memory quickly without polluting the main context.
  Tommy's current memory is durable but not yet intelligent.

Near-term work:

- Define the provider contract before optimizing retrieval internals.
- Add memory schema for facts, decisions, preferences, project constraints, lessons, and
  embeddings.
- Add FTS indexes for active memories and session summaries.
- Add pgvector extension and an embedding provider interface.
- Make compaction call `on_pre_compact` before it discards context.
- Add a memory review UI for proposed facts and rejected/confirmed memories.

## Gap 4: Tool Runtime And Permissions

Current state:

- Tools are registered and callable.
- Approval decisions exist for risky actions.
- Runtime context is passed to tools.
- Tool calls are persisted, but the execution pipeline is still embedded in graph node
  code.
- Tool outputs are summarized inline; large outputs do not yet become artifacts with
  references.

Target capability:

- `ToolRuntime` is a typed object containing session, run, agent, store, approval state,
  workspace root, artifact helpers, and cancellation checks.
- Tool schemas hide trusted runtime values from the model.
- Permission policy is declarative and testable.
- Tool calls persist request, normalized args, risk decision, approval request, execution
  result, error, duration, and artifact references.
- Large outputs are stored as artifacts and summarized for the model.

Why this matters:

- Claude Code/OpenCode-style agents are safe because tool execution is an explicit
  runtime subsystem, not just a function call.

Near-term work:

- Create `tools/runtime.py`, `tools/permissions.py`, and `tools/executor.py`.
- Move approval creation and tool execution out of `graph/nodes.py`.
- Add tool duration, retry policy, and structured error classes.
- Add artifact storage for large command outputs, search results, screenshots, and files.
- Make the model-visible tool schema exclude trusted runtime values such as session, run,
  store, workspace root, approval status, and artifact helpers.

## Gap 5: Skills, Hooks, And Extensions

Current state:

- Skill proposals exist and can be applied/rejected.
- Skills are listed in prompt context.
- There is no hook system.
- MCP-like external services are not a first-class runtime extension layer inside Tommy.

Target capability:

- Skills have metadata, version history, trigger hints, required tools, and safety notes.
- Hooks can run on run start/end, before/after tool call, before compaction, after memory
  extraction, and before approval resolution.
- Extensions register tools, memory providers, hooks, and UI panels through one boundary.
- Hook failures have timeout and failure policy.

Why this matters:

- Advanced coding agents grow through extension points. Without hooks, every workflow
  becomes a core-code change.

Near-term work:

- Add `extensions/registry.py`.
- Add hook tables and hook events.
- Add a small built-in hook set: lint after edit, memory flush before compaction,
  checkpoint pruning after run, and stale approval cleanup.
- Add skill activation metadata and a skill selection step in `ContextBuilder`.

## Gap 6: Subagents And Multi-Workflow Execution

Current state:

- `delegate_task` records a delegation-style event, but no real child agent execution
  exists.
- There is no parent-child session isolation.
- There is no background worker pool for exploration, review, testing, or best-of-N
  attempts.
- Parent prompts cannot yet import a bounded child summary or selected artifacts because
  artifact storage and context assembly are not explicit enough.

Target capability:

- Subagents are child sessions/runs with isolated graph context and inherited policy.
- Parent runs receive only bounded child summaries and selected artifacts.
- Child runs have their own messages, tool calls, approvals, checkpoints, and events.
- Common subagent types exist: explorer, reviewer, test runner, browser verifier, and
  implementation attempt.

Why this matters:

- Claude Code-style subagents keep the main context clean and allow parallel work.
  Tommy currently records intent to delegate but does not execute isolated workers.

Near-term work:

- Add parent-child columns and repository methods for sessions/runs.
- Implement a `SubagentService` that starts a child run with scoped instructions.
- Add child run events to the parent event stream.
- Add frontend UI for child run status and result import.
- Require child outputs to return through `ContextBuilder` sections or artifacts rather
  than raw transcript injection.

## Gap 7: Checkpoint, Recovery, And Maintenance

Current state:

- PostgreSQL checkpointer is active.
- Orphan run reconciliation exists.
- There is no retention policy for LangGraph checkpoints.
- There are no scheduled maintenance jobs.

Target capability:

- Checkpoint lifecycle has setup, prune, copy/fork, delete thread, and retention policy.
- Orphan run reconciliation runs at startup and periodically.
- Stale approvals, old checkpoints, old events, and failed artifacts are maintained.
- Backup/restore expectations are documented.

Why this matters:

- Long-running agent systems degrade without maintenance. OpenClaw-style systems treat
  cleanup and rotation as part of runtime health.

Near-term work:

- Add `maintenance/` service with explicit jobs.
- Add checkpoint pruning by age and thread status.
- Add stale approval expiration.
- Add `/health` details for database connectivity, checkpoint table presence, and
  maintenance lag.

## Gap 8: Observability And Evaluation

Current state:

- Runtime events and run steps are stored.
- Health endpoint reports basic Postgres/checkpoint status.
- There is no trace viewer, prompt snapshot, cost tracking, latency histogram, or replay
  harness.

Target capability:

- Every run has timing, model, token, cost, tool duration, approval delay, and error
  metadata.
- Prompt snapshots and memory injections are inspectable.
- A replay harness can run a stored session against a mock model or new graph version.
- Evaluations cover tool safety, memory recall, compaction preservation, and UI event
  consistency.

Why this matters:

- Advanced agents need observability because behavior is distributed across model,
  memory, tools, graph state, and UI.

Near-term work:

- Add run trace records and model usage fields.
- Add prompt snapshot storage.
- Add lightweight replay tests from stored fixtures.
- Add frontend trace panels for prompt, memory, tool, checkpoint, and event timelines.

## Gap 9: Frontend Workbench

Current state:

- The frontend can create sessions, stream runs, display run graph/status, show approvals,
  and manage settings.
- It does not yet expose full memory review, prompt snapshots, subagent hierarchy,
  artifact browsing, or maintenance status.

Target capability:

- Memory inbox for proposed facts and skills.
- Run trace inspector with prompt, memory, tools, events, and checkpoint information.
- Subagent tree view.
- Artifact viewer for large outputs.
- Maintenance and database health panel.

Why this matters:

- Tommy is a workbench, not only a backend. Advanced capability should be visible and
  debuggable from the UI.

Near-term work:

- Add tabs for memory review and run trace.
- Show parent/child runs once subagents exist.
- Add artifact links to tool result cards.
- Show database/checkpoint health from `/health`.

## Priority Roadmap

Stage 1 should build the runtime/context foundation:

- Split `RunManager`.
- Add `ContextBuilder`.
- Extract event service, message writer, graph runtime wrapper, and pre-run preparation.
- Add prompt snapshot/debug output and memory injection records.

Stage 2 should build real memory on top of the builder:

- Add memory provider contract.
- Add PostgreSQL FTS and pgvector.
- Add memory extraction and review flow.
- Add compaction memory flush.

Stage 3 should independentize tool execution and artifacts:

- Extract tool executor and permission engine.
- Add typed `ToolRuntime`.
- Add artifact store and large-output references.
- Add structured tool errors, durations, and retry policy.

Stage 4 should add extension surfaces:

- Add hook registry.
- Add richer skill metadata and activation.
- Add maintenance jobs.

Stage 5 should add subagents:

- Add child sessions/runs.
- Add subagent service.
- Add explorer/reviewer/test-runner workflows.
- Add frontend subagent tree.

Stage 6 should harden production behavior:

- Add replay/evaluation harness.
- Add cost/token/latency tracing.
- Add checkpoint retention and backup notes.
- Add security policy tests for destructive tools.

## Bottom Line

Tommy has crossed the most important early boundary: it is no longer a SQLite/JSONL demo
runtime. The next gap is architectural maturity. The best next move is not to add
pgvector, hooks, or subagents directly; it is to make the run loop and context assembly
small enough that those capabilities have a stable place to attach. Split `RunManager`,
build `ContextBuilder`, then layer memory provider, tool runtime, hooks, artifacts,
subagents, trace, and eval on top.
