from __future__ import annotations

import os
from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel


@dataclass(frozen=True)
class LLMSettings:
    model: str
    api_key: str
    base_url: str | None
    temperature: float = 0.2
    timeout: float = 60.0
    max_retries: int = 2


def load_llm_settings() -> LLMSettings:
    api_key = (
        os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("OPENROUTER_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    if not api_key:
        raise RuntimeError(
            "Missing API key. Set DEEPSEEK_API_KEY, OPENROUTER_API_KEY, or OPENAI_API_KEY."
        )

    return LLMSettings(
        model=os.getenv("DEEPSEEK_MODEL", os.getenv("OPENAI_MODEL", "deepseek-chat")),
        api_key=api_key,
        base_url=(
            os.getenv("DEEPSEEK_BASE_URL")
            or os.getenv("OPENROUTER_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
        ),
        temperature=float(os.getenv("AGENT_TEMPERATURE", "0.2")),
        timeout=float(os.getenv("AGENT_TIMEOUT_SECONDS", "60")),
        max_retries=int(os.getenv("AGENT_MAX_RETRIES", "2")),
    )


def _patch_reasoning_content_passthrough() -> None:
    """Patch langchain-openai's _convert_message_to_dict to pass reasoning_content back.

    DeepSeek thinking-mode models (e.g. deepseek-v4-pro) require that any
    reasoning_content present in an assistant turn be echoed back verbatim in
    the next API call. The upstream langchain-openai function only serialises a
    known allowlist of additional_kwargs fields (tool_calls, function_call,
    audio) and silently drops everything else — including reasoning_content.

    This minimal, targeted patch adds reasoning_content to the serialised dict
    when it is present so the DeepSeek API does not return a 400 error.
    """
    import langchain_openai.chat_models.base as _base
    from langchain_core.messages import AIMessage

    if getattr(_base._convert_message_to_dict, "_tommy_reasoning_patch", False):
        return

    _original = _base._convert_message_to_dict

    def _patched(message, api="chat/completions"):  # type: ignore[no-untyped-def]
        d = _original(message, api=api)
        if isinstance(message, AIMessage):
            reasoning_content = message.additional_kwargs.get("reasoning_content")
            if reasoning_content is not None:
                d["reasoning_content"] = reasoning_content
        return d

    _patched._tommy_reasoning_patch = True  # type: ignore[attr-defined]
    _base._convert_message_to_dict = _patched  # type: ignore[assignment]


# Apply once at import time.
_patch_reasoning_content_passthrough()


def create_llm(settings: LLMSettings | None = None) -> BaseChatModel:
    """Create the best available chat model for the configured provider.

    Uses ChatDeepSeek when a DeepSeek API key is detected — it natively
    captures reasoning_content from thinking-mode models. Falls back to
    ChatOpenAI for OpenRouter / generic OpenAI-compatible endpoints.
    """
    resolved = settings or load_llm_settings()

    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if deepseek_key:
        from langchain_deepseek import ChatDeepSeek  # type: ignore[import-untyped]

        return ChatDeepSeek(
            model=resolved.model,
            api_key=deepseek_key,
            temperature=resolved.temperature,
            max_retries=resolved.max_retries,
            streaming=True,
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=resolved.model,
        api_key=resolved.api_key,
        base_url=resolved.base_url,
        temperature=resolved.temperature,
        timeout=resolved.timeout,
        max_retries=resolved.max_retries,
        streaming=True,
    )
