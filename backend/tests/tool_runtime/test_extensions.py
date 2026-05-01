"""Tests for the S7 extensions package: hooks + MCP tool provider."""

from __future__ import annotations

import time
import uuid

import pytest
from pydantic import ValidationError

from app.agent_framework.extensions import (
    HookContext,
    HookPhase,
    HookRegistry,
    MCPToolProvider,
    MCPToolSpec,
    StaticMCPServer,
    install_builtin_hooks,
    mcp_tool_from_spec,
)
from app.agent_framework.storage import PostgresAgentStore
from app.agent_framework.tool_runtime import ToolRegistry, get_current_time

# ---------------------------------------------------------------------- registry


def test_registry_orders_hooks_by_order_then_seq() -> None:
    registry = HookRegistry()
    log: list[str] = []

    registry.register(
        name="b",
        phase=HookPhase.RUN_START,
        callable=lambda _ctx: log.append("b"),
        order=10,
    )
    registry.register(
        name="a",
        phase=HookPhase.RUN_START,
        callable=lambda _ctx: log.append("a"),
        order=20,
    )
    registry.register(
        name="c",
        phase=HookPhase.RUN_START,
        callable=lambda _ctx: log.append("c"),
        order=10,
    )

    outcomes = registry.dispatch(HookPhase.RUN_START)

    assert log == ["b", "c", "a"]
    assert [o.name for o in outcomes] == ["b", "c", "a"]
    assert all(o.status == "ok" for o in outcomes)


def test_registry_records_errors_and_continues_when_warn() -> None:
    registry = HookRegistry()
    log: list[str] = []

    def boom(_ctx: HookContext) -> None:
        raise RuntimeError("nope")

    registry.register(name="boom", phase=HookPhase.RUN_END, callable=boom, order=1)
    registry.register(
        name="after",
        phase=HookPhase.RUN_END,
        callable=lambda _ctx: log.append("after"),
        order=2,
    )

    outcomes = registry.dispatch(HookPhase.RUN_END)
    assert outcomes[0].status == "error"
    assert "nope" in (outcomes[0].error or "")
    assert outcomes[1].status == "ok"
    assert log == ["after"]


def test_registry_halts_when_failure_policy_is_halt() -> None:
    registry = HookRegistry()
    log: list[str] = []

    def boom(_ctx: HookContext) -> None:
        raise RuntimeError("stop")

    registry.register(
        name="boom",
        phase=HookPhase.PRE_TOOL,
        callable=boom,
        order=1,
        failure_policy="halt",
    )
    registry.register(
        name="never",
        phase=HookPhase.PRE_TOOL,
        callable=lambda _ctx: log.append("never"),
        order=2,
    )

    outcomes = registry.dispatch(HookPhase.PRE_TOOL)
    assert outcomes[0].status == "error"
    assert outcomes[1].status == "skipped"
    assert log == []


def test_registry_enforces_timeout() -> None:
    registry = HookRegistry()

    def slow(_ctx: HookContext) -> None:
        time.sleep(0.5)

    registry.register(
        name="slow",
        phase=HookPhase.PRE_COMPACT,
        callable=slow,
        timeout_seconds=0.05,
    )
    outcomes = registry.dispatch(HookPhase.PRE_COMPACT)
    assert outcomes[0].status == "timeout"
    assert "exceeded" in (outcomes[0].error or "")


def test_registry_unregister_removes_hook() -> None:
    registry = HookRegistry()
    registry.register(name="x", phase=HookPhase.RUN_START, callable=lambda _c: None)
    assert len(registry.list(HookPhase.RUN_START)) == 1
    removed = registry.unregister(name="x")
    assert removed == 1
    assert registry.list(HookPhase.RUN_START) == []


def test_dispatch_threads_context_payload() -> None:
    registry = HookRegistry()
    seen: list[HookContext] = []

    registry.register(
        name="capture",
        phase=HookPhase.POST_TOOL,
        callable=lambda ctx: seen.append(ctx),
    )
    ctx = HookContext(
        phase=HookPhase.POST_TOOL,
        session_id="sess-1",
        run_id="run-1",
        payload={"tool_name": "web_search"},
    )
    registry.dispatch(HookPhase.POST_TOOL, ctx)
    assert seen[0].session_id == "sess-1"
    assert seen[0].payload["tool_name"] == "web_search"


# ---------------------------------------------------------------------- builtins


