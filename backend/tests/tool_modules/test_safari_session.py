from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.agent_framework.tool_modules.safari_session import (
    SafariExecutor,
    detect_browser_gate,
    safe_job_id,
    write_json_artifact,
)


def test_detect_browser_gate_identifies_login_and_captcha() -> None:
    assert (
        detect_browser_gate(
            {
                "url": "https://creator.xiaohongshu.com/login?redirectReason=401",
                "title": "小红书创作服务平台",
                "text": "短信登录 发送验证码 登 录",
            }
        )
        == "LOGIN_REQUIRED"
    )
    assert (
        detect_browser_gate(
            {
                "url": "https://chatgpt.com/api/auth/error",
                "title": "请稍候…",
                "html": "cf-turnstile-response challenge-platform",
            }
        )
        == "CAPTCHA_REQUIRED"
    )
    assert detect_browser_gate({"url": "https://chatgpt.com/", "text": "今天有什么计划？"}) == "OK"


def test_safari_executor_evaluate_js_uses_temp_file() -> None:
    calls: list[dict] = []

    def runner(cmd, **kwargs):
        calls.append({"cmd": cmd, **kwargs})
        return SimpleNamespace(returncode=0, stdout='{"ok":true}\n', stderr="")

    executor = SafariExecutor(runner=runner)

    assert executor.evaluate_js("JSON.stringify({ok:true})") == '{"ok":true}'
    assert calls[0]["cmd"] == ["osascript"]
    assert "do JavaScript jsCode" in calls[0]["input"]
    assert "read POSIX file" in calls[0]["input"]


def test_safari_executor_screenshot_targets_front_window(monkeypatch, tmp_path: Path) -> None:
    script_calls: list[dict] = []
    capture_calls: list[dict] = []

    def runner(cmd, **kwargs):
        script_calls.append({"cmd": cmd, **kwargs})
        return SimpleNamespace(returncode=0, stdout="63\n", stderr="")

    def capture_runner(cmd, **kwargs):
        capture_calls.append({"cmd": cmd, **kwargs})
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "app.agent_framework.tool_modules.safari_session.subprocess.run",
        capture_runner,
    )
    executor = SafariExecutor(runner=runner)
    target = tmp_path / "shot.png"

    assert executor.screenshot(target) == target

    assert script_calls[0]["cmd"] == ["osascript"]
    assert capture_calls[0]["cmd"] == ["screencapture", "-x", "-l", "63", str(target)]


def test_artifact_helpers_sanitize_job_ids_and_write_json(tmp_path: Path) -> None:
    assert safe_job_id("  ../../bad id  ") == "bad-id"

    target = write_json_artifact(tmp_path, "state.json", {"status": "OK"})

    assert target.name == "state.json"
    assert '"status": "OK"' in target.read_text(encoding="utf-8")
