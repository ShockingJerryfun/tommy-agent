from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.runnables import Runnable

ReasoningEffort = Literal["high", "max"]

_SUPPORTED_REASONING_EFFORTS: set[ReasoningEffort] = {"high", "max"}
_REASONING_EFFORT_ALIASES: dict[str, ReasoningEffort] = {
    "low": "high",
    "medium": "high",
    "xhigh": "max",
}


@dataclass(frozen=True)
class RuntimeModelOptions:
    """Per-run model options supplied by trusted runtime metadata."""

    model: str | None = None
    temperature: float | None = None
    thinking_enabled: bool | None = None
    reasoning_effort: ReasoningEffort | None = None

    def invocation_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self.model:
            kwargs["model"] = self.model
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.thinking_enabled is None or not supports_thinking_controls(self.model):
            return kwargs

        kwargs["extra_body"] = {
            "thinking": {"type": "enabled" if self.thinking_enabled else "disabled"}
        }
        if self.thinking_enabled and self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        return kwargs


def bind_runtime_model_options(model: Runnable, metadata: dict[str, Any] | None) -> Runnable:
    options = runtime_model_options(metadata)
    kwargs = options.invocation_kwargs()
    if not kwargs:
        return model
    return model.bind(**kwargs)


def runtime_model_options(metadata: dict[str, Any] | None) -> RuntimeModelOptions:
    frontend_settings = _frontend_settings(metadata)
    model = _string_setting(frontend_settings, "model") or _env_model()
    return RuntimeModelOptions(
        model=model,
        temperature=_float_setting(frontend_settings, "temperature"),
        thinking_enabled=_bool_setting(frontend_settings, "thinkingMode", _env_thinking_enabled()),
        reasoning_effort=normalize_reasoning_effort(
            _string_setting(frontend_settings, "thinkingEffort")
            or os.getenv("AGENT_REASONING_EFFORT")
            or "high"
        ),
    )


def supports_thinking_controls(model: str | None) -> bool:
    if not model:
        return False
    normalized = model.lower()
    return "deepseek-v4" in normalized


def normalize_reasoning_effort(value: str | None) -> ReasoningEffort | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in _SUPPORTED_REASONING_EFFORTS:
        return normalized  # type: ignore[return-value]
    return _REASONING_EFFORT_ALIASES.get(normalized)


def _frontend_settings(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    settings = metadata.get("frontend_settings")
    return settings if isinstance(settings, dict) else {}


def _string_setting(settings: dict[str, Any], key: str) -> str | None:
    value = settings.get(key)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _float_setting(settings: dict[str, Any], key: str) -> float | None:
    value = settings.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _bool_setting(settings: dict[str, Any], key: str, default: bool | None) -> bool | None:
    value = settings.get(key)
    return value if isinstance(value, bool) else default


def _env_model() -> str | None:
    return os.getenv("DEEPSEEK_MODEL") or os.getenv("OPENAI_MODEL")


def _env_thinking_enabled() -> bool | None:
    raw = os.getenv("AGENT_THINKING_ENABLED")
    if raw is None:
        return True
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return True
