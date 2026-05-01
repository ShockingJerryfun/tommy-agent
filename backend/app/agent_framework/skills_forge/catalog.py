from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from ..paths import DATA_ROOT
from ..storage import PostgresAgentStore, get_agent_store


class SkillProposal(BaseModel):
    name: str = Field(..., min_length=1)
    action: str = Field(..., pattern="^(create|update)$")
    rationale: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    risks: list[str] = Field(default_factory=list)
    relative_path: str | None = Field(
        default=None,
        description="Path relative to the agent skills root. Directories resolve to SKILL.md.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class SkillSummary:
    name: str
    path: str
    description: str
    updated_at: str = ""


class SkillCatalog:
    def __init__(
        self,
        agent_id: str = "default",
        root: Path | None = None,
        store: PostgresAgentStore | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.skills_root = (root or DATA_ROOT) / agent_id / "skills"
        self.store = store or get_agent_store()

    def list_skills(self) -> list[SkillSummary]:
        if not self.skills_root.exists():
            return []
        summaries = []
        for path in sorted(self.skills_root.glob("**/SKILL.md")):
            text = path.read_text(encoding="utf-8", errors="replace")
            metadata = _parse_frontmatter(text)
            summaries.append(
                SkillSummary(
                    name=metadata.get("name") or path.parent.name,
                    path=str(path.relative_to(self.skills_root)),
                    description=metadata.get("description") or "",
                    updated_at=datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                )
            )
        return summaries

    def read_skill(self, relative_path: str) -> str:
        path = self.resolve_skill_path(relative_path)
        return path.read_text(encoding="utf-8", errors="replace")

    def create_proposal(
        self,
        proposal: SkillProposal,
        *,
        allow_auto_apply: bool = False,
    ) -> dict[str, Any]:
        relative_path = self.normalize_relative_path(proposal.relative_path or proposal.name)
        record = self.store.create_skill_proposal(
            agent_id=self.agent_id,
            name=proposal.name,
            relative_path=relative_path,
            action=proposal.action,
            rationale=proposal.rationale,
            content=proposal.content,
            risks=proposal.risks,
            metadata={
                **proposal.metadata,
                "allow_auto_apply": allow_auto_apply,
            },
        )
        if allow_auto_apply:
            applied = self.apply_proposal(record["id"])
            return {
                "proposal": applied,
                "requires_confirmation": False,
                "applied": True,
                "message": (
                    "Skill proposal was auto-applied under the configured agent skills root."
                ),
            }
        return {
            "proposal": record,
            "requires_confirmation": True,
            "applied": False,
            "message": "Review and approve before writing this proposal to SKILL.md.",
        }

    def apply_proposal(self, proposal_id: str) -> dict[str, Any]:
        proposal = self.store.get_skill_proposal(proposal_id)
        if proposal is None:
            raise FileNotFoundError(f"Skill proposal not found: {proposal_id}")
        if proposal["status"] == "applied":
            return proposal
        if proposal["status"] == "rejected":
            raise ValueError("Rejected skill proposals cannot be applied.")

        path = self.resolve_skill_path(proposal["relative_path"])
        previous_content = (
            path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        )
        if proposal["action"] == "update" and not path.exists():
            raise FileNotFoundError(f"Cannot update missing skill: {proposal['relative_path']}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(proposal["content"], encoding="utf-8")
        version_id = f"skill-ver-{uuid4().hex}"
        applied = self.store.apply_skill_proposal(
            proposal_id,
            version_id=version_id,
            previous_content=previous_content,
        )
        if applied is None:
            raise FileNotFoundError(f"Skill proposal not found: {proposal_id}")
        return applied

    def reject_proposal(self, proposal_id: str) -> dict[str, Any]:
        rejected = self.store.reject_skill_proposal(proposal_id)
        if rejected is None:
            raise FileNotFoundError(f"Skill proposal not found: {proposal_id}")
        return rejected

    def list_proposals(self, status: str | None = None) -> list[dict[str, Any]]:
        return self.store.list_skill_proposals(agent_id=self.agent_id, status=status)

    def list_versions(self, relative_path: str | None = None) -> list[dict[str, Any]]:
        return self.store.list_skill_versions(agent_id=self.agent_id, relative_path=relative_path)

    def normalize_relative_path(self, value: str) -> str:
        raw = value.strip().strip("/")
        if not raw:
            raise ValueError("Skill path is required.")
        path = Path(raw)
        if path.is_absolute() or ".." in path.parts:
            raise PermissionError(f"Path escapes skills root: {value}")
        if path.name != "SKILL.md":
            path = path / "SKILL.md"
        return path.as_posix()

    def resolve_skill_path(self, relative_path: str) -> Path:
        normalized = self.normalize_relative_path(relative_path)
        path = (self.skills_root / normalized).resolve()
        root = self.skills_root.resolve()
        if root != path and root not in path.parents:
            raise PermissionError(f"Path escapes skills root: {relative_path}")
        return path


def _parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    _, raw, *_ = text.split("---", 2)
    metadata: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"')
    return metadata
