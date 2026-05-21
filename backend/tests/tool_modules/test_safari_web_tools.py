from __future__ import annotations

import json
from pathlib import Path

from app.agent_framework.tool_modules import chatgpt_web, xhs_web
from app.agent_framework.tool_modules.registry import ToolRegistry
from app.agent_framework.tool_runtime import ToolRuntime


class FakeSafariExecutor:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.opened: list[str] = []
        self.js_calls: list[str] = []
        self.screenshots: list[Path] = []

    def open_url(self, url: str, *, new_tab: bool = True) -> str:
        self.opened.append(url)
        return url

    def current_state(self) -> dict:
        return {
            "url": "https://chatgpt.com/",
            "title": "ChatGPT",
            "text": "今天有什么计划？",
            "html": "",
        }

    def evaluate_js(self, script: str, **_: object) -> str:
        self.js_calls.append(script)
        if "data-message-author-role" in script:
            return (
                "```json\n"
                '{"title":"T","body":"B","hashtags":["h"],"cover_text":"C",'
                '"image_prompts":["I"],"risk_flags":[],"ai_disclosure":"AI 辅助创作"}'
                "\n```"
            )
        if "querySelector('input[placeholder=" in script:
            return json.dumps({"ok": True, "title": "T", "body": "B"}, ensure_ascii=False)
        if "DataTransfer" in script:
            return json.dumps({"ok": True, "files": 1, "name": "image.png"}, ensure_ascii=False)
        return json.dumps({"ok": True}, ensure_ascii=False)

    def screenshot(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        self.screenshots.append(path)
        return path


def test_chatgpt_send_message_requires_non_empty_prompt() -> None:
    runtime = ToolRuntime(ToolRegistry(tools=(chatgpt_web.chatgpt_send_message,)))

    result = runtime.execute("chatgpt_send_message", {"prompt": ""}, tool_call_id="tc")

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "validation_error"


def test_chatgpt_extract_latest_text_saves_raw_and_parsed_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake = FakeSafariExecutor(tmp_path)
    monkeypatch.setattr(chatgpt_web, "get_safari_executor", lambda: fake)
    monkeypatch.setattr(chatgpt_web, "XHS_JOB_ROOT", tmp_path)

    result = json.loads(chatgpt_web.chatgpt_extract_latest_text.invoke({"job_id": "job-1"}))

    assert result["status"] == "OK"
    assert result["note"]["title"] == "T"
    assert (tmp_path / "job-1" / "chatgpt_raw_output.txt").is_file()
    assert (tmp_path / "job-1" / "chatgpt_parsed.json").is_file()


def test_xhs_upload_and_prefill_tools_use_safari_and_screenshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    fake = FakeSafariExecutor(tmp_path)
    monkeypatch.setattr(xhs_web, "get_safari_executor", lambda: fake)
    monkeypatch.setattr(xhs_web, "XHS_JOB_ROOT", tmp_path)

    registry = ToolRegistry(
        tools=(
            xhs_web.xhs_upload_images,
            xhs_web.xhs_fill_title,
            xhs_web.xhs_stop_before_publish,
        )
    )
    upload = json.loads(
        registry.invoke(
            "xhs_upload_images",
            {"job_id": "job-1", "image_paths": [str(image)]},
            context={"approval_granted": True},
        )
    )
    title = json.loads(
        registry.invoke(
            "xhs_fill_title",
            {"job_id": "job-1", "title": "T"},
            context={"approval_granted": True},
        )
    )
    stop = json.loads(registry.invoke("xhs_stop_before_publish", {"job_id": "job-1"}))

    assert upload["status"] == "OK"
    assert title["status"] == "OK"
    assert stop["status"] == "READY_FOR_HUMAN_CONFIRMATION"
    assert any(path.name.startswith("xhs_upload_images") for path in fake.screenshots)
    assert all(
        "publish" not in call.lower() or "querySelectorAll" in call
        for call in fake.js_calls
    )


def test_xhs_start_note_retries_until_image_tab_is_rendered(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class SlowTabExecutor(FakeSafariExecutor):
        def evaluate_js(self, script: str, **_: object) -> str:
            self.js_calls.append(script)
            if len(self.js_calls) == 1:
                return json.dumps(
                    {"ok": False, "error": "XHS_IMAGE_TAB_NOT_FOUND"},
                    ensure_ascii=False,
                )
            return json.dumps({"ok": True, "text": "上传图文"}, ensure_ascii=False)

    fake = SlowTabExecutor(tmp_path)
    monkeypatch.setattr(xhs_web, "get_safari_executor", lambda: fake)
    monkeypatch.setattr(xhs_web, "XHS_JOB_ROOT", tmp_path)
    monkeypatch.setattr(xhs_web.time, "sleep", lambda _: None)

    registry = ToolRegistry(tools=(xhs_web.xhs_start_note,))
    result = json.loads(
        registry.invoke(
            "xhs_start_note",
            {"job_id": "job-1"},
            context={"approval_granted": True},
        )
    )

    assert result["status"] == "OK"
    assert len(fake.js_calls) == 2
