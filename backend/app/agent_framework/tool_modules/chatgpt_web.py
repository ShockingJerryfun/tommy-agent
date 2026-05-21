from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from .context import require_approval
from .safari_session import (
    XHS_JOB_ROOT,
    detect_browser_gate,
    get_safari_executor,
    job_dir,
    safe_job_id,
    write_json_artifact,
    write_text_artifact,
)
from .xhs_content_ops import parse_xhs_note_json

CHATGPT_URL = "https://chatgpt.com/"


class ChatgptOpenArgs(BaseModel):
    url: str = Field(default=CHATGPT_URL, min_length=1, max_length=500)
    new_tab: bool = True
    job_id: str | None = Field(default=None, max_length=120)


class ChatgptSendMessageArgs(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=20000)
    job_id: str | None = Field(default=None, max_length=120)


class ChatgptWaitUntilDoneArgs(BaseModel):
    timeout_seconds: int = Field(default=180, ge=5, le=600)
    interval_seconds: int = Field(default=2, ge=1, le=15)
    job_id: str | None = Field(default=None, max_length=120)


class ChatgptExtractLatestTextArgs(BaseModel):
    job_id: str | None = Field(default=None, max_length=120)


class ChatgptDownloadLatestImagesArgs(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=120)
    max_images: int = Field(default=9, ge=1, le=18)


class ChatgptSaveArtifactsArgs(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=120)
    name: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1)


def _directory(job_id: str | None) -> Path:
    return job_dir(job_id or "chatgpt-web", root=XHS_JOB_ROOT)


def _gate_result(job_id: str | None, action: str) -> dict[str, Any] | None:
    executor = get_safari_executor()
    state = executor.current_state()
    status = detect_browser_gate(state)
    if status == "OK":
        return None
    directory = _directory(job_id)
    write_json_artifact(
        directory,
        f"{action}_blocked_state.json",
        {"status": status, "state": state},
    )
    screenshot = executor.screenshot(directory / f"{action}_blocked.png")
    return {
        "status": status,
        "action": action,
        "state": state,
        "screenshot": str(screenshot),
        "artifact_dir": str(directory),
    }


def _latest_assistant_script() -> str:
    return """
(() => {
  const nodes = [...document.querySelectorAll('[data-message-author-role="assistant"], article')];
  const texts = nodes.map((node) => (node.innerText || '').trim()).filter(Boolean);
  return texts.length ? texts[texts.length - 1] : '';
})()
"""


@tool(args_schema=ChatgptOpenArgs)
def chatgpt_open(
    url: str = CHATGPT_URL,
    new_tab: bool = True,
    job_id: str | None = None,
) -> str:
    """Open ChatGPT in Safari and report login/captcha status."""

    require_approval("chatgpt_open")
    executor = get_safari_executor()
    opened = executor.open_url(url, new_tab=new_tab)
    state = executor.current_state()
    status = detect_browser_gate(state)
    directory = _directory(job_id)
    screenshot = executor.screenshot(directory / "chatgpt_open.png")
    result = {
        "status": status,
        "url": opened,
        "state": state,
        "screenshot": str(screenshot),
        "artifact_dir": str(directory),
    }
    write_json_artifact(directory, "chatgpt_open.json", result)
    return json.dumps(result, ensure_ascii=False)


@tool(args_schema=ChatgptOpenArgs)
def chatgpt_new_chat(
    url: str = CHATGPT_URL,
    new_tab: bool = True,
    job_id: str | None = None,
) -> str:
    """Open a fresh ChatGPT tab in Safari."""

    require_approval("chatgpt_new_chat")
    executor = get_safari_executor()
    opened = executor.open_url(url, new_tab=new_tab)
    state = executor.current_state()
    status = detect_browser_gate(state)
    directory = _directory(job_id)
    screenshot = executor.screenshot(directory / "chatgpt_new_chat.png")
    result = {
        "status": status,
        "url": opened,
        "state": state,
        "screenshot": str(screenshot),
        "artifact_dir": str(directory),
    }
    write_json_artifact(directory, "chatgpt_new_chat.json", result)
    return json.dumps(result, ensure_ascii=False)


@tool(args_schema=ChatgptSendMessageArgs)
def chatgpt_send_message(prompt: str, job_id: str | None = None) -> str:
    """Send a prompt to ChatGPT through Safari DOM automation."""

    require_approval("chatgpt_send_message")
    blocked = _gate_result(job_id, "chatgpt_send_message")
    if blocked:
        return json.dumps(blocked, ensure_ascii=False)

    directory = _directory(job_id)
    write_text_artifact(directory, "chatgpt_prompt.txt", prompt)
    script = f"""
(() => {{
  const prompt = {json.dumps(prompt, ensure_ascii=False)};
  const input = document.querySelector('#prompt-textarea')
    || document.querySelector('textarea[aria-label*="ChatGPT"]')
    || document.querySelector('textarea[aria-label*="聊天"]');
  if (!input) return JSON.stringify({{ok:false, error:'PROMPT_INPUT_NOT_FOUND'}});
  input.focus();
  if (input.tagName === 'TEXTAREA') {{
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    setter.call(input, prompt);
    input.dispatchEvent(new InputEvent(
      'input',
      {{bubbles:true, inputType:'insertText', data:prompt}}
    ));
    input.dispatchEvent(new Event('change', {{bubbles:true}}));
  }} else {{
    document.execCommand('selectAll', false, null);
    document.execCommand('insertText', false, prompt);
    input.dispatchEvent(new InputEvent(
      'input',
      {{bubbles:true, inputType:'insertText', data:prompt}}
    ));
  }}
  const send = document.querySelector('[data-testid="send-button"]')
    || document.querySelector('button[aria-label="发送提示"]')
    || document.querySelector('button[aria-label="Send prompt"]');
  if (!send) return JSON.stringify({{ok:false, error:'SEND_BUTTON_NOT_FOUND'}});
  send.click();
  return JSON.stringify({{ok:true}});
}})()
"""
    raw = get_safari_executor().evaluate_js(script, timeout=30)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {"ok": False, "error": "INVALID_SCRIPT_RESULT", "raw": raw}
    status = "OK" if result.get("ok") else str(result.get("error") or "CHATGPT_SEND_FAILED")
    screenshot = get_safari_executor().screenshot(directory / "chatgpt_send_message.png")
    payload = {
        "status": status,
        "job_id": safe_job_id(job_id),
        "result": result,
        "screenshot": str(screenshot),
        "artifact_dir": str(directory),
    }
    write_json_artifact(directory, "chatgpt_send_message.json", payload)
    return json.dumps(payload, ensure_ascii=False)


