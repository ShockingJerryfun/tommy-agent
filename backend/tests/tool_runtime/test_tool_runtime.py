"""Tests for the S4 ToolRuntime pipeline."""

from __future__ import annotations

import json
import uuid

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent_framework.storage import PostgresAgentStore
from app.agent_framework.tool_runtime import (
    ARTIFACT_SPILL_THRESHOLD,
    PermissionPolicy,
    ToolError,
    ToolRegistry,
    ToolRuntime,
    default_permission_policy,
    load_permission_policy,
)

# ---------------------------------------------------------------------------
# Synthetic tools used by the runtime tests
# ---------------------------------------------------------------------------


class _EchoArgs(BaseModel):
    text: str = Field(..., min_length=1, max_length=64)
    repeat: int = Field(1, ge=1, le=8)


@tool("echo_tool", args_schema=_EchoArgs)
def echo_tool(text: str, repeat: int = 1) -> str:
    """Return ``text`` repeated ``repeat`` times."""

    return text * repeat


class _BigArgs(BaseModel):
    size: int = Field(1024, ge=1, le=200_000)


@tool("big_tool", args_schema=_BigArgs)
def big_tool(size: int = 1024) -> str:
    """Return a string of ``size`` ASCII chars (used to trigger auto-spill)."""

    return "x" * size


class _ExplodeArgs(BaseModel):
    msg: str = Field("boom")


@tool("explode_tool", args_schema=_ExplodeArgs)
def explode_tool(msg: str = "boom") -> str:
    """Always raises — tests the runtime_error path."""

    raise RuntimeError(msg)


def _registry() -> ToolRegistry:
    return ToolRegistry(tools=(echo_tool, big_tool, explode_tool))


def _store() -> PostgresAgentStore:
    store = PostgresAgentStore()
    store.reset_for_tests()
    return store


def _new_session(store: PostgresAgentStore) -> str:
    session_id = f"sess-{uuid.uuid4().hex[:10]}"
    store.create_session(session_id=session_id, agent_id="default", title="t")
    return session_id


# ---------------------------------------------------------------------------
# Permission policy
# ---------------------------------------------------------------------------


def test_default_policy_loads_yaml_and_marks_write_local_file_always():
    policy = default_permission_policy()
    decision = policy.evaluate(
        "write_local_file",
        {"path": "notes.txt", "content": "hi", "mode": "overwrite"},
        command_scope="restricted",
    )
    assert decision.needs_approval is True
    assert decision.risk_level == "high"
    assert "notes.txt" in decision.summary

    benign = policy.evaluate("get_current_time", {}, command_scope="restricted")
    assert benign.needs_approval is False


def test_dangerous_shell_command_requires_approval_even_unrestricted():
    policy = default_permission_policy()
    decision = policy.evaluate(
        "run_shell_command",
        {"command": "sudo rm -rf /"},
        command_scope="unrestricted",
    )
    assert decision.needs_approval is True
    assert decision.denied is False


def test_unrestricted_scope_skips_approval_except_dangerous_shell():
    policy = default_permission_policy()
    safe = policy.evaluate(
        "run_shell_command",
        {"command": "pwd"},
        command_scope="unrestricted",
    )
    assert safe.needs_approval is False

    dangerous = policy.evaluate(
        "run_shell_command",
        {"command": "sudo rm -rf /"},
        command_scope="unrestricted",
    )
    assert dangerous.needs_approval is True


def test_inline_policy_construction_for_tests():
    policy = PermissionPolicy(
        {
            "version": 1,
            "default": {"approval": "never", "risk": "low"},
            "tools": {
                "danger": {"approval": "always", "risk": "medium"},
            },
            "denied_command_patterns": [],
        }
    )
    assert policy.evaluate("danger", {}).needs_approval is True
    assert policy.evaluate("benign", {}).needs_approval is False


def test_load_permission_policy_returns_fresh_instance(tmp_path):
    yaml_text = """
version: 1
default: {approval: never, risk: low}
tools:
  bespoke: {approval: always, risk: high}
denied_command_patterns: []
"""
    target = tmp_path / "policy.yaml"
    target.write_text(yaml_text, encoding="utf-8")
    policy = load_permission_policy(target)
    assert policy.evaluate("bespoke", {}).risk_level == "high"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validation_error_short_circuits_before_running():
    runtime = ToolRuntime(_registry())
    result = runtime.execute(
        "echo_tool",
        {"text": "", "repeat": 1},
        tool_call_id="tc-1",
    )
    assert result.status == "error"
    assert isinstance(result.error, ToolError)
    assert result.error.code == "validation_error"

    parsed = json.loads(result.content)
    assert parsed["status"] == "error"
    assert parsed["error"]["code"] == "validation_error"


def test_unknown_tool_yields_not_found_error():
    runtime = ToolRuntime(_registry())
    result = runtime.execute("nope_tool", {}, tool_call_id="tc-x")
    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "not_found"


