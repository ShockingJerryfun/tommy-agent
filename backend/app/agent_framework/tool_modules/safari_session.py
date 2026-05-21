from __future__ import annotations

import json
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

BrowserGateStatus = Literal["OK", "LOGIN_REQUIRED", "CAPTCHA_REQUIRED", "NOT_READY"]

XHS_JOB_ROOT = Path.home() / ".tommy" / "xhs_content_jobs"


def safe_job_id(raw: str | None) -> str:
    """Return a filesystem-safe job id without path components."""

    value = Path(str(raw or "").strip()).name
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-_")
    return value or "default"


def job_dir(job_id: str | None = None, *, root: Path = XHS_JOB_ROOT) -> Path:
    target = root / safe_job_id(job_id)
    target.mkdir(parents=True, exist_ok=True)
    return target


def write_json_artifact(directory: Path, name: str, payload: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    body = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    target.write_text(body, encoding="utf-8")
    return target


def write_text_artifact(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    target.write_text(body, encoding="utf-8")
    return target


def detect_browser_gate(state: dict[str, Any]) -> BrowserGateStatus:
    """Classify login/captcha states from Safari DOM state."""

    url = str(state.get("url") or "").lower()
    title = str(state.get("title") or "").lower()
    text = str(state.get("text") or "").lower()
    html = str(state.get("html") or "").lower()
    combined = "\n".join((url, title, text, html))

    captcha_markers = (
        "cf-turnstile-response",
        "challenge-platform",
        "challenges.cloudflare.com",
        "verify you are human",
        "captcha",
        "请稍候",
        "安全验证",
        "人机验证",
    )
    if any(marker in combined for marker in captcha_markers):
        return "CAPTCHA_REQUIRED"

    login_markers = ("短信登录", "手机号", "登 录", "log in", "sign up", "登录", "注册")
    if (
        "/login" in url
        or "auth.openai.com" in url
        or any(marker in text for marker in login_markers)
    ):
        return "LOGIN_REQUIRED"

    if state.get("ready") is False:
        return "NOT_READY"
    return "OK"


class SafariExecutor:
    """Small AppleScript bridge for Safari DOM automation."""

    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self._runner = runner or subprocess.run

    def run_osascript(self, script: str, *, timeout: int = 30) -> str:
        completed = self._runner(
            ["osascript"],
            input=script,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if completed.returncode != 0:
            details = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(details or "osascript failed")
        return (completed.stdout or "").strip()

    def open_url(self, url: str, *, new_tab: bool = True) -> str:
        if new_tab:
            script = f"""
tell application "Safari"
  activate
  if (count of windows) = 0 then
    make new document with properties {{URL:{json.dumps(url)}}}
  else
    tell front window to set current tab to (make new tab with properties {{URL:{json.dumps(url)}}})
  end if
  return URL of current tab of front window
end tell
"""
        else:
            script = f"""
tell application "Safari"
  activate
  if (count of windows) = 0 then
    make new document with properties {{URL:{json.dumps(url)}}}
  else
    set URL of current tab of front window to {json.dumps(url)}
  end if
  return URL of current tab of front window
end tell
"""
        return self.run_osascript(script, timeout=30)

    def evaluate_js(self, javascript: str, *, timeout: int = 30) -> str:
        utf8_class = (
            "\N{LEFT-POINTING DOUBLE ANGLE QUOTATION MARK}"
            "class utf8"
            "\N{RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK}"
        )
        with tempfile.NamedTemporaryFile(
            "w",
            suffix=".js",
            encoding="utf-8",
            delete=False,
        ) as handle:
            handle.write(javascript)
            js_path = Path(handle.name)
        quoted = str(js_path).replace("\\", "\\\\").replace('"', '\\"')
        try:
            script = f"""
tell application "Safari"
  set jsCode to read POSIX file "{quoted}" as {utf8_class}
  do JavaScript jsCode in current tab of front window
end tell
"""
            return self.run_osascript(script, timeout=timeout)
        finally:
            js_path.unlink(missing_ok=True)

    def current_state(self) -> dict[str, Any]:
        raw = self.evaluate_js(
            """
JSON.stringify({
  url: location.href,
  title: document.title,
  text: document.body ? document.body.innerText.slice(0, 5000) : "",
  html: document.documentElement ? document.documentElement.outerHTML.slice(0, 12000) : ""
})
""",
            timeout=20,
        )
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"url": "", "title": "", "text": raw, "html": "", "ready": False}
        return parsed if isinstance(parsed, dict) else {"text": raw, "ready": False}

    def screenshot(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        window_id = ""
        try:
            window_id = self.run_osascript(
                """
tell application "Safari"
  activate
  if (count of windows) = 0 then return ""
  return id of front window
end tell
""",
                timeout=10,
            ).strip()
        except RuntimeError:
            window_id = ""
        command = ["screencapture", "-x", str(path)]
        if window_id:
            command = ["screencapture", "-x", "-l", window_id, str(path)]
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "").strip())
        return path


_SAFARI_EXECUTOR: SafariExecutor | None = None


def get_safari_executor() -> SafariExecutor:
    global _SAFARI_EXECUTOR
    if _SAFARI_EXECUTOR is None:
        _SAFARI_EXECUTOR = SafariExecutor()
    return _SAFARI_EXECUTOR


def reset_safari_executor() -> None:
    global _SAFARI_EXECUTOR
    _SAFARI_EXECUTOR = None
