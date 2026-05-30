"""Canonical runtime context for child-agent runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_LINEAGE_FIELDS = (
    "parent_session_id",
    "parent_run_id",
    "parent_agent_id",
    "subagent_role",
    "team_id",
    "team_task_id",
    "workflow_run_id",
    "phase_run_id",
    "workflow_phase_id",
)
_RUNTIME_FIELDS = (
    "approval_id",
    "frontend_settings",
    "working_directory",
    "command_scope",
    "model",
    "permission_mode",
    "budget",
    "depth",
    "is_child",
)
_INHERITABLE_METADATA = {
    "team_id",
    "team_task_id",
    "workflow_run_id",
    "phase_run_id",
    "workflow_phase_id",
    "approval_id",
    "model",
    "permission_mode",
    "budget",
}
_OVERRIDABLE_FIELDS = {
    "team_id",
    "team_task_id",
    "workflow_run_id",
    "phase_run_id",
    "workflow_phase_id",
    "approval_id",
    "working_directory",
    "model",
    "budget",
}
_PERMISSION_RANK = {
    "read_only": 0,
    "workspace_write": 1,
    "write": 1,
    "admin": 2,
    "danger_full_access": 2,
}


@dataclass(frozen=True)
class ChildRunContext:
    """Immutable child-run lineage and runtime constraints."""

    parent_session_id: str
    parent_run_id: str
    parent_agent_id: str = "default"
    subagent_role: str = "researcher"
    team_id: str = ""
    team_task_id: str = ""
    workflow_run_id: str = ""
    phase_run_id: str = ""
    workflow_phase_id: str = ""
    approval_id: str = ""
    frontend_settings: dict[str, Any] = field(default_factory=dict)
    working_directory: str = ""
    command_scope: str = "restricted"
    model: str | None = None
    permission_mode: str = "read_only"
    budget: dict[str, Any] = field(default_factory=dict)
    depth: int = 0
    is_child: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "parent_session_id", str(self.parent_session_id))
        object.__setattr__(self, "parent_run_id", str(self.parent_run_id))
        object.__setattr__(self, "parent_agent_id", str(self.parent_agent_id or "default"))
        object.__setattr__(self, "subagent_role", str(self.subagent_role or "researcher"))
        working_directory = str(self.working_directory or "")
        command_scope = _scope_value(self.command_scope)
        model = _optional_string(self.model)
        object.__setattr__(self, "working_directory", working_directory)
        object.__setattr__(self, "command_scope", command_scope)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "permission_mode", _permission_value(self.permission_mode))
        object.__setattr__(self, "budget", dict(self.budget or {}))
        object.__setattr__(self, "depth", max(0, int(self.depth or 0)))
        object.__setattr__(self, "is_child", bool(self.is_child))
        object.__setattr__(
            self,
            "frontend_settings",
            _normalized_frontend_settings(
                dict(self.frontend_settings or {}),
                working_directory=working_directory,
                command_scope=command_scope,
                model=model,
            ),
        )

    def as_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        for field_name in (*_LINEAGE_FIELDS, *_RUNTIME_FIELDS):
            value = getattr(self, field_name)
            if isinstance(value, dict):
                metadata[field_name] = dict(value)
            else:
                metadata[field_name] = value
        return metadata

    def lineage_metadata(self) -> dict[str, Any]:
        return {field_name: getattr(self, field_name) for field_name in _LINEAGE_FIELDS}


def derive_child_context(
    *,
    parent_session_id: str,
    parent_run_id: str,
    parent_agent_id: str = "default",
    parent_metadata: dict[str, Any] | None = None,
    role_id: str = "researcher",
    overrides: dict[str, Any] | None = None,
) -> ChildRunContext:
    """Derive a narrowed child context from parent runtime metadata."""

    source = dict(parent_metadata or {})
    override_values = dict(overrides or {})
    frontend_settings = _frontend_settings(source, override_values)
    base_command_scope = _scope_value(
        source.get("command_scope") or frontend_settings.get("commandScope") or "restricted"
    )
    requested_command_scope = _scope_value(
        override_values.get("command_scope", base_command_scope)
    )
    base_permission = _permission_value(source.get("permission_mode") or "read_only")
    requested_permission = _permission_value(
        override_values.get("permission_mode", base_permission)
    )

    working_directory = str(
        override_values.get(
            "working_directory",
            source.get("working_directory") or frontend_settings.get("workingDirectory") or "",
        )
        or ""
    )
    command_scope = _narrow_scope(base_command_scope, requested_command_scope)
    model = _optional_string(override_values.get("model", source.get("model")))
    frontend_settings = _normalized_frontend_settings(
        frontend_settings,
        working_directory=working_directory,
        command_scope=command_scope,
        model=model,
    )

    values = {
        "parent_session_id": parent_session_id,
        "parent_run_id": parent_run_id,
        "parent_agent_id": parent_agent_id,
        "subagent_role": role_id,
        "team_id": "",
        "team_task_id": "",
        "workflow_run_id": "",
        "phase_run_id": "",
        "workflow_phase_id": "",
        "approval_id": "",
        "frontend_settings": frontend_settings,
        "working_directory": working_directory,
        "command_scope": command_scope,
        "model": model,
        "permission_mode": _narrow_permission(base_permission, requested_permission),
        "budget": _dict_value(override_values.get("budget", source.get("budget"))),
        "depth": _parent_depth(source) + 1,
        "is_child": True,
    }

    for field_name in _INHERITABLE_METADATA:
        if field_name in {"permission_mode", "budget", "model"}:
            continue
        if field_name in source:
            values[field_name] = str(source[field_name] or "")
    for field_name, value in override_values.items():
        if field_name in _OVERRIDABLE_FIELDS:
            values[field_name] = value
    values["is_child"] = True
    return ChildRunContext(**values)


def _frontend_settings(
    parent_metadata: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    raw = overrides.get("frontend_settings")
    if raw is None:
        raw = parent_metadata.get("frontend_settings") or parent_metadata.get("frontendSettings")
    return dict(raw) if isinstance(raw, dict) else {}


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _normalized_frontend_settings(
    frontend_settings: dict[str, Any],
    *,
    working_directory: str,
    command_scope: str,
    model: str | None,
) -> dict[str, Any]:
    settings = dict(frontend_settings)
    if working_directory:
        settings.setdefault("workingDirectory", working_directory)
    settings["commandScope"] = command_scope
    if model:
        settings.setdefault("model", model)
    return settings


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parent_depth(parent_metadata: dict[str, Any]) -> int:
    try:
        return max(0, int(parent_metadata.get("depth") or 0))
    except (TypeError, ValueError):
        return 0


def _scope_value(value: Any) -> str:
    text = str(value or "restricted").strip()
    return text if text in {"restricted", "unrestricted"} else "restricted"


def _narrow_scope(base: str, requested: str) -> str:
    if base == "restricted" or requested == "restricted":
        return "restricted"
    return "unrestricted"


def _permission_value(value: Any) -> str:
    text = str(value or "read_only").strip()
    return text if text in _PERMISSION_RANK else "read_only"


def _narrow_permission(base: str, requested: str) -> str:
    base_rank = _PERMISSION_RANK.get(base, 0)
    requested_rank = _PERMISSION_RANK.get(requested, 0)
    return requested if requested_rank <= base_rank else base
