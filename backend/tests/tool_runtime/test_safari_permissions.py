from __future__ import annotations

from app.agent_framework.tool_runtime import PermissionPolicy, default_permission_policy
from app.agent_framework.tool_runtime.approvals import evaluate_tool_call


def test_permission_policy_denies_even_when_unrestricted() -> None:
    policy = PermissionPolicy(
        {
            "version": 1,
            "default": {"approval": "never", "risk": "low"},
            "tools": {"xhs_click_publish": {"approval": "deny", "risk": "high"}},
            "denied_command_patterns": [],
        }
    )

    decision = policy.evaluate("xhs_click_publish", {}, command_scope="unrestricted")

    assert decision.denied is True
    assert decision.needs_approval is False


def test_sensitive_safari_tools_do_not_bypass_approval_in_unrestricted_scope() -> None:
    policy = PermissionPolicy(
        {
            "version": 1,
            "default": {"approval": "never", "risk": "low"},
            "tools": {
                "chatgpt_send_message": {
                    "approval": "always",
                    "risk": "high",
                    "unrestricted_bypass": False,
                }
            },
            "denied_command_patterns": [],
        }
    )

    decision = policy.evaluate(
        "chatgpt_send_message",
        {"prompt": "hello"},
        command_scope="unrestricted",
    )

    assert decision.needs_approval is True
    assert decision.denied is False


def test_default_policy_contains_denied_publish_and_always_chatgpt_send() -> None:
    denied = evaluate_tool_call("xhs_click_publish", {}, command_scope="unrestricted")
    sensitive = default_permission_policy().evaluate(
        "chatgpt_send_message",
        {"prompt": "hello"},
        command_scope="unrestricted",
    )

    assert denied.denied is True
    assert sensitive.needs_approval is True