def test_install_builtin_hooks_registers_all_three() -> None:
    store = PostgresAgentStore()
    store.reset_for_tests()
    registry = HookRegistry()
    bundle = install_builtin_hooks(registry, store=store)
    names = {r.name for r in registry.list()}
    assert bundle.memory_flush in names
    assert bundle.stale_approval_cleanup in names
    assert bundle.checkpoint_prune in names


def test_stale_approval_cleanup_rejects_old_pending_approvals() -> None:
    store = PostgresAgentStore()
    store.reset_for_tests()
    session_id = f"sess-{uuid.uuid4().hex[:8]}"
    store.create_session(session_id=session_id, agent_id="default", title="t")

    fresh = store.create_approval_request(
        session_id=session_id,
        run_id="r-1",
        tool_call_id="tc-1",
        tool_name="shell",
        args={"command": "echo hi"},
        risk_level="low",
        summary="echo hi",
    )
    stale = store.create_approval_request(
        session_id=session_id,
        run_id="r-2",
        tool_call_id="tc-2",
        tool_name="shell",
        args={"command": "echo old"},
        risk_level="low",
        summary="echo old",
    )
    # Force ``stale.created_at`` into the past.
    with store._connector.connect() as conn:  # noqa: SLF001 — test helper.
        conn.execute(
            "UPDATE approval_requests SET created_at = ? WHERE id = ?",
            ("2020-01-01T00:00:00+00:00", stale["id"]),
        )

    registry = HookRegistry()
    install_builtin_hooks(registry, store=store, approval_ttl_seconds=60)
    outcomes = registry.dispatch(
        HookPhase.RUN_END,
        HookContext(phase=HookPhase.RUN_END, session_id=session_id),
    )
    cleanup = next(o for o in outcomes if "cleanup_stale" in o.name)
    assert cleanup.status == "ok"

    refreshed_fresh = store.get_approval_request(fresh["id"])
    refreshed_stale = store.get_approval_request(stale["id"])
    assert refreshed_fresh["status"] == "pending"
    assert refreshed_stale["status"] == "rejected"
    assert "expired" in (refreshed_stale.get("error") or "").lower()


def test_checkpoint_prune_hook_calls_delete_thread_only_when_requested() -> None:
    calls: list[str] = []

    class FakeCheckpointer:
        def delete_thread(self, thread_id: str) -> None:
            calls.append(thread_id)

    registry = HookRegistry()
    install_builtin_hooks(registry, checkpointer=FakeCheckpointer())

    registry.dispatch(
        HookPhase.RUN_END,
        HookContext(phase=HookPhase.RUN_END, session_id="sess-x"),
    )
    assert calls == []  # no prune flag

    registry.dispatch(
        HookPhase.RUN_END,
        HookContext(
            phase=HookPhase.RUN_END,
            session_id="sess-x",
            payload={"prune_checkpoint": True},
        ),
    )
    assert calls == ["sess-x"]


# ---------------------------------------------------------------------- MCP


def _build_static_server() -> StaticMCPServer:
    return StaticMCPServer(
        name="weather",
        tools=[
            MCPToolSpec(
                name="lookup",
                description="Look up the weather.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"},
                        "units": {"type": "string", "default": "metric"},
                    },
                    "required": ["city"],
                },
            )
        ],
        handlers={"lookup": lambda city, units="metric": f"{city}:{units}:sunny"},
    )


def test_mcp_tool_from_spec_invokes_handler_with_typed_args() -> None:
    server = _build_static_server()
    spec = server.list_tools()[0]
    tool = mcp_tool_from_spec(server, spec)
    assert tool.name == "mcp.weather.lookup"
    assert tool.description == "Look up the weather."

    result = tool.invoke({"city": "Paris"})
    assert result == "Paris:metric:sunny"


def test_mcp_tool_validates_required_args() -> None:
    server = _build_static_server()
    spec = server.list_tools()[0]
    tool = mcp_tool_from_spec(server, spec)
    with pytest.raises(ValidationError):
        tool.invoke({})  # missing required ``city``


def test_mcp_provider_merges_into_existing_registry() -> None:
    provider = MCPToolProvider([_build_static_server()])
    base = ToolRegistry(tools=(get_current_time,))
    merged = provider.to_registry(base=base)
    names = {t.name for t in merged.tools}
    assert "get_current_time" in names
    assert "mcp.weather.lookup" in names


def test_mcp_provider_remove_drops_server() -> None:
    server = _build_static_server()
    provider = MCPToolProvider([server])
    assert provider.remove("weather") == 1
    assert provider.list_tools() == []
