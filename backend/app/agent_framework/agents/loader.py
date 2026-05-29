"""Load AgentDefinition objects from built-ins and markdown files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..paths import DATA_ROOT
from ..tool_runtime import create_default_registry
from .definitions import (
    DEFAULT_MAX_TURNS,
    DEFAULT_MAX_WALL_SECONDS,
    DEFAULT_PERMISSION_MODE,
    AgentDefinition,
    built_in_agent_definitions,
)
from .registry import AgentRegistry


def load_agent_registry(
    *,
    agent_id: str = "default",
    workspace_dir: str | Path | None = None,
    data_root: str | Path | None = None,
    known_tool_names: set[str] | None = None,
) -> AgentRegistry:
    definitions = load_agent_definitions(
        agent_id=agent_id,
        workspace_dir=workspace_dir,
        data_root=data_root,
    )
    known_names = known_tool_names if known_tool_names is not None else _default_tool_names()
    return AgentRegistry(definitions, known_tool_names=known_names)


def load_agent_definitions(
    *,
    agent_id: str = "default",
    workspace_dir: str | Path | None = None,
    data_root: str | Path | None = None,
) -> list[AgentDefinition]:
    definitions: dict[str, AgentDefinition] = {
        definition.id: definition for definition in built_in_agent_definitions()
    }

    for path in _definition_paths(_data_agent_dir(data_root, agent_id)):
        definition = load_agent_markdown(path)
        definitions[definition.id] = definition

    if workspace_dir is not None:
        for path in _definition_paths(Path(workspace_dir) / ".tommy" / "agents"):
            definition = load_agent_markdown(path)
            definitions[definition.id] = definition

    return list(definitions.values())


def load_agent_markdown(path: Path) -> AgentDefinition:
    content = path.read_text(encoding="utf-8")
    header, system_prompt = _split_frontmatter(content)
    fallback_id = path.stem.strip()
    agent_id = str(header.get("id") or fallback_id).strip()
    title = str(header.get("title") or agent_id.replace("_", " ").title()).strip()
    return AgentDefinition(
        id=agent_id,
        title=title,
        description=str(header.get("description") or ""),
        system_prompt=system_prompt,
        tool_names=_string_tuple(header.get("tools")),
        disallowed_tool_names=_string_tuple(header.get("disallowed_tools")),
        max_turns=int(header.get("max_turns") or DEFAULT_MAX_TURNS),
        max_wall_seconds=float(header.get("max_wall_seconds") or DEFAULT_MAX_WALL_SECONDS),
        model=_optional_string(header.get("model")),
        permission_mode=str(header.get("permission_mode") or DEFAULT_PERMISSION_MODE),
        metadata=_metadata(header.get("metadata")),
    )


def _data_agent_dir(data_root: str | Path | None, agent_id: str) -> Path:
    root = Path(data_root) if data_root is not None else DATA_ROOT
    return root / agent_id / "agents"


def _definition_paths(directory: Path) -> list[Path]:
    if not directory.exists() or not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("*.md") if path.is_file())


def _split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, content.strip()

    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        raise ValueError("agent markdown frontmatter is missing closing delimiter")

    header = _parse_simple_frontmatter(lines[1:end_index])
    body = "\n".join(lines[end_index + 1 :]).strip()
    return header, body


def _parse_simple_frontmatter(lines: list[str]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_key = ""
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if not current_key:
                raise ValueError("frontmatter list item is missing a key")
            current = data.setdefault(current_key, [])
            if not isinstance(current, list):
                raise ValueError(f"frontmatter key {current_key!r} mixes scalar and list values")
            current.append(_parse_scalar(stripped[2:].strip()))
            continue
        if ":" not in stripped:
            raise ValueError(f"invalid frontmatter line: {stripped}")
        key, value = stripped.split(":", 1)
        current_key = key.strip()
        if not current_key:
            raise ValueError("frontmatter key must be non-empty")
        value = value.strip()
        data[current_key] = [] if value == "" else _parse_scalar(value)
    return data


def _parse_scalar(value: str) -> Any:
    if not value:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value)
    raise ValueError("agent tool fields must be strings or lists")


def _metadata(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _default_tool_names() -> set[str]:
    return {tool.name for tool in create_default_registry().tools}
