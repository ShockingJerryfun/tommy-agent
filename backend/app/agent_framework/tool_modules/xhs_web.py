from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from .context import require_approval
from .safari_session import (
    XHS_JOB_ROOT,
    detect_browser_gate,
    get_safari_executor,
    job_dir,
    write_json_artifact,
)

XHS_CREATOR_URL = "https://creator.xiaohongshu.com/publish/publish"


class XhsOpenCreatorArgs(BaseModel):
    url: str = Field(default=XHS_CREATOR_URL, min_length=1, max_length=500)
    new_tab: bool = True
    job_id: str | None = Field(default=None, max_length=120)


class XhsJobArgs(BaseModel):
    job_id: str | None = Field(default=None, max_length=120)


class XhsUploadImagesArgs(BaseModel):
    image_paths: list[str] = Field(..., min_length=1, max_length=18)
    job_id: str | None = Field(default=None, max_length=120)


class XhsFillTitleArgs(BaseModel):
    title: str = Field(..., min_length=1, max_length=80)
    job_id: str | None = Field(default=None, max_length=120)


class XhsFillBodyArgs(BaseModel):
    body: str = Field(..., min_length=1, max_length=5000)
    job_id: str | None = Field(default=None, max_length=120)


class XhsFillHashtagsArgs(BaseModel):
    hashtags: list[str] = Field(..., min_length=1, max_length=30)
    job_id: str | None = Field(default=None, max_length=120)


def _directory(job_id: str | None) -> Path:
    return job_dir(job_id or "xhs-web", root=XHS_JOB_ROOT)


