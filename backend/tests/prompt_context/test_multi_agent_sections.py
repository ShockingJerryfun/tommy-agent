from __future__ import annotations

import uuid

from langchain_core.messages import HumanMessage

from app.agent_framework.prompt_context import ContextBuilder, ContextBuildRequest
from app.agent_framework.storage import PostgresAgentStore


def _store() -> PostgresAgentStore:
    store = PostgresAgentStore()
    store.reset_for_tests()
    return store


def _new_session(store: PostgresAgentStore) -> tuple[str, str]:
    session_id = f"sess-{uuid.uuid4().hex[:10]}"
    store.create_session(session_id=session_id, agent_id="default", title="t")
    run_id = f"run-{uuid.uuid4().hex[:10]}"
    store.create_run(
        session_id=session_id,
        agent_id="default",
        input="context",
        run_id=run_id,
        status="running",
    )
    return session_id, run_id


def test_context_builder_injects_bounded_team_and_workflow_sections() -> None:
    store = _store()
    session_id, run_id = _new_session(store)
    team = store.agent_teams.create(
        parent_session_id=session_id,
        parent_run_id=run_id,
        goal="Audit runtime",
    )
    member = store.agent_team_members.create(
        team_id=team["id"],
        role="reviewer",
        agent_definition_id="reviewer",
    )
    task = store.agent_team_tasks.create(
        team_id=team["id"],
        title="Review storage",
        description="Review storage",
        assigned_member_id=member["id"],
    )
    store.agent_team_messages.create(
        team_id=team["id"],
        from_member_id=member["id"],
        task_id=task["id"],
        content="bounded mailbox note",
    )
    workflow_run = store.workflow_runs.create(
        spec_id="audit",
        parent_session_id=session_id,
        parent_run_id=run_id,
    )
    phase = store.workflow_phase_runs.create(
        workflow_run_id=workflow_run["id"],
        phase_id="inspect",
        kind="single",
        agent="reviewer",
    )
    child_session = store.create_session(agent_id="default", title="child")
    subagent = store.subagent_runs.create(
        parent_session_id=session_id,
        parent_run_id=run_id,
        child_session_id=child_session,
        role="reviewer",
        task="review",
        status="running",
        team_id=team["id"],
        team_task_id=task["id"],
        workflow_run_id=workflow_run["id"],
        phase_run_id=phase["id"],
        workflow_phase_id="inspect",
    )
    full_transcript = "TRANSCRIPT-LEAK " * 500
    store.subagent_runs.update(
        subagent["id"],
        status="completed",
        final_response=full_transcript,
        finished=True,
    )

    rendered = ContextBuilder(store=store, memory_provider=None).build(
        ContextBuildRequest(
            state={
                "session_id": session_id,
                "agent_id": "default",
                "messages": [HumanMessage(content="continue")],
                "metadata": {
                    "run_id": run_id,
                    "team_id": team["id"],
                    "team_task_id": task["id"],
                    "workflow_run_id": workflow_run["id"],
                    "phase_run_id": phase["id"],
                    "workflow_phase_id": "inspect",
                    "is_child": True,
                },
            },
            max_chars=9000,
        )
    )

    names = {section.name for section in rendered.sections}
    assert "active_team_role" in names
    assert "team_task_board" in names
    assert "team_mailbox" in names
    assert "workflow_phase_context" in names
    assert "child_constraints" in names
    assert "bounded mailbox note" in rendered.content
    assert "TRANSCRIPT-LEAK " * 100 not in rendered.content
    assert len(rendered.content) <= 9000