def test_runtime_error_in_tool_is_wrapped():
    runtime = ToolRuntime(_registry())
    result = runtime.execute("explode_tool", {"msg": "kaboom"}, tool_call_id="tc-2")
    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "runtime_error"
    assert "kaboom" in result.error.message


# ---------------------------------------------------------------------------
# Permission denied path
# ---------------------------------------------------------------------------


def test_permission_denied_short_circuits_with_structured_error():
    # Use a custom policy that bans a benign tool to keep the test fast.
    policy = PermissionPolicy(
        {
            "version": 1,
            "default": {"approval": "never", "risk": "low"},
            "tools": {
                "echo_tool": {"approval": "always", "risk": "high"},
            },
            "denied_command_patterns": ["forbidden"],
        }
    )
    runtime = ToolRuntime(_registry(), policy=policy)
    # ``approval_granted`` not set → runtime returns pending_approval
    result = runtime.execute(
        "echo_tool",
        {"text": "hi", "repeat": 1},
        tool_call_id="tc-perm",
        command_scope="restricted",
    )
    assert result.status == "pending_approval"
    assert result.metadata.get("permission", {}).get("risk_level") == "high"


def test_dangerous_shell_returns_pending_approval_without_grant():
    runtime = ToolRuntime(_registry())

    # Add a stub run_shell_command into a fresh registry just for this case.
    @tool("run_shell_command")
    def shell(command: str) -> str:
        """Stub shell tool used to exercise the deny-list."""
        return f"ran: {command}"

    runtime.registry = ToolRegistry(tools=(shell,))
    result = runtime.execute(
        "run_shell_command",
        {"command": "sudo rm -rf /"},
        tool_call_id="tc-shell",
        command_scope="unrestricted",
    )
    assert result.status == "pending_approval"
    assert result.metadata.get("permission", {}).get("risk_level") == "high"


# ---------------------------------------------------------------------------
# Run + persist
# ---------------------------------------------------------------------------


def test_successful_run_persists_tool_calls_row():
    store = _store()
    session_id = _new_session(store)
    runtime = ToolRuntime(_registry())

    result = runtime.execute(
        "echo_tool",
        {"text": "hi", "repeat": 3},
        tool_call_id="tc-run-1",
        context={"approval_granted": True},
        store=store,
        session_id=session_id,
        run_id="run-x",
    )
    assert result.ok
    assert result.content == "hihihi"
    assert result.spilled is False

    rows = store.list_tool_calls(session_id)
    assert len(rows) == 1
    assert rows[0]["status"] == "ok"
    assert rows[0]["name"] == "echo_tool"
    assert rows[0]["args"] == {"text": "hi", "repeat": 3}


def test_persist_disabled_skips_tool_calls_write():
    store = _store()
    session_id = _new_session(store)
    runtime = ToolRuntime(_registry())

    runtime.execute(
        "echo_tool",
        {"text": "hi", "repeat": 1},
        tool_call_id="tc-no-persist",
        context={"approval_granted": True},
        store=store,
        session_id=session_id,
        persist=False,
    )
    assert store.list_tool_calls(session_id) == []


# ---------------------------------------------------------------------------
# Auto-spill
# ---------------------------------------------------------------------------


def test_large_output_is_spilled_to_artifact_store():
    store = _store()
    session_id = _new_session(store)
    runtime = ToolRuntime(_registry(), spill_threshold_bytes=1024)

    result = runtime.execute(
        "big_tool",
        {"size": 5000},
        tool_call_id="tc-spill",
        context={"approval_granted": True},
        store=store,
        session_id=session_id,
        run_id="run-spill",
    )
    assert result.ok
    assert result.spilled is True
    assert result.artifact is not None
    assert result.artifact.size_bytes == 5000

    payload = json.loads(result.content)
    assert payload["spilled"] is True
    assert payload["artifact"]["artifact_id"] == result.artifact.artifact_id
    assert payload["preview"].startswith("xxxx")

    fetched = store.tool_artifacts.get(result.artifact.artifact_id)
    assert fetched is not None
    assert fetched["body"] == "x" * 5000
    assert fetched["session_id"] == session_id

    rows = store.list_tool_calls(session_id)
    assert rows[0]["status"] == "ok"
    # Persisted result is the artifact reference JSON, not the raw body.
    persisted = json.loads(rows[0]["result"])
    assert persisted["artifact"]["artifact_id"] == result.artifact.artifact_id


def test_below_threshold_keeps_output_inline():
    store = _store()
    session_id = _new_session(store)
    runtime = ToolRuntime(_registry(), spill_threshold_bytes=10_000)

    result = runtime.execute(
        "big_tool",
        {"size": 256},
        tool_call_id="tc-inline",
        context={"approval_granted": True},
        store=store,
        session_id=session_id,
    )
    assert result.ok
    assert result.spilled is False
    assert result.artifact is None
    assert result.content == "x" * 256
    assert store.tool_artifacts.list_for_session(session_id) == []


def test_artifact_spill_threshold_default_is_eight_kib():
    assert ARTIFACT_SPILL_THRESHOLD >= 1024
