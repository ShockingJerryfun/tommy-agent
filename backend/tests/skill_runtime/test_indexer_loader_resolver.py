from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent_framework.skill_runtime.context import SkillContextAssembler
from app.agent_framework.skill_runtime.indexer import SkillIndexer
from app.agent_framework.skill_runtime.loader import SkillLoader
from app.agent_framework.skill_runtime.resolver import SkillResolver
from app.agent_framework.skills_forge.catalog import SkillCatalog


class _FakeSkillCatalogRepo:
    def __init__(self) -> None:
        self.registered: list[dict] = []
        self.embeddings: list[dict] = []
        self.status_changes: list[tuple[str, str]] = []

    def register_skill(self, **kwargs):
        existing = next(
            (
                row
                for row in self.registered
                if row.get("agent_id") == kwargs.get("agent_id")
                and row.get("relative_path") == kwargs.get("relative_path")
            ),
            None,
        )
        if existing is None:
            row = {"id": f"skill-{len(self.registered) + 1}", **kwargs}
            self.registered.append(row)
            return row
        existing.update({key: value for key, value in kwargs.items() if key != "status"})
        return dict(existing)

    def list_skills(self, *, agent_id: str, status: str | None = None, limit: int = 100):
        rows = [row for row in self.registered if row.get("agent_id") == agent_id]
        if status is not None:
            rows = [row for row in rows if row.get("status", "active") == status]
        return rows[:limit]

    def set_status(self, skill_id: str, status: str):
        self.status_changes.append((skill_id, status))
        for row in self.registered:
            if row["id"] == skill_id:
                row["status"] = status
                return dict(row)
        return None

    def update_signature_embedding(self, skill_id: str, *, embedding, model: str):
        self.embeddings.append({"skill_id": skill_id, "embedding": embedding, "model": model})


class _FakeStore:
    def __init__(self) -> None:
        self.skill_catalog = _FakeSkillCatalogRepo()


class _FakeEmbedder:
    model = "fake-1536"

    def embed(self, text: str):  # noqa: ARG002
        return [0.01] * 1536


