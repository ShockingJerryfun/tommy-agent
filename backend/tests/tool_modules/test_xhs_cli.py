from __future__ import annotations

import json
from pathlib import Path


def test_xhs_cli_prefill_runs_browser_steps_in_order(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from app.agent_framework.cli import xhs

    image = tmp_path / "cover.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    body_file = tmp_path / "body.md"
    body_file.write_text("正文第一行\n正文第二行", encoding="utf-8")
    calls: list[tuple[str, dict, bool]] = []

    def fake_invoke_tool(name: str, args: dict, *, approval_granted: bool) -> dict:
        calls.append((name, args, approval_granted))
        if name == "xhs_stop_before_publish":
            return {
                "status": "READY_FOR_HUMAN_CONFIRMATION",
                "screenshot": "/tmp/preview.png",
                "artifact_dir": "/tmp/job",
            }
        return {"status": "OK", "artifact_dir": "/tmp/job"}

    monkeypatch.setattr(xhs, "invoke_tool", fake_invoke_tool)

    exit_code = xhs.main(
        [
            "prefill-note",
            "--job-id",
            "job-1",
            "--title",
            "测试标题",
            "--body-file",
            str(body_file),
            "--image",
            str(image),
            "--hashtag",
            "AI工具",
            "--hashtag",
            "#效率",
            "--reuse-tab",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "READY_FOR_HUMAN_CONFIRMATION"
    assert payload["steps"] == [
        "xhs_open_creator",
        "xhs_start_note",
        "xhs_upload_images",
        "xhs_fill_title",
        "xhs_fill_body",
        "xhs_fill_hashtags",
        "xhs_take_preview_screenshot",
        "xhs_stop_before_publish",
    ]
    assert [name for name, _, _ in calls] == payload["steps"]
    assert calls[0][1] == {
        "job_id": "job-1",
        "new_tab": False,
        "url": "https://creator.xiaohongshu.com/publish/publish",
    }
    assert calls[2][1] == {"job_id": "job-1", "image_paths": [str(image)]}
    assert calls[3][1] == {"job_id": "job-1", "title": "测试标题"}
    assert calls[4][1] == {"job_id": "job-1", "body": "正文第一行\n正文第二行"}
    assert calls[5][1] == {"job_id": "job-1", "hashtags": ["AI工具", "#效率"]}
    assert all(approval for _, _, approval in calls[:6])
    assert calls[6][2] is False
    assert calls[7][2] is False