@tool(args_schema=ChatgptWaitUntilDoneArgs)
def chatgpt_wait_until_done(
    timeout_seconds: int = 180,
    interval_seconds: int = 2,
    job_id: str | None = None,
) -> str:
    """Wait until the latest visible ChatGPT response is stable."""

    blocked = _gate_result(job_id, "chatgpt_wait_until_done")
    if blocked:
        return json.dumps(blocked, ensure_ascii=False)
    executor = get_safari_executor()
    deadline = time.time() + timeout_seconds
    last = ""
    stable_count = 0
    while time.time() < deadline:
        current = executor.evaluate_js(_latest_assistant_script(), timeout=20)
        if current and current == last:
            stable_count += 1
        else:
            stable_count = 0
            last = current
        if current and stable_count >= 2:
            result = {"status": "OK", "latest_text_chars": len(current)}
            write_json_artifact(_directory(job_id), "chatgpt_wait_until_done.json", result)
            return json.dumps(result, ensure_ascii=False)
        time.sleep(interval_seconds)
    result = {"status": "TIMEOUT", "latest_text_chars": len(last)}
    write_json_artifact(_directory(job_id), "chatgpt_wait_until_done.json", result)
    return json.dumps(result, ensure_ascii=False)


@tool(args_schema=ChatgptExtractLatestTextArgs)
def chatgpt_extract_latest_text(job_id: str | None = None) -> str:
    """Extract and validate the latest visible ChatGPT answer."""

    blocked = _gate_result(job_id, "chatgpt_extract_latest_text")
    if blocked:
        return json.dumps(blocked, ensure_ascii=False)
    directory = _directory(job_id)
    latest = get_safari_executor().evaluate_js(_latest_assistant_script(), timeout=20)
    parsed = parse_xhs_note_json(latest)
    write_text_artifact(directory, "chatgpt_raw_output.txt", latest)
    write_json_artifact(directory, "chatgpt_parsed.json", parsed)
    return json.dumps(parsed | {"artifact_dir": str(directory)}, ensure_ascii=False)


@tool(args_schema=ChatgptDownloadLatestImagesArgs)
def chatgpt_download_latest_images(job_id: str, max_images: int = 9) -> str:
    """Download image URLs from the latest visible ChatGPT answer."""

    require_approval("chatgpt_download_latest_images")
    blocked = _gate_result(job_id, "chatgpt_download_latest_images")
    if blocked:
        return json.dumps(blocked, ensure_ascii=False)
    directory = _directory(job_id)
    image_dir = directory / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    raw = get_safari_executor().evaluate_js(
        """
JSON.stringify([
  ...document.querySelectorAll('[data-message-author-role="assistant"] img, article img')
]
  .map((img) => img.currentSrc || img.src)
  .filter(Boolean)
  .slice(-18))
""",
        timeout=20,
    )
    try:
        urls = json.loads(raw)
    except json.JSONDecodeError:
        urls = []
    paths: list[str] = []
    try:
        for index, src in enumerate(urls[:max_images], start=1):
            suffix = ".png"
            target = image_dir / f"chatgpt_image_{index:02d}{suffix}"
            if str(src).startswith("data:image/"):
                encoded = str(src).split(",", 1)[1]
                target.write_bytes(base64.b64decode(encoded))
            else:
                request = Request(str(src), headers={"User-Agent": "Safari"})
                with urlopen(request, timeout=30) as response:  # noqa: S310 - browser-provided URL.
                    target.write_bytes(response.read())
            paths.append(str(target))
    except (OSError, ValueError, URLError) as exc:
        screenshot = get_safari_executor().screenshot(directory / "image_download_failed.png")
        result = {
            "status": "IMAGE_DOWNLOAD_FAILED",
            "error": str(exc),
            "image_paths": paths,
            "screenshot": str(screenshot),
        }
        write_json_artifact(directory, "chatgpt_images.json", result)
        return json.dumps(result, ensure_ascii=False)
    result = {"status": "OK", "image_paths": paths, "artifact_dir": str(directory)}
    write_json_artifact(directory, "chatgpt_images.json", result)
    return json.dumps(result, ensure_ascii=False)


@tool(args_schema=ChatgptSaveArtifactsArgs)
def chatgpt_save_artifacts(job_id: str, name: str, content: str) -> str:
    """Save an arbitrary ChatGPT workflow artifact in the local job folder."""

    directory = _directory(job_id)
    target = write_text_artifact(directory, name, content)
    return json.dumps({"status": "OK", "path": str(target)}, ensure_ascii=False)
