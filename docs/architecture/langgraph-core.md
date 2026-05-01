# LangGraph Core Design Notes

## Source-Level Principles

LangGraph separates short-term thread persistence from long-term memory:

- Checkpointers persist graph state by `thread_id` and support resume, pending writes,
  interrupt, time travel, and fault tolerance.
- Stores provide cross-thread memory through namespace-based get/search/put APIs.

Tommy should keep this separation. The application store is product state, the
LangGraph checkpointer is thread state, and the memory platform is cross-session
knowledge.

## Checkpointing

The production path should use LangGraph's PostgreSQL checkpointer rather than a custom
checkpoint schema. `AsyncPostgresSaver` already handles schema setup, checkpoint blobs,
checkpoint writes, pending writes, and thread deletion.

Tommy should wrap saver lifecycle in a small factory:

- initialize from app config during FastAPI lifespan
- call `setup()` explicitly during startup or schema setup
- close the underlying connection/pool during shutdown
- expose `delete_thread`, `prune`, and future copy/fork helpers through one module

Tommy's runtime uses the PostgreSQL checkpointer; tests should exercise that same
backend so failures surface before local end-to-end runs.

## Tool Execution

LangGraph's prebuilt `ToolNode` shows a useful design even if Tommy keeps a custom
action node:

- trusted runtime data should be injected, not model-supplied
- tool errors should return structured tool messages
- graph interrupts should bubble up, not be converted into ordinary tool results
- store/state/runtime arguments should be hidden from the tool schema

Tommy's next tool layer should mirror this contract with a `ToolRuntime` style object
containing session id, agent id, run id, metadata, store access, approval state, and
artifact helpers.

## Graph Boundary

The current graph shape is intentionally simple:

- agent node calls the model with a constructed system prompt
- action node evaluates and executes tool calls
- routing loops until no tool calls remain

This should remain the first workflow. Additional workflows should be separate graph
builders that reuse the same run service, store, checkpointer, tool executor, and
context builder.
