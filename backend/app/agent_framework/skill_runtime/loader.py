from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .metadata import normalize_skill_relative_path, parse_skill_markdown
from .types import LoadedSkill, LoadedSkillResource, SkillLoadResult, SkillResource

_LINKED_DIRS = ("assets", "references", "scripts", "templates")
_MARKDOWN_LINK_RE = re.compile(r"(?:!\[[^\]]*\]|\[[^\]]*\])\(([^)]+)\)")


class SkillLoader:
    def __init__(self, skills_root: str | Path) -> None:
        self._skills_root = Path(skills_root)

    def load_selected(
        self,
        selected: Iterable[Any],
        *,
        detail: str = "excerpt",
        char_budget: int = 4000,
    ) -> SkillLoadResult:
        remaining = max(0, int(char_budget))
        loaded: list[LoadedSkill] = []
        diagnostics: list[dict[str, str]] = []
        linked_files: list[str] = []
        resources: list[SkillResource] = []

        for item in selected:
            row = _selection_payload(item)
            relative_path = str(row.get("relative_path") or row.get("path") or "")
            try:
                skill = self._load_one(
                    relative_path,
                    fallback_name=str(row.get("name") or ""),
                    detail=detail,
                    char_budget=remaining,
                )
            except Exception as exc:  # noqa: BLE001 - report per-skill diagnostics and continue.
                diagnostics.append(
                    {
                        "path": relative_path,
                        "severity": "error",
                        "message": str(exc),
                    }
                )
                continue

            loaded.append(skill)
            remaining = max(0, remaining - skill.injected_chars)
            linked_files.extend(skill.linked_files)
            resources.extend(skill.resources)

        return SkillLoadResult(
            skills=loaded,
            injected_chars=sum(skill.injected_chars for skill in loaded),
            linked_files=sorted(dict.fromkeys(linked_files)),
            resources=_dedupe_resources(resources),
            diagnostics=diagnostics,
        )

    def load(
        self,
        relative_path: str,
        *,
        detail: str = "full",
        char_budget: int = 4000,
    ) -> SkillLoadResult:
        return self.load_selected(
            [{"relative_path": relative_path}],
            detail=detail,
            char_budget=char_budget,
        )

    def load_resource(
        self,
        relative_path: str,
        *,
        char_budget: int = 4000,
    ) -> LoadedSkillResource:
        path, resolved = self._resolve_resource_path(relative_path)
        content = path.read_text(encoding="utf-8", errors="replace")
        truncated = char_budget >= 0 and len(content) > char_budget
        return LoadedSkillResource(
            resource=_resource_for_path(self._skills_root.resolve(), path, stat_path=resolved),
            content=_truncate(content, char_budget),
            truncated=truncated,
        )

    def _load_one(
        self,
        relative_path: str,
        *,
        fallback_name: str,
        detail: str,
        char_budget: int,
    ) -> LoadedSkill:
        normalized = normalize_skill_relative_path(relative_path)
        path = (self._skills_root / normalized).resolve()
        root = self._skills_root.resolve()
        if root not in path.parents and path != root:
            raise ValueError(f"unsafe skill path: {relative_path}")
        if not path.exists():
            raise FileNotFoundError(f"skill not found: {normalized}")

        text = path.read_text(encoding="utf-8", errors="replace")
        document = parse_skill_markdown(text, source_path=normalized)
        _validate_markdown_links(document.body)

        resources = tuple(_discover_resources(root, path.parent))
        linked_files = tuple(resource.relative_path for resource in resources)
        full = document.body
        summary = document.metadata.description or ""
        excerpt = _truncate(full, char_budget)
        metadata_summary = _metadata_summary(
            name=document.metadata.name or fallback_name or path.parent.name,
            relative_path=normalized,
            document=document,
        )
        if detail == "full":
            injected = full
        elif detail == "summary":
            injected = summary
        elif detail == "metadata":
            injected = metadata_summary
        else:
            injected = excerpt
        injected = _truncate(injected, char_budget)
        return LoadedSkill(
            name=document.metadata.name or fallback_name or path.parent.name,
            relative_path=normalized,
            summary=summary,
            excerpt=excerpt,
            full=full,
            injected=injected,
            injected_chars=len(injected),
            linked_files=linked_files,
            resources=resources,
        )

    def _resolve_resource_path(self, relative_path: str) -> tuple[Path, Path]:
        root = self._skills_root.resolve()
        normalized = _normalize_resource_relative_path(relative_path)
        path = root / normalized
        resolved = path.resolve()
        _ensure_contained(root, resolved, f"unsafe resource path: {relative_path}")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"resource not found: {normalized}")
        _resource_kind_from_relative_path(normalized)
        return path, resolved


