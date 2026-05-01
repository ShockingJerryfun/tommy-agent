"""YAML-driven permission policy for the tool runtime."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

POLICY_FILE = Path(__file__).resolve().parent / "permissions.yaml"


@dataclass(frozen=True)
class PermissionDecision:
    """Outcome of consulting the policy for a single tool call."""

    needs_approval: bool
    risk_level: str = "low"
    summary: str = ""
    denied: bool = False
    deny_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "needs_approval": self.needs_approval,
            "risk_level": self.risk_level,
            "summary": self.summary,
            "denied": self.denied,
            "deny_reason": self.deny_reason,
        }


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "…"


class PermissionPolicy:
    """Policy compiled from ``permissions.yaml`` (or an equivalent dict)."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw
        self._default = raw.get("default") or {"approval": "never", "risk": "low"}
        self._tools: dict[str, dict[str, Any]] = dict(raw.get("tools") or {})
        patterns = raw.get("denied_command_patterns") or []
        self._denied_patterns: tuple[re.Pattern[str], ...] = tuple(
            re.compile(pattern, flags=re.IGNORECASE) for pattern in patterns
        )

    @property
    def denied_command_patterns(self) -> tuple[re.Pattern[str], ...]:
        return self._denied_patterns

    def command_is_dangerous(self, command: str) -> bool:
        normalized = " ".join((command or "").strip().split())
        return any(pattern.search(normalized) for pattern in self._denied_patterns)

    def evaluate(
        self,
        name: str,
        args: dict[str, Any],
        *,
        command_scope: str = "restricted",
    ) -> PermissionDecision:
        spec = self._tools.get(name, self._default)
        approval = str(spec.get("approval") or self._default.get("approval") or "never")

        if name == "run_shell_command":
            command = str(args.get("command") or "")
            if self.command_is_dangerous(command):
                return PermissionDecision(
                    needs_approval=True,
                    risk_level=self._risk_for(spec, args, dangerous=True),
                    summary=self._format_summary(name, spec, args),
                )

        if command_scope == "unrestricted":
            return PermissionDecision(needs_approval=False)

        if approval == "never":
            return PermissionDecision(needs_approval=False)

        if approval == "always":
            return PermissionDecision(
                needs_approval=True,
                risk_level=self._risk_for(spec, args),
                summary=self._format_summary(name, spec, args),
            )

        # ``conditional`` and any future modes default to safe-by-asking.
        return PermissionDecision(
            needs_approval=True,
            risk_level=self._risk_for(spec, args),
            summary=self._format_summary(name, spec, args),
        )

    def _risk_for(
        self,
        spec: dict[str, Any],
        args: dict[str, Any],
        *,
        dangerous: bool = False,
    ) -> str:
        risk = spec.get("risk")
        if isinstance(risk, str):
            return risk
        if isinstance(risk, dict):
            if dangerous and "dangerous" in risk:
                return str(risk["dangerous"])
            mode = str(args.get("mode") or "")
            mode_key = f"mode_{mode}" if mode else None
            if mode_key and mode_key in risk:
                return str(risk[mode_key])
            if "mode_default" in risk:
                return str(risk["mode_default"])
            if "base" in risk:
                return str(risk["base"])
        return "medium"

    def _format_summary(
        self,
        name: str,
        spec: dict[str, Any],
        args: dict[str, Any],
    ) -> str:
        template = spec.get("summary_template")
        if not isinstance(template, str) or not template:
            return name
        ctx: dict[str, Any] = {
            "name": name,
            "path": args.get("path") or "",
            "mode": args.get("mode") or "overwrite",
            "size_bytes": len(str(args.get("content") or "").encode("utf-8")),
            "command": str(args.get("command") or ""),
            "command_preview": _truncate(str(args.get("command") or ""), 180),
            "target_agent": str(args.get("target_agent") or "researcher"),
            "task": str(args.get("task") or ""),
            "task_preview": _truncate(str(args.get("task") or ""), 180),
        }
        try:
            return template.format(**ctx)
        except (KeyError, IndexError, ValueError):
            return name


def load_permission_policy(path: Path | None = None) -> PermissionPolicy:
    target = path or POLICY_FILE
    with target.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"permissions yaml at {target} must be a mapping at the top level")
    return PermissionPolicy(raw)


@lru_cache(maxsize=1)
def default_permission_policy() -> PermissionPolicy:
    return load_permission_policy()
