from __future__ import annotations

import json

from app.agent_framework.tool_modules.xhs_content_ops import (
    check_xhs_content_risk,
    validate_xhs_note_json,
)


def _invoke_json(tool, args: dict) -> dict:
    return json.loads(tool.invoke(args))


def test_validate_xhs_note_json_accepts_fenced_payload() -> None:
    raw = """好的，结果如下：
```json
{
  "title": "周末咖啡店探店",
  "body": "这是一篇克制的种草文案。",
  "hashtags": ["咖啡", "周末"],
  "cover_text": "周末咖啡",
  "image_prompts": ["一张明亮咖啡店桌面的照片"],
  "risk_flags": [],
  "ai_disclosure": "AI 辅助创作"
}
```
"""

    result = _invoke_json(validate_xhs_note_json, {"raw_text": raw})

    assert result["status"] == "OK"
    assert result["note"]["title"] == "周末咖啡店探店"
    assert result["note"]["ai_disclosure"] == "AI 辅助创作"


def test_validate_xhs_note_json_rejects_missing_code_block() -> None:
    result = _invoke_json(validate_xhs_note_json, {"raw_text": '{"title":"裸 JSON"}'})

    assert result["status"] == "FORMAT_INVALID"
    assert result["errors"][0]["code"] == "missing_json_code_block"


def test_validate_xhs_note_json_rejects_schema_errors() -> None:
    raw = """```json
{"title":"少字段","body":"正文","hashtags":"咖啡"}
```"""

    result = _invoke_json(validate_xhs_note_json, {"raw_text": raw})

    assert result["status"] == "SCHEMA_INVALID"
    error_fields = {error["field"] for error in result["errors"]}
    expected_fields = {"hashtags", "cover_text", "image_prompts", "risk_flags", "ai_disclosure"}
    assert expected_fields <= error_fields


def test_check_xhs_content_risk_flags_unsafe_claims() -> None:
    note = {
        "title": "我亲测最有效的理财课",
        "body": "我亲身经历，保证收益，三天根治焦虑，微信私聊领取。",
        "hashtags": ["理财"],
        "cover_text": "保证有效",
        "image_prompts": ["课程海报"],
        "risk_flags": [],
        "ai_disclosure": "AI 辅助创作",
    }

    result = _invoke_json(check_xhs_content_risk, {"note": note})

    assert result["status"] == "RISK_FOUND"
    assert {
        "fabricated_personal_experience",
        "absolute_ad_claim",
        "medical_financial_or_effect_claim",
        "traffic_diversion",
    } <= set(result["risk_flags"])
