from __future__ import annotations

from app.agent_framework.api_handlers import knowledge
from app.agent_framework.storage import PostgresAgentStore


def _store_with_proposal(content: str = "User likes precise answers"):
    store = PostgresAgentStore()
    store.reset_for_tests()
    memory = store.create_memory(
        agent_id="default",
        content=content,
        status="proposed",
        metadata={"source": "test"},
    )
    return store, memory


def test_confirm_memory_defaults_to_postgres_only(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(knowledge, "DATA_ROOT", tmp_path)
    monkeypatch.delenv("TOMMY_MEMORY_MARKDOWN_EXPORT_ON_CONFIRM", raising=False)
    agent_root = tmp_path / "default"
    agent_root.mkdir(parents=True)
    memory_file = agent_root / "MEMORY.md"
    memory_file.write_text("# MEMORY\n", encoding="utf-8")
    store, proposal = _store_with_proposal()

    result = knowledge.confirm_memory_impl(store, proposal["id"], "default")

    assert result["memory"]["status"] == "active"
    active = store.list_memories(agent_id="default", status="active")
    assert active[0]["content"] == proposal["content"]
    assert memory_file.read_text(encoding="utf-8") == "# MEMORY\n"


def test_memory_markdown_can_be_imported_as_seed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(knowledge, "DATA_ROOT", tmp_path)
    agent_root = tmp_path / "default"
    agent_root.mkdir(parents=True)
    (agent_root / "MEMORY.md").write_text(
        "# MEMORY\n\n- User prefers concise answers.\n- Project goal is Tommy parity.\n",
        encoding="utf-8",
    )
    store = PostgresAgentStore()
    store.reset_for_tests()

    result = knowledge.import_markdown_memory_seed_impl(store, agent_id="default")

    assert result["imported_count"] == 2
    active = store.list_memories(agent_id="default", status="active", limit=10)
    assert {item["content"] for item in active} == {
        "User prefers concise answers.",
        "Project goal is Tommy parity.",
    }
    assert all(item["metadata"]["source"] == "markdown_seed" for item in active)


def test_confirm_memory_exports_markdown_only_when_config_enabled(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(knowledge, "DATA_ROOT", tmp_path)
    monkeypatch.setenv("TOMMY_MEMORY_MARKDOWN_EXPORT_ON_CONFIRM", "true")
    agent_root = tmp_path / "default"
    agent_root.mkdir(parents=True)
    memory_file = agent_root / "MEMORY.md"
    memory_file.write_text("# MEMORY\n", encoding="utf-8")
    store, proposal = _store_with_proposal("User wants markdown backup")

    knowledge.confirm_memory_impl(store, proposal["id"], "default")

    assert "- User wants markdown backup" in memory_file.read_text(encoding="utf-8")


def test_active_memories_can_be_explicitly_exported_to_markdown(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(knowledge, "DATA_ROOT", tmp_path)
    store = PostgresAgentStore()
    store.reset_for_tests()
    store.create_memory(
        agent_id="default",
        content="Postgres active fact",
        status="active",
        metadata={"source": "test"},
    )

    result = knowledge.export_markdown_memories_impl(store, agent_id="default")

    exported = (tmp_path / "default" / "MEMORY.md").read_text(encoding="utf-8")
    assert result["exported_count"] == 1
    assert "- Postgres active fact" in exported
