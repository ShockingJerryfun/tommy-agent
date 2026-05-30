"""Tests for the S6 Subagent platform: scoped tools, delegate, best-of-N.

The tests use an injected fake runner so they don't require a live LLM.
The runner is the only knob that matters for unit testing the
parent/child wiring, the score computation, and the merger.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from app.agent_framework.storage import PostgresAgentStore
from app.agent_framework.subagents import (
    BestOfNMerger,
    SubagentDelegator,
    SubagentRole,
    list_role_ids,
    registry_for_role,
    score_response,
    subagent_summary_section,
)
from app.agent_framework.tool_runtime import ToolRegistry
from app.agent_framework.workers.context import ChildRunContext


def _store() -> PostgresAgentStore:
    store = PostgresAgentStore()
    store.reset_for_tests()
    return store


def _new_session(store: PostgresAgentStore) -> tuple[str, str]:
    session_id = f"sess-{uuid.uuid4().hex[:10]}"
    store.create_session(session_id=session_id, agent_id="default", title="t")
    run_id = f"run-{uuid.uuid4().hex[:10]}"
    return session_id, run_id


def _fake_runner(response: str):
    def runner(
        prompt: str,
        registry: ToolRegistry,
        role: SubagentRole,
        thread_config: dict[str, Any],
    ) -> dict[str, Any]:
        return {"final_response": response, "status": "completed"}

    return runner


def _write_agent(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------- roles


def test_role_registry_exposes_default_roles() -> None:
    ids = list_role_ids()
    assert {"researcher", "analyst", "writer"}.issubset(set(ids))


def test_registry_for_role_is_scoped() -> None:
    researcher = registry_for_role("researcher")
    writer = registry_for_role("writer")
    researcher_names = {t.name for t in researcher.tools}
    writer_names = {t.name for t in writer.tools}

    # Researcher is read-only — no write tools.
    assert "write_local_file" not in researcher_names
    # Writer can write files.
    assert "write_local_file" in writer_names
    # Both can read files.
    assert "read_local_file" in researcher_names
    assert "read_local_file" in writer_names


def test_registry_for_role_unknown_raises() -> None:
    with pytest.raises(KeyError):
        registry_for_role("evil-overlord")


def test_registry_for_role_uses_workspace_definition_from_child_context(
    tmp_path: Path,
) -> None:
    _write_agent(
        tmp_path / ".tommy" / "agents" / "reviewer.md",
        """---
id: reviewer
title: Workspace Reviewer
tools:
  - read_workspace_file
---
Use workspace reviewer instructions.
""",
    )
    child_context = ChildRunContext(
        parent_session_id="sess-1",
        parent_run_id="run-1",
        subagent_role="reviewer",
        working_directory=str(tmp_path),
    )

    registry = registry_for_role("reviewer", child_context=child_context)
    names = {tool.name for tool in registry.tools}

    assert names == {"read_workspace_file"}


def test_resolve_role_preserves_definition_runtime_metadata(tmp_path: Path) -> None:
    _write_agent(
        tmp_path / ".tommy" / "agents" / "reviewer.md",
        """---
id: reviewer
title: Workspace Reviewer
tools:
  - read_workspace_file
disallowed_tools:
  - write_local_file
max_turns: 4
max_wall_seconds: 30
model: deepseek-chat
permission_mode: read_only
---
Use workspace reviewer instructions.
""",
    )
    child_context = ChildRunContext(
        parent_session_id="sess-1",
        parent_run_id="run-1",
        subagent_role="reviewer",
        working_directory=str(tmp_path),
    )

    from app.agent_framework.subagents import resolve_role

    role = resolve_role("reviewer", child_context=child_context)

    assert role.title == "Workspace Reviewer"
    assert role.system_prompt == "Use workspace reviewer instructions."
    assert role.tool_names == ("read_workspace_file",)
    assert role.max_turns == 4
    assert role.max_wall_seconds == 30.0
    assert role.model == "deepseek-chat"


def test_context_aware_role_validation_rejects_unknown_tools(tmp_path: Path) -> None:
    _write_agent(
        tmp_path / ".tommy" / "agents" / "reviewer.md",
        """---
id: reviewer
title: Workspace Reviewer
tools:
  - missing_tool
---
Use workspace reviewer instructions.
""",
    )
    child_context = ChildRunContext(
        parent_session_id="sess-1",
        parent_run_id="run-1",
        subagent_role="reviewer",
        working_directory=str(tmp_path),
    )

    with pytest.raises(ValueError, match="unknown tool"):
        registry_for_role("reviewer", child_context=child_context)


# ----------------------------------------------------------- score


def test_score_response_rewards_length_and_citations() -> None:
    short = score_response("ok", citations_count=0)
    medium = score_response("x" * 600, citations_count=2)
    rich = score_response("x" * 1200, citations_count=5)

    assert 0.0 <= short < medium < rich <= 1.0
    assert rich == pytest.approx(1.0)


def test_score_response_empty_is_zero() -> None:
    assert score_response("", citations_count=10) == 0.0
    assert score_response("   ", citations_count=10) == 0.0


# ----------------------------------------------------------- delegate


def test_delegator_creates_child_session_and_records_subagent_run() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)

    delegator = SubagentDelegator(
        store, runner=_fake_runner("Found data at https://example.com — confirmed.")
    )
    result = delegator.dispatch(
        task="research X",
        role_id="researcher",
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        approval_id="appr-1",
        reason="user wants a report",
    )

    assert result.status == "completed"
    assert result.role == "researcher"
    assert result.score > 0.0
    assert result.citations_count == 1

    child = store.get_session(result.child_session_id)
    assert child is not None
    assert child["metadata"]["subagent"] is True
    assert child["metadata"]["parent_session_id"] == parent_session_id

    runs = store.subagent_runs.list_for_session(parent_session_id)
    assert len(runs) == 1
    row = runs[0]
    assert row["status"] == "completed"
    assert row["role"] == "researcher"
    assert row["parent_run_id"] == parent_run_id
    assert row["child_session_id"] == result.child_session_id
    assert row["metadata"]["citations_count"] == 1
    assert row["metadata"]["tool_scope"]
    assert "write_local_file" not in row["metadata"]["tool_scope"]


def test_delegator_parent_metadata_enables_workspace_role_override(
    tmp_path: Path,
) -> None:
    _write_agent(
        tmp_path / ".tommy" / "agents" / "reviewer.md",
        """---