def _json_or_error(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": "INVALID_SCRIPT_RESULT", "raw": raw}
    return parsed if isinstance(parsed, dict) else {"ok": False, "raw": parsed}


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


def _screenshot_and_payload(job_id: str | None, action: str, result: dict[str, Any]) -> str:
    directory = _directory(job_id)
    screenshot = get_safari_executor().screenshot(directory / f"{action}.png")
    status = "OK" if result.get("ok", True) else str(result.get("error") or f"{action}_FAILED")
    payload = {
        "status": status,
        "result": result,
        "screenshot": str(screenshot),
        "artifact_dir": str(directory),
    }
    write_json_artifact(directory, f"{action}.json", payload)
    return json.dumps(payload, ensure_ascii=False)


@tool(args_schema=XhsOpenCreatorArgs)
def xhs_open_creator(
    url: str = XHS_CREATOR_URL,
    new_tab: bool = True,
    job_id: str | None = None,
) -> str:
    """Open the XHS creator page in Safari."""

    require_approval("xhs_open_creator")
    executor = get_safari_executor()
    opened = executor.open_url(url, new_tab=new_tab)
    state = executor.current_state()
    status = detect_browser_gate(state)
    directory = _directory(job_id)
    screenshot = executor.screenshot(directory / "xhs_open_creator.png")
    result = {
        "status": status,
        "url": opened,
        "state": state,
        "screenshot": str(screenshot),
        "artifact_dir": str(directory),
    }
    write_json_artifact(directory, "xhs_open_creator.json", result)
    return json.dumps(result, ensure_ascii=False)


@tool(args_schema=XhsJobArgs)
def xhs_start_note(job_id: str | None = None) -> str:
    """Switch the XHS creator page to image-note mode."""

    require_approval("xhs_start_note")
    blocked = _gate_result(job_id, "xhs_start_note")
    if blocked:
        return json.dumps(blocked, ensure_ascii=False)
    script = """
(() => {
  const tabs = [...document.querySelectorAll('.creator-tab')];
  const tab = tabs.find((node) => node.innerText.trim() === '上传图文'
    && !(node.getAttribute('style') || '').includes('-9999'))
    || tabs.find((node) => node.innerText.trim() === '上传图文');
  if (!tab) return JSON.stringify({ok:false, error:'XHS_IMAGE_TAB_NOT_FOUND'});
  ['pointerdown','mousedown','mouseup','pointerup','click'].forEach((type) => {
    tab.dispatchEvent(new MouseEvent(type, {bubbles:true, cancelable:true, view:window}));
  });
  return JSON.stringify({ok:true, text:tab.innerText.trim()});
})()
"""
    result: dict[str, Any] = {"ok": False, "error": "XHS_IMAGE_TAB_NOT_FOUND"}
    for attempt in range(1, 7):
        raw = get_safari_executor().evaluate_js(script, timeout=20)
        result = _json_or_error(raw)
        result["attempt"] = attempt
        if result.get("ok") or result.get("error") != "XHS_IMAGE_TAB_NOT_FOUND":
            break
        time.sleep(1)
    return _screenshot_and_payload(job_id, "xhs_start_note", result)


@tool(args_schema=XhsUploadImagesArgs)
def xhs_upload_images(image_paths: list[str], job_id: str | None = None) -> str:
    """Upload local images to the XHS creator page without publishing."""

    require_approval("xhs_upload_images")
    blocked = _gate_result(job_id, "xhs_upload_images")
    if blocked:
        return json.dumps(blocked, ensure_ascii=False)
    files = []
    for raw_path in image_paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Image does not exist: {raw_path}")
        suffix = path.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg"}:
            raise ValueError(f"Unsupported XHS image type: {raw_path}")
        mime = "image/png" if suffix == ".png" else "image/jpeg"
        files.append({
            "name": path.name,
            "mime": mime,
            "base64": base64.b64encode(path.read_bytes()).decode("ascii"),
        })
    script = f"""
(() => {{
  const input = document.querySelector('input[type=file].upload-input')
    || document.querySelector('input[type=file][accept*=png]')
    || document.querySelector('input[type=file]');
  if (!input) return JSON.stringify({{ok:false, error:'XHS_FILE_INPUT_NOT_FOUND'}});
  const data = {json.dumps(files)};
  const dt = new DataTransfer();
  for (const item of data) {{
    const bin = atob(item.base64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
    dt.items.add(new File([bytes], item.name, {{type:item.mime}}));
  }}
  input.files = dt.files;
  input.dispatchEvent(new Event('input', {{bubbles:true}}));
  input.dispatchEvent(new Event('change', {{bubbles:true}}));
  return JSON.stringify({{ok:true, files:input.files.length}});
}})()
"""
    raw = get_safari_executor().evaluate_js(script, timeout=60)
    result = _json_or_error(raw)
    result["image_paths"] = image_paths
    return _screenshot_and_payload(job_id, "xhs_upload_images", result)


@tool(args_schema=XhsFillTitleArgs)
def xhs_fill_title(title: str, job_id: str | None = None) -> str:
    """Fill the XHS note title."""

    require_approval("xhs_fill_title")
    blocked = _gate_result(job_id, "xhs_fill_title")
    if blocked:
        return json.dumps(blocked, ensure_ascii=False)
    script = f"""
(() => {{
  const title = document.querySelector('input[placeholder="填写标题会有更多赞哦"]');
  if (!title) return JSON.stringify({{ok:false, error:'XHS_TITLE_INPUT_NOT_FOUND'}});
  const value = {json.dumps(title, ensure_ascii=False)};
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(title, value);
  title.dispatchEvent(new InputEvent(
    'input',
    {{bubbles:true, inputType:'insertText', data:value}}
  ));
  title.dispatchEvent(new Event('change', {{bubbles:true}}));
  return JSON.stringify({{ok:true, title:title.value}});
}})()
"""
    result = _json_or_error(get_safari_executor().evaluate_js(script))
    return _screenshot_and_payload(job_id, "xhs_fill_title", result)


@tool(args_schema=XhsFillBodyArgs)
def xhs_fill_body(body: str, job_id: str | None = None) -> str:
    """Fill the XHS note body."""

    require_approval("xhs_fill_body")
    blocked = _gate_result(job_id, "xhs_fill_body")
    if blocked:
        return json.dumps(blocked, ensure_ascii=False)
    script = f"""
(() => {{
  const body = document.querySelector('.ProseMirror[contenteditable="true"], .ProseMirror');
  if (!body) return JSON.stringify({{ok:false, error:'XHS_BODY_INPUT_NOT_FOUND'}});
  const value = {json.dumps(body, ensure_ascii=False)};
  body.focus();
  document.execCommand('selectAll', false, null);
  document.execCommand('insertText', false, value);
  body.dispatchEvent(new InputEvent('input', {{bubbles:true, inputType:'insertText', data:value}}));
  return JSON.stringify({{ok:true, body:body.innerText}});
}})()
"""
    result = _json_or_error(get_safari_executor().evaluate_js(script))
    return _screenshot_and_payload(job_id, "xhs_fill_body", result)


@tool(args_schema=XhsFillHashtagsArgs)
def xhs_fill_hashtags(hashtags: list[str], job_id: str | None = None) -> str:
    """Append hashtags to the XHS note body."""

    require_approval("xhs_fill_hashtags")
    blocked = _gate_result(job_id, "xhs_fill_hashtags")
    if blocked:
        return json.dumps(blocked, ensure_ascii=False)
    normalized = " ".join(f"#{tag.lstrip('#')}" for tag in hashtags)
    normalized_json = json.dumps(normalized, ensure_ascii=False)
    script = f"""
(() => {{
  const body = document.querySelector('.ProseMirror[contenteditable="true"], .ProseMirror');
  if (!body) return JSON.stringify({{ok:false, error:'XHS_BODY_INPUT_NOT_FOUND'}});
  const current = body.innerText || '';
  const value = `${{current.trim()}}\\n\\n` + {normalized_json};
  body.focus();
  document.execCommand('selectAll', false, null);
  document.execCommand('insertText', false, value);
  body.dispatchEvent(new InputEvent('input', {{bubbles:true, inputType:'insertText', data:value}}));
  return JSON.stringify({{ok:true, body:body.innerText}});
}})()
"""
    result = _json_or_error(get_safari_executor().evaluate_js(script))
    return _screenshot_and_payload(job_id, "xhs_fill_hashtags", result)


@tool(args_schema=XhsJobArgs)
def xhs_take_preview_screenshot(job_id: str | None = None) -> str:
    """Take a screenshot of the current XHS creator preview."""

    directory = _directory(job_id)
    screenshot = get_safari_executor().screenshot(directory / "xhs_preview.png")
    result = {"status": "OK", "screenshot": str(screenshot), "artifact_dir": str(directory)}
    write_json_artifact(directory, "xhs_preview.json", result)
    return json.dumps(result, ensure_ascii=False)


@tool(args_schema=XhsJobArgs)
def xhs_stop_before_publish(job_id: str | None = None) -> str:
    """Stop before the publish button and wait for human confirmation."""

    blocked = _gate_result(job_id, "xhs_stop_before_publish")
    if blocked:
        return json.dumps(blocked, ensure_ascii=False)
    raw = get_safari_executor().evaluate_js(
        """
JSON.stringify({
  publish_buttons: [...document.querySelectorAll('button')]
    .map((button, index) => ({
      index,
      text:(button.innerText || '').trim(),
      disabled:button.disabled
    }))
    .filter((button) => button.text.includes('发布')),
  url: location.href
})
""",
        timeout=20,
    )
    result = _json_or_error(raw)
    directory = _directory(job_id)
    screenshot = get_safari_executor().screenshot(directory / "xhs_stop_before_publish.png")
    payload = {
        "status": "READY_FOR_HUMAN_CONFIRMATION",
        "result": result,
        "screenshot": str(screenshot),
        "artifact_dir": str(directory),
    }
    write_json_artifact(directory, "xhs_stop_before_publish.json", payload)
    return json.dumps(payload, ensure_ascii=False)
