# Agent Landscape Technical Notes

## Purpose

This document captures the agent-system research that should guide Tommy's next
architecture work. It is not a product comparison. The goal is to preserve reusable
engineering patterns from modern coding agents and memory-centric agents so future
changes do not drift back into ad hoc runtime, storage, or context handling.

Tommy's target remains narrower than a full gateway platform: a LangGraph-first coding
agent workbench with PostgreSQL-backed runtime state, strong memory boundaries, safe tool
execution, and a path to multi-agent workflows.

## Tommy's Current Position

Tommy has moved past the SQLite/JSONL demo baseline. PostgreSQL now owns runtime state,
LangGraph owns graph execution and checkpointing, and the frontend can observe sessions,
runs, approvals, events, and settings. The next architectural problem is no longer
"persist the loop"; it is "make the loop small enough to grow."

The most important immediate move is to split `RunManager` and introduce
`ContextBuilder`:

- `RunManager` should become a thin lifecycle facade rather than the place where
  streaming, event replay, assistant message flushing, graph invocation, compaction, and
  memory proposals all live.
- `ContextBuilder` should become the single inspected boundary where curated files,
  retrieved memory, context pact, skills, workspace state, metadata, and tool policy enter
  the prompt.
- Memory provider, pgvector, tool runtime, hooks, subagents, artifacts, trace, and eval
  should attach to those two boundaries instead of adding more branches to the current
  manager/prompt/node code.

## Cross-System Patterns

Modern agents converge on a few core principles:

- They separate short-term execution state from long-term memory. Checkpoints and thread
  state are recoverability mechanisms, not memory.
- They keep the main model context clean. Large logs, tool traces, retrieval candidates,
  and delegated exploration live outside the main prompt until intentionally summarized
  or injected.
- They treat sessions as durable product objects. Messages, tool calls, approvals,
  events, checkpoints, and compaction summaries need transactionally consistent IDs.
- They make tools declarative. Tool schemas, permissions, runtime injection, audit logs,
  and result handling are explicit surfaces.
- They support extension without changing the core loop. Skills, hooks, MCP servers,
  subagents, providers, and workflows are separate extension layers.
- They enforce context budgets. Retrieved memory, file snippets, and summaries must be
  ranked and bounded before entering the prompt.
- They keep the orchestrator thin. The run service coordinates lifecycle, while context
  building, tool execution, memory retrieval, event persistence, artifacts, and eval are
  separate testable subsystems.

## Claude Code Patterns

Claude Code's most useful architectural idea is layered context plus extension points.
Its behavior is shaped by project memory, user memory, commands, skills, hooks, MCP, and
subagents rather than a single large prompt.

Useful mechanisms:

- Project and user memory are loaded as structured context layers. The important detail
  is not the filename itself, but the boundary: stable project rules, user preferences,
  and session-specific state are not mixed together.
- Skills package repeatable workflows with instructions and optional assets. A skill is
  procedural memory that can be discovered and invoked when the task fits.
- Hooks provide event-driven enforcement. They can run around tool calls, edits, commits,
  or session events to add policy and automation without changing the agent core.
- Subagents run with isolated context. They are good for broad exploration, reviews,
  testing, and parallel attempts because they prevent research logs from polluting the
  parent context.
- MCP externalizes capabilities. Browser, GitHub, Figma, docs, and other services should
  be attached through a typed tool boundary, not hardcoded into the prompt loop.
- Permission and approval are part of tool execution, not UI-only concerns. Risky actions
  should be classified before execution and recorded after resolution.

What Tommy should absorb:

- Keep curated memory (`SOUL.md`, `USER.md`, `MEMORY.md`) small and layered.
- Route all model-visible context through `ContextBuilder` so memory, skills, hooks, and
  subagent summaries do not compete inside one prompt function.
- Promote procedural memory into first-class skills with metadata, versions, and
  activation rules.
