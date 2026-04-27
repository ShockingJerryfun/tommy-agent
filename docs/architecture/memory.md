# Memory Architecture

## Memory Layers

Tommy should use four memory layers:

- Curated memory: bounded always-on context such as `SOUL.md`, `USER.md`, and a compact
  `MEMORY.md`.
- Episodic memory: session turns, tool results, observations, and compaction summaries.
- Semantic memory: extracted facts, preferences, decisions, project constraints, and
  lessons with provenance and confidence.
- Procedural memory: skills, rules, workflows, and repeatable operating procedures.

## Provider Contract

The memory layer should expose a provider contract inspired by modern agent systems:

- `initialize(session_context)`
- `system_prompt_block()`
- `prefetch(query, scope)`
- `queue_prefetch(query, scope)`
- `sync_turn(user_message, assistant_message, metadata)`
- `on_session_end(messages)`
- `on_pre_compact(messages)`
- `on_memory_write(action, target, content, metadata)`
- `on_delegation(task, result, metadata)`

The built-in provider can start with local curated files plus PostgreSQL-backed indexed
memory. Future providers can add external systems without changing the LangGraph loop.

## Retrieval

Production recall should be hybrid:

- PostgreSQL full-text search for exact terms, paths, identifiers, and error codes
- pgvector similarity search for semantic matches
- reranking by scope, recency, importance, confidence, and source trust
- context budget enforcement before prompt injection

Each injected memory should carry provenance back to a session, message, tool call,
artifact, or manual confirmation.

## Compaction

Compaction should preserve tool call/result pairs, recent turns, file paths, identifiers,
decisions, open tasks, and user constraints. Before compaction discards older context,
Tommy should trigger a pre-compaction memory flush so critical state survives in durable
memory.
