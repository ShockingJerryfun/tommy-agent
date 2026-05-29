"""Workflow YAML loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None  # type: ignore[assignment]

from .models import WorkflowBudget, WorkflowPhaseSpec, WorkflowSpec


def load_workflow_spec(path: str | Path) -> WorkflowSpec:
    text = Path(path).read_text(encoding="utf-8")
    return load_workflow_spec_text(text)


def load_workflow_spec_text(text: str) -> WorkflowSpec:
    raw = yaml.safe_load(text) if yaml is not None else _load_simple_yaml(text)
    if not isinstance(raw, dict):
        raise ValueError("workflow spec must be a mapping")
    return workflow_spec_from_mapping(raw)


def workflow_spec_from_mapping(raw: dict[str, Any]) -> WorkflowSpec:
    budget_raw = raw.get("budget") if isinstance(raw.get("budget"), dict) else {}
    phases_raw = raw.get("phases")
    if not isinstance(phases_raw, list) or not phases_raw:
        raise ValueError("workflow spec requires at least one phase")
    phases = [_phase_from_mapping(item) for item in phases_raw]
    return WorkflowSpec(
        id=_required_string(raw, "id"),
        name=_required_string(raw, "name"),
        description=str(raw.get("description") or ""),
        max_concurrency=int(raw.get("max_concurrency") or 4),
        budget=WorkflowBudget(
            max_workers=int(budget_raw.get("max_workers") or 20),
            max_wall_seconds=float(budget_raw.get("max_wall_seconds") or 900.0),
        ),
        inputs=raw.get("inputs") if isinstance(raw.get("inputs"), dict) else {},
        phases=phases,
        metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    )


def _phase_from_mapping(raw: Any) -> WorkflowPhaseSpec:
    if not isinstance(raw, dict):
        raise ValueError("workflow phase must be a mapping")
    kind = _required_string(raw, "kind")
    if kind not in {"single", "fanout", "map", "reduce"}:
        raise ValueError(f"unsupported phase kind: {kind}")
    return WorkflowPhaseSpec(
        id=_required_string(raw, "id"),
        kind=kind,
        agent=_required_string(raw, "agent"),
        prompt=_required_string(raw, "prompt"),
        input_ref=str(raw.get("input") or ""),
        metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    )


def _required_string(raw: dict[str, Any], key: str) -> str:
    value = str(raw.get(key) or "").strip()
    if not value:
        raise ValueError(f"workflow spec field {key!r} is required")
    return value


def _load_simple_yaml(text: str) -> dict[str, Any]:
    """Conservative fallback parser for Tommy workflow YAML specs."""

    lines = text.splitlines()
    result: dict[str, Any] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        if line.startswith(" ") or ":" not in stripped:
            raise ValueError(f"unsupported workflow YAML line: {line}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value:
            result[key] = _parse_scalar(value)
            index += 1
            continue
        if key == "phases":
            phases, index = _parse_phase_list(lines, index + 1)
            result[key] = phases
        else:
            mapping, index = _parse_nested_mapping(lines, index + 1, indent=2)
            result[key] = mapping
    return result


def _parse_nested_mapping(
    lines: list[str],
    index: int,
    *,
    indent: int,
) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        current_indent = _indent(line)
        if current_indent < indent:
            break
        if current_indent != indent or ":" not in stripped:
            raise ValueError(f"unsupported workflow YAML line: {line}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value:
            mapping[key] = _parse_scalar(value)
            index += 1
            continue
        values, index = _parse_scalar_list(lines, index + 1, indent=indent + 2)
        mapping[key] = values
    return mapping, index


def _parse_scalar_list(
    lines: list[str],
    index: int,
    *,
    indent: int,
) -> tuple[list[Any], int]:
    values: list[Any] = []
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        current_indent = _indent(line)
        if current_indent < indent:
            break
        if current_indent != indent or not stripped.startswith("- "):
            raise ValueError(f"unsupported workflow YAML list item: {line}")
        values.append(_parse_scalar(stripped[2:].strip()))
        index += 1
    return values, index


def _parse_phase_list(lines: list[str], index: int) -> tuple[list[dict[str, Any]], int]:
    phases: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        current_indent = _indent(line)
        if current_indent < 2:
            break
        if current_indent == 2 and stripped.startswith("- "):
            if current is not None:
                phases.append(current)
            current = {}
            rest = stripped[2:].strip()
            if rest:
                key, value = rest.split(":", 1)
                current[key.strip()] = _parse_scalar(value.strip())
            index += 1
            continue
        if current is None or current_indent != 4 or ":" not in stripped:
            raise ValueError(f"unsupported workflow YAML phase line: {line}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "|":
            block, index = _parse_literal_block(lines, index + 1, indent=6)
            current[key] = block
            continue
        current[key] = _parse_scalar(value)
        index += 1
    if current is not None:
        phases.append(current)
    return phases, index


def _parse_literal_block(
    lines: list[str],
    index: int,
    *,
    indent: int,
) -> tuple[str, int]:
    block: list[str] = []
    while index < len(lines):
        line = lines[index]
        if line.strip() and _indent(line) < indent:
            break
        block.append(line[indent:] if len(line) >= indent else "")
        index += 1
    return "\n".join(block).strip(), index


def _parse_scalar(value: str) -> Any:
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


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))