- Add hooks for run lifecycle, tool approval, memory extraction, compaction, and testing.
- Add subagent sessions with isolated context and parent-child provenance in PostgreSQL.
- Treat MCP and local tools as plug-in providers behind the same tool runtime contract.

What Tommy should not copy directly:

- Do not make file-based memory the source of truth for sessions or runtime state.
- Do not let hooks become hidden global side effects. They need registration, ordering,
  timeout, failure policy, and audit events.

## OpenCode Patterns

OpenCode-style coding agents emphasize a modular command/runtime architecture. The
useful lesson is that sessions, permissions, tools, providers, and UI can evolve
independently when they have explicit contracts.

Useful mechanisms:

- Sessions are explicit runtime objects. A session can own messages, tool executions,
  child tasks, and UI state without requiring the model loop to know every persistence
  detail.
- Tools are declarative units with schemas and permission requirements. The runtime can
  decide whether to execute, ask, reject, or sandbox a tool call.
- Provider/model selection is separated from orchestration. The graph should not be tied
  to one model client or one prompt style.
- Child sessions are a natural way to delegate work. A child can perform exploration or
  testing and return a bounded result to the parent.
- UI surfaces can stream structured events instead of parsing free-form text.

What Tommy should absorb:

- Split `RunManager` into run service, stream/event service, tool execution service, and
  graph runtime service.
- Keep `RunManager` as an API-facing facade during the split so frontend behavior and
  routes do not churn.
- Move permission decisions into a reusable permission engine shared by frontend and
  backend event logs.
- Model subagents as child runs/sessions with parent run IDs, not as plain text notes.
- Keep frontend run visualization driven by typed events and stored run steps.

What Tommy should not copy directly:

- Do not optimize for terminal UI first. Tommy already has a web workbench, so the API
  and event model should remain frontend-friendly.

## Hermes Agent Patterns

Hermes is useful as a memory and prompt orchestration reference. Its design points toward
an agent core with well-defined provider hooks rather than scattered memory reads.

Useful mechanisms:

- A central agent orchestrator composes prompt building, memory access, tools, and model
  calls. The risk is monolith growth, but the benefit is clear lifecycle ownership.
- Prompt building is a dedicated concern. System prompt sections, retrieved memories,
  tool instructions, and task context are assembled by a prompt builder rather than mixed
  into arbitrary runtime code.
- Memory providers expose lifecycle hooks: prefetch before a turn, sync after a turn,
  extract on session end, and update before compaction.
- Memory is bounded. The agent retrieves what is useful for the current turn instead of
  dumping all known memory into the prompt.
- Checkpoint/rollback concepts exist outside conversational memory. Recovery and memory
  are related but separate.

What Tommy should absorb:

- Add a `ContextBuilder` or `PromptBuilder` module that owns prompt sections, ordering,
  budget, and citations.
- Turn current memory reads into a `MemoryProvider` contract with prefetch, sync,
  extraction, and compaction hooks.
- Record memory provenance: source session, message, tool call, extraction rule,
  confidence, and confirmation status.
- Add explicit memory write proposals and confirmations before promoting facts into
  always-on curated memory.
- Treat prompt snapshots and memory injection records as runtime data. They are needed
  for trace, replay, eval, and debugging hallucinated memory.

What Tommy should not copy directly:

- Do not let one `AIAgent` class own storage, memory, tools, and orchestration. Tommy is
  already splitting these boundaries and should continue in that direction.

## OpenClaw Patterns

OpenClaw is heavier than Tommy's near-term needs, but it is valuable as a session and
maintenance reference. Its gateway-like design shows what becomes necessary when many
agents, tools, and long-running sessions share one runtime.

Useful mechanisms:

- A gateway or runtime authority owns sessions. Clients should not invent session state
  independently.
- Transcript data is formalized. If JSONL exists, it is an intentional rebuildable
  transcript with retention and rotation, not a side log.
- Compaction is paired with memory flush. Before discarding old context, the system
  extracts durable facts, decisions, and tasks.
