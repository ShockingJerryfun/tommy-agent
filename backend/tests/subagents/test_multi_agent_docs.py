"""Documentation coverage for the multi-agent runtime foundation."""

from __future__ import annotations

from pathlib import Path


def test_multi_agent_runtime_doc_exists_and_covers_core_topics() -> None:
    doc = Path("../docs/architecture/multi-agent-runtime.md")
    content = doc.read_text(encoding="utf-8")

    for phrase in (
        "AgentDefinition",
        "WorkerPool",
        "Team Runtime MVP",
        "Workflow Runtime MVP",
        ".tommy/agents",
        "workflow YAML",
        "bounded summaries",
    ):
        assert phrase in content
