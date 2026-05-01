from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_openai.chat_models import base as openai_base

from app.agent_framework.runtime.llm import _patch_reasoning_content_passthrough
from app.agent_framework.runtime.model_options import runtime_model_options


def test_deepseek_v4_thinking_options_from_frontend_settings():
    options = runtime_model_options(
        {
            "frontend_settings": {
                "model": "deepseek-v4-pro",
                "temperature": 0.3,
                "thinkingMode": True,
                "thinkingEffort": "max",
            }
        }
    )

    assert options.invocation_kwargs() == {
        "model": "deepseek-v4-pro",
        "temperature": 0.3,
        "extra_body": {"thinking": {"type": "enabled"}},
        "reasoning_effort": "max",
    }


def test_disabled_thinking_omits_reasoning_effort():
    options = runtime_model_options(
        {
            "frontend_settings": {
                "model": "deepseek-v4-pro",
                "thinkingMode": False,
                "thinkingEffort": "max",
            }
        }
    )

    assert options.invocation_kwargs() == {
        "model": "deepseek-v4-pro",
        "extra_body": {"thinking": {"type": "disabled"}},
    }


def test_non_v4_model_does_not_receive_thinking_controls():
    options = runtime_model_options(
        {
            "frontend_settings": {
                "model": "deepseek-chat",
                "thinkingMode": True,
                "thinkingEffort": "max",
            }
        }
    )

    assert options.invocation_kwargs() == {"model": "deepseek-chat"}


def test_reasoning_content_is_serialized_for_followup_tool_calls():
    _patch_reasoning_content_passthrough()
    message = AIMessage(content="", additional_kwargs={"reasoning_content": "tool reasoning"})

    serialized = openai_base._convert_message_to_dict(message)

    assert serialized["reasoning_content"] == "tool reasoning"