- Maintenance is automatic. Retention, rotation, cleanup, orphan recovery, and summary
  refresh are part of runtime operation.
- Multi-agent workflows require isolation. Parent and child agents need separate state
  with clear handoff and provenance.

What Tommy should absorb:

- Keep PostgreSQL as the session authority for messages, runs, events, approvals, and
  memory proposals.
- If transcript export is reintroduced, generate it from PostgreSQL with retention and
  rotation rather than writing JSONL during execution.
- Add maintenance jobs for checkpoint pruning, orphan run reconciliation, stale approval
  cleanup, and memory index refresh.
- Treat compaction as an extraction point, not only a prompt-shortening step.
- Keep artifacts outside the prompt by default. Store large command outputs, screenshots,
  search results, and generated files as referenced runtime objects.

What Tommy should not copy directly:

- Do not build a heavy gateway before the core LangGraph runtime is stable.
- Do not add multi-agent routing until the run/event/store boundaries are smaller and
  well tested.

## LangGraph-Specific Guidance

LangGraph should remain Tommy's orchestration foundation. The main lesson from LangGraph
is to keep graph state, checkpoint state, and long-term memory separate.

Important boundaries:

- `StateGraph` owns node transitions and graph state.
- PostgreSQL checkpointer owns resumable thread state by `thread_id`.
- Application PostgreSQL tables own product state such as sessions, messages, runs,
  approvals, events, and memories.
- A future LangGraph store or Tommy memory provider should own cross-session memory
  retrieval, not the checkpointer.
- Tool runtime values should be injected by trusted backend code, not supplied by model
  arguments.

Tommy should keep the custom graph while it is still small. Prebuilt ReAct-style agents
are useful references, but Tommy needs explicit control over approvals, event streaming,
memory sync, and frontend run visualization.

Near-term LangGraph shape:

- Graph nodes should call a context builder and a tool executor, not perform prompt
  assembly, approval creation, or tool persistence inline.
- `GraphRuntime` should hide graph construction, checkpointer setup, thread config, and
  stream-mode normalization from `RunManager`.
- Custom stream events should remain the frontend contract, but event persistence and
  replay should live outside the graph loop.
- Checkpoint state should not be mined as memory. Memory retrieval should go through a
  provider that can use PostgreSQL FTS, pgvector, reranking, and provenance.

## Near-Term Build Order

The reference systems all point to the same sequencing for Tommy:

1. Split runtime coordination first.
   Keep API routes stable, but extract event streaming/replay, message writing, graph
   invocation, pre-run preparation, and cancellation/orphan handling behind small
   services.

2. Add `ContextBuilder` before advanced memory.
   Establish section ordering, budgets, provenance, prompt snapshots, and memory
   injection records. Then pgvector and reranking have a safe model-visible surface.

3. Move tool execution into a typed runtime.
   Create a trusted `ToolRuntime`, declarative permissions, structured tool results, and
   artifact references for large outputs.

4. Add hooks and skills as extension layers.
   Hooks should run around lifecycle events and tool/memory boundaries with timeout,
   ordering, failure policy, and audit events.

5. Add subagents after parent/child state and context import are explicit.
   Child agents should produce bounded summaries and artifacts, not raw transcript dumps.

6. Add trace and eval once prompt/context/tool/event records are durable.
   Replay and evaluation need stored prompt snapshots, memory injections, tool calls,
   approvals, events, costs, latency, and final outcomes.

## Design Rules For Tommy

- PostgreSQL is the runtime source of truth. Do not reintroduce SQLite or JSONL as live
  state paths.
- `RunManager` should coordinate, not own every subsystem.
- `ContextBuilder` is the only path for model-visible context assembly.
- Every long-running action should have a run ID, event stream, and persisted status.
- Every tool call should have a stored request, permission decision, result, and error.
- Every memory injected into the model should have a source and budget cost.
- Every subagent or delegated workflow should be represented as a child run/session.
- Every extension point should have registration, configuration, timeout, and audit
  behavior.
