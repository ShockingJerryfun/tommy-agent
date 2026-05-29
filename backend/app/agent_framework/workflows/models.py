"""Workflow runtime DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WorkflowBudget:
    max_workers: int = 20
    max_wall_seconds: float = 900.0


@dataclass(frozen=True)
class WorkflowPhaseSpec:
    id: str
    kind: str
    agent: str
    prompt: str
    input_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowSpec:
    id: str
    name: str
    description: str
    max_concurrency: int
    budget: WorkflowBudget
    inputs: dict[str, Any]
    phases: list[WorkflowPhaseSpec]
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "max_concurrency": self.max_concurrency,
            "budget": {
                "max_workers": self.budget.max_workers,
                "max_wall_seconds": self.budget.max_wall_seconds,
            },
            "inputs": self.inputs,
            "phases": [
                {
                    "id": phase.id,
                    "kind": phase.kind,
                    "agent": phase.agent,
                    "input": phase.input_ref,
                    "prompt": phase.prompt,
                    "metadata": phase.metadata,
                }
                for phase in self.phases
            ],
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class WorkflowRunResult:
    workflow_run_id: str
    status: str
    summary: str
    outputs: list[str]
