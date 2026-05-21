from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..skills_forge.activator import get_default_skill_activator
from .indexer import SkillIndexer
from .loader import SkillLoader
from .resolver import SkillResolver

logger = logging.getLogger(__name__)


class SkillContextAssembler:
    """Build the prompt-facing view of indexed and selected skills."""

    def __init__(
        self,
        *,
        store: Any,
        activator: Any | None = None,
        available_tools: Iterable[str] | None = None,
        tool_registry: Any | None = None,
    ) -> None:
        self._store = store
        self._activator = activator
        self._available_tools = None if available_tools is None else set(available_tools)
        self._tool_registry = tool_registry

    def build(
        self,
        *,
        agent_id: str,
        query: str,
        skills_root: str | Path,
    ) -> dict[str, Any]:
        root = Path(skills_root)
        diagnostics: list[dict[str, str]] = []
        activator = self._resolve_activator()

        if root.exists():
            try:
                sync_result = SkillIndexer(
                    store=self._store,
                    embedder=getattr(activator, "embedder", None),
                ).sync(agent_id, root)
                diagnostics.extend(sync_result.get("diagnostics") or [])
            except Exception as exc:  # noqa: BLE001 - skill indexing must not break a turn.
                diagnostics.append(
                    {
                        "path": "",
                        "severity": "error",
                        "message": f"skill index sync failed: {exc}",
                    }
                )

        rows = self._list_active_skill_rows(agent_id)
        resolver = SkillResolver(
            catalog_rows=rows,
            activator=activator,
            available_tools=self._resolve_available_tools(),
        )
        resolution = resolver.resolve(query, agent_id=agent_id)
        load_result = SkillLoader(root).load_selected(resolution.selected, char_budget=3600)
        diagnostics.extend(resolution.diagnostics)
        diagnostics.extend(load_result.diagnostics)
        resources_by_skill = {
            skill.relative_path: [_resource_payload(resource) for resource in skill.resources]
            for skill in load_result.skills
        }

        return {
            "available_index": _available_skill_index_markdown(rows),
            "selected_markdown": _selected_skills_markdown(load_result.skills),
            "activation": {
                "candidates": [_candidate_payload(row) for row in _candidate_rows(rows)],
                "selected": [
                    {
                        "skill_id": skill.row.get("id") or skill.row.get("skill_id"),
                        "name": skill.name,
                        "relative_path": skill.relative_path,
                        "score": skill.score,
                        "reason_codes": list(skill.reason_codes),
                        "required_tools": list(skill.required_tools),
                        "resources": resources_by_skill.get(skill.relative_path, []),
                    }
                    for skill in resolution.selected
                ],
                "diagnostics": diagnostics,
                "injected_chars": load_result.injected_chars,
                "linked_files": list(load_result.linked_files),
                "resources": [_resource_payload(resource) for resource in load_result.resources],
            },
        }

    def _resolve_activator(self) -> Any | None:
        if self._activator is not None:
            return self._activator
        try:
            return get_default_skill_activator(self._store)
        except Exception as exc:  # noqa: BLE001 - lexical skill matching remains available.
            logger.debug("Unable to initialize default skill activator: %s", exc)
            return None

    def _list_active_skill_rows(self, agent_id: str) -> list[dict[str, Any]]:
        try:
            catalog = self._store.skill_catalog
            rows = catalog.list_skills(agent_id=agent_id, status="active", limit=100)
        except Exception as exc:  # noqa: BLE001 - skill catalog issues should not break context.
            logger.warning("Unable to list active skill rows for agent %s: %s", agent_id, exc)
            return []
        return [dict(row) for row in rows]

    def _resolve_available_tools(self) -> set[str] | None:
        if self._available_tools is not None:
            return set(self._available_tools)

        if self._tool_registry is not None:
            return _tool_names_from_registry(self._tool_registry)

        for attr in ("tool_registry", "registry"):
            try:
                registry = getattr(self._store, attr, None)
            except Exception as exc:  # noqa: BLE001 - broken injected inventory means unknown.
                logger.debug("Unable to read tool inventory attribute %s: %s", attr, exc)
                return None
            names = _tool_names_from_registry(registry)
            if registry is not None:
                return names

        return None


def _available_skill_index_markdown(rows: list[dict[str, Any]], *, limit: int = 8) -> str:
    if not rows:
        return "No active skills indexed."
    lines = []
    for row in _candidate_rows(rows)[:limit]:
        name = str(row.get("name") or row.get("relative_path") or "unnamed")
        description = str(row.get("description") or row.get("relative_path") or "").strip()
        if description:
            lines.append(f"- {name}: {description}")
        else:
            lines.append(f"- {name}")
    return "\n".join(lines)


def _selected_skills_markdown(skills: list[Any]) -> str:
    lines: list[str] = []
    for skill in skills:
        lines.append(f"## {skill.name}")
        if skill.summary:
            lines.append(skill.summary)
        lines.append(f"Path: {skill.relative_path}")
        if skill.linked_files:
            lines.append("Linked files:")
            lines.extend(f"- {path}" for path in skill.linked_files)
        if skill.injected:
            lines.append("")
            lines.append(skill.injected)
        lines.append("")
    return "\n".join(lines).strip()


def _candidate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("name") or "").lower(),
            str(row.get("relative_path") or ""),
        ),
    )


def _candidate_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row.get("name"),
        "relative_path": row.get("relative_path"),
        "description": row.get("description", ""),
        "status": row.get("status", "active"),
    }


def _resource_payload(resource: Any) -> dict[str, Any]:
    return {
        "relative_path": str(getattr(resource, "relative_path", "")),
        "kind": str(getattr(resource, "kind", "")),
        "size_bytes": int(getattr(resource, "size_bytes", 0) or 0),
    }


def _tool_names_from_registry(registry: Any | None) -> set[str] | None:
    if registry is None:
        return None
    try:
        if isinstance(registry, (list, tuple, set)):
            return {str(name) for name in registry if str(name)}
        by_name = getattr(registry, "by_name", None)
        if isinstance(by_name, dict):
            return {str(name) for name in by_name if str(name)}
        tools = getattr(registry, "tools", None)
        if tools is None:
            schemas = getattr(registry, "schemas", None)
            tools = schemas() if callable(schemas) else None
        if tools is None:
            return None
        return {
            str(name)
            for tool in tools
            if (name := getattr(tool, "name", None)) is not None and str(name)
        }
    except Exception as exc:  # noqa: BLE001 - keep diagnostics disabled when inventory cannot be read.
        logger.debug("Unable to read tool names from registry: %s", exc)
        return None
