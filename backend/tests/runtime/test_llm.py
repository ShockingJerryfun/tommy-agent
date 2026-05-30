from __future__ import annotations

import sys
from types import SimpleNamespace

from app.agent_framework.runtime.llm import LLMSettings, create_llm, load_llm_settings


def test_load_llm_settings_defaults_to_reasoning_tolerant_timeout(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.delenv("AGENT_TIMEOUT_SECONDS", raising=False)

    settings = load_llm_settings()

    assert settings.timeout == 120.0


def test_load_llm_settings_reads_timeout_from_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "7.5")

    settings = load_llm_settings()

    assert settings.timeout == 7.5


def test_create_deepseek_llm_passes_configured_timeout(monkeypatch):
    captured: dict[str, object] = {}

    class FakeChatDeepSeek:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setitem(
        sys.modules,
        "langchain_deepseek",
        SimpleNamespace(ChatDeepSeek=FakeChatDeepSeek),
    )

    create_llm(
        LLMSettings(
            model="deepseek-v4-pro",
            api_key="ignored",
            base_url=None,
            timeout=12.5,
            max_retries=1,
        )
    )

    assert captured["timeout"] == 12.5
    assert captured["max_retries"] == 1