def _write_skill(root: Path, relative_path: str, content: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_indexer_sync_registers_active_skills_with_shared_metadata(tmp_path):
    _write_skill(
        tmp_path,
        "browser/SKILL.md",
        """---
name: browser
description: Browser automation helpers.
required_tools:
  - browser.open
  - browser.click
triggers:
  - inspect localhost
user_invocable: true
metadata:
  hermes:
    role: browser-worker
---

# Browser
""",
    )
    store = _FakeStore()

    result = SkillIndexer(store=store).sync("agent-1", tmp_path)

    assert result["registered"] == 1
    assert result["diagnostics"] == []
    assert len(store.skill_catalog.registered) == 1
    registered = store.skill_catalog.registered[0]
    assert registered["agent_id"] == "agent-1"
    assert registered["name"] == "browser"
    assert registered["relative_path"] == "browser/SKILL.md"
    assert registered["description"] == "Browser automation helpers."
    assert registered["status"] == "active"
    assert registered["signature"].startswith("description=Browser automation helpers.")
    assert registered["tool_chain"] == ["browser.open", "browser.click"]
    assert registered["metadata"]["normalized"]["required_tools"] == [
        "browser.open",
        "browser.click",
    ]
    assert registered["metadata"]["normalized"]["hermes"] == {"role": "browser-worker"}
    assert registered["metadata"]["source"]["relative_path"] == "browser/SKILL.md"
    assert registered["metadata"]["diagnostics"] == []


def test_indexer_reactivates_existing_catalog_row_and_updates_embedding(tmp_path):
    _write_skill(
        tmp_path,
        "browser/SKILL.md",
        """---
name: browser
description: Browser automation helpers.
---

# Browser
""",
    )
    store = _FakeStore()
    store.skill_catalog.registered.append(
        {
            "id": "skill-existing",
            "agent_id": "agent-1",
            "name": "browser",
            "relative_path": "browser/SKILL.md",
            "description": "",
            "signature": "",
            "tool_chain": [],
            "status": "shadow",
            "metadata": {},
        }
    )

    result = SkillIndexer(store=store, embedder=_FakeEmbedder()).sync("agent-1", tmp_path)

    assert result["registered"] == 1
    assert result["skills"][0]["id"] == "skill-existing"
    assert result["skills"][0]["status"] == "active"
    assert store.skill_catalog.status_changes == [("skill-existing", "active")]
    assert store.skill_catalog.embeddings == [
        {
            "skill_id": "skill-existing",
            "embedding": [0.01] * 1536,
            "model": "fake-1536",
        }
    ]


def test_indexer_sync_returns_diagnostics_for_invalid_skills_and_continues(tmp_path):
    _write_skill(
        tmp_path,
        "valid/SKILL.md",
        """---
name: valid
required_tools: [shell]
---

# Valid
""",
    )
    _write_skill(tmp_path, "invalid/SKILL.md", "# Missing metadata name\n")
    store = _FakeStore()

    result = SkillIndexer(store=store).sync("agent-1", tmp_path)

    assert result["registered"] == 1
    assert [item["path"] for item in result["diagnostics"]] == ["invalid/SKILL.md"]
    assert result["diagnostics"][0]["severity"] == "error"
    assert "name" in result["diagnostics"][0]["message"]
    assert [item["relative_path"] for item in store.skill_catalog.registered] == [
        "valid/SKILL.md",
    ]


def test_indexer_rejects_symlinked_skill_that_escapes_root(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    _write_skill(
        outside,
        "SKILL.md",
        """---
name: outside
---

# Outside
""",
    )
    skill_dir = tmp_path / "skills" / "escaped"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").symlink_to(outside / "SKILL.md")
    store = _FakeStore()

    result = SkillIndexer(store=store).sync("agent-1", tmp_path / "skills")

    assert result["registered"] == 0
    assert store.skill_catalog.registered == []
    assert result["diagnostics"] == [
        {
            "path": "escaped/SKILL.md",
            "severity": "error",
            "message": "unsafe skill path escapes skills root: escaped/SKILL.md",
        }
    ]


def test_indexer_retires_active_rows_whose_skill_file_disappeared(tmp_path):
    store = _FakeStore()
    store.skill_catalog.registered.append(
        {
            "id": "skill-stale",
            "agent_id": "agent-1",
            "name": "stale",
            "relative_path": "stale/SKILL.md",
            "status": "active",
            "metadata": {"source": {"relative_path": "stale/SKILL.md"}},
        }
    )

    result = SkillIndexer(store=store).sync("agent-1", tmp_path)

    assert store.skill_catalog.status_changes == [("skill-stale", "retired")]
    assert result["diagnostics"] == [
        {
            "path": "stale/SKILL.md",
            "severity": "warning",
            "message": "retired indexed skill because SKILL.md is no longer present",
        }
    ]


def test_indexer_retires_legacy_rows_without_source_metadata(tmp_path):
    store = _FakeStore()
    store.skill_catalog.registered.append(
        {
            "id": "skill-legacy",
            "agent_id": "agent-1",
            "name": "legacy",
            "relative_path": "legacy/SKILL.md",
            "status": "active",
            "metadata": {},
        }
    )

    result = SkillIndexer(store=store).sync("agent-1", tmp_path)

    assert store.skill_catalog.status_changes == [("skill-legacy", "retired")]
    assert result["diagnostics"][0]["path"] == "legacy/SKILL.md"


def test_skill_catalog_list_skills_uses_shared_markdown_parser(tmp_path):
    _write_skill(
        tmp_path / "agent-1" / "skills",
        "quoted/SKILL.md",
        """---
name: 'quoted skill'
description: 'single quoted description'
---

# Quoted
""",
    )

    summaries = SkillCatalog(agent_id="agent-1", root=tmp_path, store=_FakeStore()).list_skills()

    assert summaries[0].name == "quoted skill"
    assert summaries[0].description == "single quoted description"


class _FakeActivator:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def recall(self, **kwargs):
        return self.rows


def test_resolver_selects_active_skills_with_mentions_keywords_semantic_and_metrics():
    rows = [
        {
            "id": "retired",
            "name": "old-browser",
            "relative_path": "old-browser/SKILL.md",
            "description": "Browser automation.",
            "signature": "",
            "tool_chain": [],
            "status": "retired",
            "metadata": {"normalized": {"triggers": ["inspect"], "domains": ["browser"]}},
            "metrics": {"success_rate": 1.0},
        },
        {
            "id": "browser",
            "name": "browser",
            "relative_path": "browser/SKILL.md",
            "description": "Inspect localhost pages.",
            "signature": "",
            "tool_chain": ["browser.open"],
            "metadata": {"normalized": {"triggers": ["inspect localhost"], "domains": ["web"]}},
            "metrics": {"success_rate": 0.95, "failure_count": 0},
        },
        {
            "id": "docs",
            "name": "docs",
            "relative_path": "docs/SKILL.md",
            "description": "Document editing.",
            "signature": "",
            "tool_chain": ["docs.write"],
            "status": "active",
            "metadata": {"normalized": {"triggers": ["write doc"], "domains": ["documents"]}},
            "metrics": {"success_rate": 0.2, "failure_count": 8},
        },
    ]
    semantic_rows = [
        {
            "id": "playwright",
            "name": "playwright",
            "relative_path": "playwright/SKILL.md",
            "description": "Browser tests.",
            "signature": "",
            "tool_chain": [],
            "status": "active",
            "similarity": 0.8,
            "metadata": {"normalized": {"triggers": ["browser test"], "domains": ["web"]}},
            "metrics": {"success_rate": 0.7},
        },
        rows[0],
    ]

    result = SkillResolver(
        catalog_rows=rows,
        activator=_FakeActivator(semantic_rows),
        available_tools={"browser.open"},
    ).resolve(
        "Use browser/SKILL.md to inspect localhost and run a browser test",
        agent_id="agent-1",
    )

    assert [skill.relative_path for skill in result.selected] == [
        "browser/SKILL.md",
        "playwright/SKILL.md",
    ]
    assert result.selected[0].score > result.selected[1].score
    assert "explicit_path" in result.selected[0].reason_codes
    assert "semantic_match" in result.selected[1].reason_codes
    assert all(skill.status == "active" for skill in result.selected)
    assert result.diagnostics == []


def test_resolver_does_not_select_unrelated_skills_for_generic_query():
    rows = [
        {
            "name": "xhs-content",
            "relative_path": "xhs-content/SKILL.md",
            "description": "Plan Xiaohongshu posts.",
            "metadata": {"normalized": {"triggers": ["小红书"], "domains": ["content"]}},
            "metrics": {"success_rate": 1.0},
        }
    ]

    result = SkillResolver(catalog_rows=rows).resolve("hello there")

    assert result.selected == []
    assert result.diagnostics == []


def test_resolver_only_reports_missing_tools_when_tool_inventory_is_known():
    rows = [
        {
            "name": "browser",
            "relative_path": "browser/SKILL.md",
            "description": "Inspect localhost pages.",
            "tool_chain": ["browser.open"],
            "metadata": {"normalized": {"triggers": ["inspect localhost"]}},
        }
    ]

    unknown_inventory = SkillResolver(catalog_rows=rows).resolve("inspect localhost")
    known_inventory = SkillResolver(catalog_rows=rows, available_tools=[]).resolve(
        "inspect localhost"
    )

    assert unknown_inventory.selected
    assert unknown_inventory.diagnostics == []
    assert known_inventory.diagnostics == [
        {
            "path": "browser/SKILL.md",
            "severity": "warning",
            "message": "missing required tools: browser.open",
        }
    ]


def test_resolver_orders_ties_by_name_and_path_and_limits_to_three():
    rows = [
        {
            "name": "zeta",
            "relative_path": "zeta/SKILL.md",
            "description": "Same match.",
            "metadata": {"normalized": {"triggers": ["same"], "domains": []}},
        },
        {
            "name": "alpha",
            "relative_path": "b/SKILL.md",
            "description": "Same match.",
            "metadata": {"normalized": {"triggers": ["same"], "domains": []}},
        },
        {
            "name": "alpha",
            "relative_path": "a/SKILL.md",
            "description": "Same match.",
            "metadata": {"normalized": {"triggers": ["same"], "domains": []}},
        },
        {
            "name": "middle",
            "relative_path": "middle/SKILL.md",
            "description": "Same match.",
            "metadata": {"normalized": {"triggers": ["same"], "domains": []}},
        },
    ]

    result = SkillResolver(catalog_rows=rows).resolve("same")

    assert [(skill.name, skill.relative_path) for skill in result.selected] == [
        ("alpha", "a/SKILL.md"),
        ("alpha", "b/SKILL.md"),
        ("middle", "middle/SKILL.md"),
    ]


def test_loader_loads_selected_skills_with_default_excerpt_budget_and_linked_files(tmp_path):
    _write_skill(
        tmp_path,
        "browser/SKILL.md",
        """---
name: browser
description: Browser automation helpers.
---

# Browser

Use the browser to inspect pages.

This line is intentionally long enough to be trimmed by a tiny budget.
""",
    )
    _write_skill(tmp_path, "browser/references/guide.md", "# Guide\n")
    _write_skill(tmp_path, "browser/templates/prompt.md", "Prompt\n")
    _write_skill(tmp_path, "browser/assets/example.txt", "asset\n")
    _write_skill(tmp_path, "browser/scripts/run.sh", "echo run\n")

    result = SkillLoader(tmp_path).load_selected(
        [{"name": "browser", "relative_path": "browser/SKILL.md"}],
        char_budget=40,
    )

    assert result.injected_chars <= 40
    assert result.skills[0].summary == "Browser automation helpers."
    assert result.skills[0].full.startswith("# Browser")
    assert result.skills[0].injected == result.skills[0].excerpt
    assert result.skills[0].excerpt.endswith("...")
    assert result.linked_files == [
        "browser/assets/example.txt",
        "browser/references/guide.md",
        "browser/scripts/run.sh",
        "browser/templates/prompt.md",
    ]
    assert [
        (resource.relative_path, resource.kind, resource.size_bytes)
        for resource in result.skills[0].resources
    ] == [
        ("browser/assets/example.txt", "assets", 6),
        ("browser/references/guide.md", "references", 8),
        ("browser/scripts/run.sh", "scripts", 9),
        ("browser/templates/prompt.md", "templates", 7),
    ]
    assert result.resources == list(result.skills[0].resources)
    assert "asset" not in result.skills[0].injected


def test_loader_load_resource_reads_allowed_resource_with_budget(tmp_path):
    _write_skill(
        tmp_path,
        "browser/SKILL.md",
        """---
name: browser
description: Browser automation helpers.
---

# Browser
""",
    )
    _write_skill(tmp_path, "browser/references/guide.md", "abcdef")

    loaded = SkillLoader(tmp_path).load_resource(
        "browser/references/guide.md",
        char_budget=4,
    )

    assert loaded.resource.relative_path == "browser/references/guide.md"
    assert loaded.resource.kind == "references"
    assert loaded.resource.size_bytes == 6
    assert loaded.content == "a..."
    assert loaded.truncated is True


def test_loader_load_resource_rejects_parent_traversal(tmp_path):
    _write_skill(tmp_path, "browser/references/guide.md", "abcdef")

    with pytest.raises(ValueError, match="unsafe resource path"):
        SkillLoader(tmp_path).load_resource("browser/references/../secret.txt")


def test_loader_load_resource_rejects_symlink_that_escapes_root(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("secret", encoding="utf-8")
    resource_dir = tmp_path / "browser" / "references"
    resource_dir.mkdir(parents=True)
    (resource_dir / "secret.md").symlink_to(outside)

    with pytest.raises(ValueError, match="unsafe resource path"):
        SkillLoader(tmp_path).load_resource("browser/references/secret.md")


def test_loader_metadata_detail_injects_no_body_content(tmp_path):
    _write_skill(
        tmp_path,
        "browser/SKILL.md",
        """---
name: browser
description: Browser automation helpers.
required_tools: [browser.open]
triggers:
  - inspect localhost
domains: [frontend]
---

# Browser Body

Do not inject this body in metadata mode.
""",
    )

    result = SkillLoader(tmp_path).load_selected(
        [{"name": "browser", "relative_path": "browser/SKILL.md"}],
        detail="metadata",
    )

    assert result.skills[0].injected == "\n".join(
        [
            "Skill: browser",
            "Path: browser/SKILL.md",
            "Description: Browser automation helpers.",
            "Required tools: browser.open",
            "Triggers: inspect localhost",
            "Domains: frontend",
        ]
    )
    assert "Do not inject this body" not in result.skills[0].injected


def test_loader_rejects_unsafe_asset_paths(tmp_path):
    _write_skill(
        tmp_path,
        "bad/SKILL.md",
        """---
name: bad
description: Bad asset.
---

# Bad

![escape](assets/../secret.txt)
""",
    )

    result = SkillLoader(tmp_path).load_selected(
        [{"name": "bad", "relative_path": "bad/SKILL.md"}],
    )

    assert result.skills == []
    assert result.diagnostics == [
        {
            "path": "bad/SKILL.md",
            "severity": "error",
            "message": "unsafe linked asset path: assets/../secret.txt",
        }
    ]


def test_context_assembler_uses_semantic_activator_fallback(tmp_path):
    _write_skill(
        tmp_path,
        "semantic/SKILL.md",
        """---
name: semantic-skill
description: Specialized vector-only workflow.
---

# Semantic Skill

This body appears only when semantic recall selects the skill.
""",
    )
    store = _FakeStore()
    semantic_row = {
        "id": "semantic",
        "name": "semantic-skill",
        "relative_path": "semantic/SKILL.md",
        "description": "Specialized vector-only workflow.",
        "signature": "",
        "tool_chain": [],
        "status": "active",
        "similarity": 0.9,
        "metadata": {"normalized": {"triggers": [], "domains": []}},
    }

    result = SkillContextAssembler(
        store=store,
        activator=_FakeActivator([semantic_row]),
    ).build(
        agent_id="agent-1",
        query="a request understood through embeddings",
        skills_root=tmp_path,
    )

    assert result["activation"]["selected"][0]["relative_path"] == "semantic/SKILL.md"
    assert result["activation"]["selected"][0]["reason_codes"] == ["semantic_match"]
    assert "This body appears only when semantic recall selects" in result["selected_markdown"]


def test_context_assembler_passes_known_tool_inventory_without_false_missing(tmp_path):
    _write_skill(
        tmp_path,
        "browser/SKILL.md",
        """---
name: browser
description: Inspect localhost pages.
required_tools: [browser.open]
triggers: [inspect localhost]
---

# Browser
""",
    )
    store = _FakeStore()

    result = SkillContextAssembler(
        store=store,
        tool_registry=SimpleNamespace(tools=[SimpleNamespace(name="browser.open")]),
    ).build(agent_id="agent-1", query="inspect localhost", skills_root=tmp_path)

    assert result["activation"]["selected"][0]["relative_path"] == "browser/SKILL.md"
    assert result["activation"]["diagnostics"] == []


def test_context_assembler_persists_resource_manifest_in_activation(tmp_path):
    _write_skill(
        tmp_path,
        "browser/SKILL.md",
        """---
name: browser
description: Inspect localhost pages.
triggers: [inspect localhost]
---

# Browser
""",
    )
    _write_skill(tmp_path, "browser/references/guide.md", "# Guide\n")
    store = _FakeStore()

    result = SkillContextAssembler(store=store).build(
        agent_id="agent-1",
        query="inspect localhost",
        skills_root=tmp_path,
    )

    assert result["activation"]["resources"] == [
        {
            "relative_path": "browser/references/guide.md",
            "kind": "references",
            "size_bytes": 8,
        }
    ]
    assert result["activation"]["selected"][0]["resources"] == result["activation"]["resources"]


def test_context_assembler_reports_missing_tools_when_inventory_is_known(tmp_path):
    _write_skill(
        tmp_path,
        "browser/SKILL.md",
        """---
name: browser
description: Inspect localhost pages.
required_tools: [browser.open]
triggers: [inspect localhost]
---

# Browser
""",
    )
    store = _FakeStore()

    result = SkillContextAssembler(
        store=store,
        available_tools={"shell.run"},
    ).build(agent_id="agent-1", query="inspect localhost", skills_root=tmp_path)

    assert result["activation"]["diagnostics"] == [
        {
            "path": "browser/SKILL.md",
            "severity": "warning",
            "message": "missing required tools: browser.open",
        }
    ]


def test_context_assembler_keeps_tool_inventory_unknown_when_registry_unavailable(tmp_path):
    class BrokenRegistry:
        @property
        def tools(self):
            raise RuntimeError("registry unavailable")

    _write_skill(
        tmp_path,
        "browser/SKILL.md",
        """---
name: browser
description: Inspect localhost pages.
required_tools: [browser.open]
triggers: [inspect localhost]
---

# Browser
""",
    )
    store = _FakeStore()

    result = SkillContextAssembler(
        store=store,
        tool_registry=BrokenRegistry(),
    ).build(agent_id="agent-1", query="inspect localhost", skills_root=tmp_path)

    assert result["activation"]["selected"][0]["relative_path"] == "browser/SKILL.md"
    assert result["activation"]["diagnostics"] == []
