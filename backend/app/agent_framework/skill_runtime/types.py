from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SkillMetadata:
    name: str | None = None
    description: str | None = None
    source_path: str | None = None
    required_tools: tuple[str, ...] = ()
    triggers: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    safety_notes: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    user_invocable: bool = False
    disable_model_invocation: bool = False
    hermes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillDocument:
    metadata: SkillMetadata
    body: str
    signature_text: str


@dataclass(frozen=True)
class ResolvedSkill:
    name: str
    relative_path: str
    description: str = ""
    score: float = 0.0
    status: str = "active"
    required_tools: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    diagnostics: tuple[dict[str, str], ...] = ()
    row: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillResolution:
    selected: list[ResolvedSkill]
    diagnostics: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class SkillResource:
    relative_path: str
    kind: str
    size_bytes: int


@dataclass(frozen=True)
class LoadedSkillResource:
    resource: SkillResource
    content: str
    truncated: bool = False


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    relative_path: str
    summary: str
    excerpt: str
    full: str
    injected: str
    injected_chars: int
    linked_files: tuple[str, ...] = ()
    resources: tuple[SkillResource, ...] = ()


@dataclass(frozen=True)
class SkillLoadResult:
    skills: list[LoadedSkill]
    injected_chars: int
    linked_files: list[str] = field(default_factory=list)
    resources: list[SkillResource] = field(default_factory=list)
    diagnostics: list[dict[str, str]] = field(default_factory=list)