def _selection_payload(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    if hasattr(item, "row") and isinstance(item.row, dict):
        return {
            "name": getattr(item, "name", ""),
            "relative_path": getattr(item, "relative_path", ""),
        }
    return dict(getattr(item, "__dict__", {}))


def _discover_resources(root: Path, skill_dir: Path) -> list[SkillResource]:
    resources: list[SkillResource] = []
    for dirname in _LINKED_DIRS:
        directory = skill_dir / dirname
        if not directory.exists():
            continue
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            resolved = path.resolve()
            _ensure_contained(root, resolved, f"unsafe linked file path: {path}")
            resources.append(_resource_for_path(root, path, stat_path=resolved))
    return sorted(resources, key=lambda resource: resource.relative_path)


def _resource_for_path(root: Path, path: Path, *, stat_path: Path | None = None) -> SkillResource:
    relative_path = path.relative_to(root).as_posix()
    return SkillResource(
        relative_path=relative_path,
        kind=_resource_kind_from_relative_path(relative_path),
        size_bytes=(stat_path or path).stat().st_size,
    )


def _dedupe_resources(resources: list[SkillResource]) -> list[SkillResource]:
    by_path = {resource.relative_path: resource for resource in resources}
    return [by_path[path] for path in sorted(by_path)]


def _normalize_resource_relative_path(relative_path: str) -> str:
    value = relative_path.replace("\\", "/").strip()
    path = Path(value)
    if not value or path.is_absolute() or any(part in ("", "..") for part in path.parts):
        raise ValueError(f"unsafe resource path: {relative_path}")
    return value


def _resource_kind_from_relative_path(relative_path: str) -> str:
    parts = relative_path.split("/")
    for dirname in _LINKED_DIRS:
        if dirname in parts:
            return dirname
    raise ValueError(f"not a skill resource path: {relative_path}")


def _ensure_contained(root: Path, path: Path, message: str) -> None:
    if root not in path.parents and path != root:
        raise ValueError(message)


def _validate_markdown_links(body: str) -> None:
    for match in _MARKDOWN_LINK_RE.finditer(body):
        target = match.group(1).split("#", 1)[0].split("?", 1)[0].strip()
        if not target or "://" in target or target.startswith("#"):
            continue
        normalized = target.replace("\\", "/")
        parts = [part for part in normalized.split("/") if part]
        if parts and parts[0] in _LINKED_DIRS and ".." in parts:
            raise ValueError(f"unsafe linked asset path: {target}")


def _metadata_summary(*, name: str, relative_path: str, document: Any) -> str:
    metadata = document.metadata
    lines = [f"Skill: {name}", f"Path: {relative_path}"]
    if metadata.description:
        lines.append(f"Description: {metadata.description}")
    if metadata.required_tools:
        lines.append("Required tools: " + ", ".join(metadata.required_tools))
    if metadata.triggers:
        lines.append("Triggers: " + ", ".join(metadata.triggers))
    if metadata.domains:
        lines.append("Domains: " + ", ".join(metadata.domains))
    if metadata.platforms:
        lines.append("Platforms: " + ", ".join(metadata.platforms))
    return "\n".join(lines)


def _truncate(value: str, char_budget: int) -> str:
    if char_budget <= 0:
        return ""
    if len(value) <= char_budget:
        return value
    if char_budget <= 3:
        return "." * char_budget
    return value[: char_budget - 3].rstrip() + "..."
