from __future__ import annotations

import posixpath
from pathlib import PurePosixPath
from typing import Any

from .types import SkillDocument, SkillMetadata

_LIST_FIELDS = (
    "required_tools",
    "triggers",
    "domains",
    "platforms",
    "safety_notes",
    "allowed_tools",
)


def normalize_skill_relative_path(path: str) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path must be a non-empty relative path")

    normalized_input = path.strip().replace("\\", "/")
    parsed = PurePosixPath(normalized_input)
    if parsed.is_absolute() or ".." in parsed.parts:
        raise ValueError(f"unsafe relative path: {path}")

    normalized = posixpath.normpath(normalized_input)
    if normalized in ("", "."):
        raise ValueError("path must be a non-empty relative path")
    return normalized


def parse_skill_markdown(markdown: str, *, source_path: str | None = None) -> SkillDocument:
    raw_frontmatter, body = _split_frontmatter(markdown)
    data = _parse_yaml_subset(raw_frontmatter) if raw_frontmatter is not None else {}

    normalized_source = normalize_skill_relative_path(source_path) if source_path else None
    metadata = SkillMetadata(
        name=_optional_string(data.get("name")),
        description=_optional_string(data.get("description")),
        source_path=normalized_source,
        required_tools=_string_tuple(data.get("required_tools")),
        triggers=_string_tuple(data.get("triggers")),
        domains=_string_tuple(data.get("domains")),
        platforms=_string_tuple(data.get("platforms")),
        safety_notes=_string_tuple(data.get("safety_notes")),
        allowed_tools=_string_tuple(data.get("allowed_tools")),
        user_invocable=_bool_value(data.get("user_invocable"), default=False),
        disable_model_invocation=_bool_value(data.get("disable_model_invocation"), default=False),
        hermes=_hermes_metadata(data),
    )
    return SkillDocument(
        metadata=metadata,
        body=body,
        signature_text=_signature_text(metadata),
    )


def _split_frontmatter(markdown: str) -> tuple[str | None, str]:
    if not markdown.startswith("---\n"):
        return None, markdown

    lines = markdown.splitlines(keepends=True)
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            frontmatter = "".join(lines[1:index])
            body = "".join(lines[index + 1 :])
            if body.startswith("\n"):
                body = body[1:]
            return frontmatter, body
    return None, markdown


def _parse_yaml_subset(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    parsed, _ = _parse_mapping(lines, 0, 0)
    return parsed


def _parse_mapping(lines: list[str], index: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        current_indent = _indent_width(line)
        if current_indent < indent:
            break
        if current_indent > indent:
            break

        stripped = line.strip()
        if stripped.startswith("- ") or ":" not in stripped:
            break

        key, raw_value = stripped.split(":", 1)
        raw_value = raw_value.strip()
        if raw_value:
            result[key] = _parse_scalar(raw_value)
            index += 1
            continue

        next_index = _next_content_line(lines, index + 1)
        if next_index is None or _indent_width(lines[next_index]) <= current_indent:
            result[key] = None
            index += 1
            continue

        if lines[next_index].strip().startswith("- "):
            result[key], index = _parse_list(lines, next_index, _indent_width(lines[next_index]))
        else:
            result[key], index = _parse_mapping(
                lines,
                next_index,
                _indent_width(lines[next_index]),
            )
    return result, index


def _parse_list(lines: list[str], index: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        current_indent = _indent_width(line)
        stripped = line.strip()
        if current_indent != indent or not stripped.startswith("- "):
            break

        result.append(_parse_scalar(stripped[2:].strip()))
        index += 1
    return result, index


def _parse_scalar(value: str) -> Any:
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item.strip()) for item in inner.split(",")]

    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if value in ("''", '""'):
        return ""
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value


def _indent_width(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _next_content_line(lines: list[str], index: int) -> int | None:
    while index < len(lines):
        if lines[index].strip():
            return index
        index += 1
    return None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return (str(value),)


def _bool_value(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _hermes_metadata(data: dict[str, Any]) -> dict[str, Any]:
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        return {}

    hermes = metadata.get("hermes")
    if not isinstance(hermes, dict):
        return {}

    return {str(key): _freeze_lists(value) for key, value in hermes.items()}


def _freeze_lists(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_freeze_lists(item) for item in value)
    if isinstance(value, dict):
        return {str(key): _freeze_lists(item) for key, item in value.items()}
    return value


def _signature_text(metadata: SkillMetadata) -> str:
    lines: list[str] = []
    _append_list(lines, "allowed_tools", metadata.allowed_tools)
    _append_optional(lines, "description", metadata.description)
    _append_bool(lines, "disable_model_invocation", metadata.disable_model_invocation)
    _append_list(lines, "domains", metadata.domains)
    _append_hermes(lines, metadata.hermes)
    _append_optional(lines, "name", metadata.name)
    _append_list(lines, "platforms", metadata.platforms)
    _append_list(lines, "required_tools", metadata.required_tools)
    _append_list(lines, "safety_notes", metadata.safety_notes)
    _append_optional(lines, "source_path", metadata.source_path)
    _append_list(lines, "triggers", metadata.triggers)
    _append_bool(lines, "user_invocable", metadata.user_invocable)
    return "\n".join(lines)


def _append_optional(lines: list[str], key: str, value: str | None) -> None:
    if value:
        lines.append(f"{key}={value}")


def _append_list(lines: list[str], key: str, value: tuple[str, ...]) -> None:
    if value:
        lines.append(f"{key}={','.join(value)}")


def _append_bool(lines: list[str], key: str, value: bool) -> None:
    lines.append(f"{key}={str(value).lower()}")


def _append_hermes(lines: list[str], hermes: dict[str, Any]) -> None:
    for key in sorted(hermes):
        value = hermes[key]
        if isinstance(value, tuple):
            rendered = ",".join(str(item) for item in value)
        else:
            rendered = str(value).lower() if isinstance(value, bool) else str(value)
        lines.append(f"hermes.{key}={rendered}")