id: reviewer
title: Workspace Reviewer
tools:
  - read_workspace_file
---
WORKSPACE REVIEWER PROMPT.
""",
    )
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)
    seen: dict[str, Any] = {}

    def runner(
        prompt: str,
        registry: ToolRegistry,
        role: SubagentRole,
        thread_config: dict[str, Any],
    ) -> dict[str, Any]:
        seen["prompt"] = prompt
        seen["role"] = role.title
        return {"final_response": "reviewed", "status": "completed"}

    delegator = SubagentDelegator(store, runner=runner)
    result = delegator.dispatch(
        task="review X",
        role_id="reviewer",
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        parent_metadata={"frontend_settings": {"workingDirectory": str(tmp_path)}},
    )

    assert result.status == "completed"
    assert seen["role"] == "Workspace Reviewer"
    assert "WORKSPACE REVIEWER PROMPT." in seen["prompt"]


def test_delegator_records_failures_without_raising() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)

    def boom(*_: Any, **__: Any) -> dict[str, Any]:
        raise RuntimeError("model exploded")

    delegator = SubagentDelegator(store, runner=boom)
    result = delegator.dispatch(
        task="x",
        role_id="analyst",
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
    )
    assert result.status == "failed"
    rows = store.subagent_runs.list_for_session(parent_session_id)
    assert rows[0]["status"] == "failed"
    assert "model exploded" in rows[0]["final_response"]


def test_delegator_short_circuits_when_run_is_stopped() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)
    store.create_run(
        session_id=parent_session_id,
        agent_id="default",
        input="hi",
        run_id=parent_run_id,
        status="running",
    )
    store.runs.request_run_cancel(parent_run_id)

    delegator = SubagentDelegator(store, runner=_fake_runner("should not run"))
    result = delegator.dispatch(
        task="x",
        role_id="researcher",
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
    )
    assert result.status == "stopped"
    # No row written because we short-circuited before recording.
    assert store.subagent_runs.list_for_session(parent_session_id) == []


# ----------------------------------------------------------- best-of-N


def test_best_of_n_picks_highest_score() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)

    responses = iter(
        [
            "short",  # low score
            "x" * 1200 + " https://a.com https://b.com https://c.com",  # winner
            "medium length response with one https://a.com link",
        ]
    )

    def runner(*_: Any, **__: Any) -> dict[str, Any]:
        return {"final_response": next(responses), "status": "completed"}

    merger = BestOfNMerger(store, SubagentDelegator(store, runner=runner))
    merged = merger.run(
        task="t",
        role_id="researcher",
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        n=3,
    )

    assert merged.status == "completed"
    assert merged.winner is not None
    assert merged.winner.score == max(a.score for a in merged.attempts)
    assert "https://a.com" in merged.final_response

    rows = store.subagent_runs.list_for_run(
        parent_session_id=parent_session_id, parent_run_id=parent_run_id
    )
    assert len(rows) == 3
    assert [r["attempt_index"] for r in rows] == [0, 1, 2]
    assert all(r["status"] == "completed" for r in rows)


def test_best_of_n_returns_failed_when_all_attempts_empty() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)

    def runner(*_: Any, **__: Any) -> dict[str, Any]:
        return {"final_response": "", "status": "completed"}

    merger = BestOfNMerger(store, SubagentDelegator(store, runner=runner))
    merged = merger.run(
        task="t",
        role_id="researcher",
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        n=2,
    )
    assert merged.status == "failed"
    assert merged.winner is None
    assert merged.final_response == ""


def test_best_of_n_n_must_be_positive() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)
    merger = BestOfNMerger(store, SubagentDelegator(store, runner=_fake_runner("x")))
    with pytest.raises(ValueError):
        merger.run(
            task="t",
            role_id="researcher",
            parent_session_id=parent_session_id,
            parent_run_id=parent_run_id,
            n=0,
        )


# ----------------------------------------------------------- summary section


def test_subagent_summary_section_reflects_recent_runs() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)

    delegator = SubagentDelegator(store, runner=_fake_runner("Insights at https://example.com."))
    delegator.dispatch(
        task="check the docs",
        role_id="researcher",
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
    )

    section = subagent_summary_section(store, parent_session_id=parent_session_id)
    assert "researcher" in section
    assert "check the docs" in section
    assert "https://example.com" in section


def test_subagent_summary_section_is_empty_for_new_session() -> None:
    store = _store()
    parent_session_id, _ = _new_session(store)
    assert subagent_summary_section(store, parent_session_id=parent_session_id) == ""
