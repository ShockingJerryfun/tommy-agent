from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..runtime.events import AgentEvent


@dataclass(frozen=True)
class HermesDelegateConfig:
    enabled: bool = False
    model: str | None = None
    enabled_toolsets: list[str] = field(default_factory=list)
    max_iterations: int = 12


class HermesDelegateUnavailable(RuntimeError):
    """Raised when optional Hermes delegation cannot run."""


def run_hermes_delegate(
    prompt: str,
    *,
    config: HermesDelegateConfig | None = None,
) -> dict[str, Any]:
    resolved = config or HermesDelegateConfig()
    if not resolved.enabled:
        raise HermesDelegateUnavailable("Hermes delegation is disabled by configuration.")

    try:
        from run_agent import AIAgent  # type: ignore
    except Exception as exc:  # noqa: BLE001 - optional integration should fail softly.
        raise HermesDelegateUnavailable("Hermes Agent is not installed.") from exc

    agent = AIAgent(
        model=resolved.model,
        quiet_mode=True,
        skip_memory=True,
        skip_context_files=True,
        enabled_toolsets=resolved.enabled_toolsets or None,
        max_iterations=resolved.max_iterations,
    )
    result = agent.run_conversation(user_message=prompt)
    return {
        "final_response": result.get("final_response"),
        "messages": result.get("messages", []),
        "task_id": result.get("task_id"),
    }


def hermes_result_events(result: dict[str, Any]) -> list[AgentEvent]:
    """Adapt optional Hermes output into this runtime's event vocabulary."""

    task_id = str(result.get("task_id") or "hermes")
    return [
        AgentEvent(
            type="tool_start",
            data={
                "tool": "hermes_delegate",
                "tool_call_id": task_id,
                "args": {"mode": "optional_delegation"},
            },
        ),
        AgentEvent(
            type="tool_end",
            data={
                "tool": "hermes_delegate",
                "tool_call_id": task_id,
                "status": "ok",
                "content": str(result.get("final_response") or ""),
            },
        ),
    ]
