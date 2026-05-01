# Storage Architecture

## Target

Tommy uses PostgreSQL as the runtime source of truth. The application should depend on
store interfaces and repository-style modules, not on a single monolithic store class.

The first boundary is now documented in `backend/app/agent_framework/storage/interfaces.py`.
Those protocols are intentionally narrow by domain:

- `SessionStore`
- `MessageStore`
- `RunStore`
- `EventStore`
- `ApprovalStore`
- `MemoryProposalStore`

`PostgresAgentStore` implements the current surface. Future work should split it into
smaller repositories without reintroducing multiple runtime backends.

## Source Of Truth

PostgreSQL should own:

- sessions and session lifecycle
- messages and message parts
- runs and run controls
- runtime events
- tool calls and approval requests
- context pacts and compaction records
- memory proposals and memory item metadata
- artifact metadata

LangGraph's PostgreSQL checkpointer should own checkpoint tables. Application tables and
checkpoint tables should be documented as separate concerns even if they share the same
database.

## JSONL And Files

JSONL should not be a live runtime source of truth. If retained, it should be generated
from database records as an export or audit artifact with retention and rotation.

Markdown files should remain curated human-editable context:

- `SOUL.md`: identity and boundaries
- `USER.md`: durable user profile
- `MEMORY.md`: bounded high-signal memory
- daily memory files: optional human-readable journal

Search and runtime recall should use database-backed memory records and indexed chunks,
not raw Markdown scanning as the primary path.

## Runtime Storage Notes

Local state rules:

- Duplicate local agent data directories should not be recreated; PostgreSQL owns runtime
  session history.
- root `MEMORY.md` is not the agent memory file currently read by prompts.
- previous local state can contain run events without run rows and should be treated as
  archived input.
- soft-deleted sessions can still have messages/events by design today; future retention
  should make this explicit.
- LangGraph checkpoint tables can grow faster than app state and need retention or pruning.
