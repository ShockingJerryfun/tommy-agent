from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from langchain_core.tools import tool
from pydantic import BaseModel, Field, ValidationError

from .safari_session import (
    XHS_JOB_ROOT,
    job_dir,
    safe_job_id,
    write_json_artifact,
    write_text_artifact,
)

JSON_BLOCK_RE = re.compile(r"```(?:json|JSON)\s*(\{.*?\})\s*```", re.DOTALL)


class XhsNote(BaseModel):
    title: str = Field(..., min_length=1, max_length=80)
    body: str = Field(..., min_length=1, max_length=5000)
    hashtags: list[str] = Field(..., max_length=30)
    cover_text: str = Field(..., min_length=1, max_length=80)
    image_prompts: list[str] = Field(..., min_length=1, max_length=18)
    risk_flags: list[str] = Field(...)
    ai_disclosure: str = Field(...)


class CreateXhsContentJobArgs(BaseModel):
    topic: str = Field(..., min_length=1, max_length=300)
    audience: str = Field(default="", max_length=200)
    tone: str = Field(default="", max_length=120)
    image_count: int = Field(default=3, ge=1, le=18)
    extra_requirements: list[str] = Field(default_factory=list, max_length=20)


class BuildChatgptXhsPromptArgs(CreateXhsContentJobArgs):
    job_id: str = Field(..., min_length=1, max_length=120)


class ValidateXhsNoteJsonArgs(BaseModel):
    raw_text: str = Field(..., min_length=1)
    job_id: str | None = Field(default=None, max_length=120)


class CheckXhsContentRiskArgs(BaseModel):
    note: dict[str, Any] = Field(...)
    job_id: str | None = Field(default=None, max_length=120)


def _format_errors(exc: ValidationError) -> list[dict[str, Any]]:
    errors = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error.get("loc", ())) or "__root__"
        errors.append({"field": field, "code": error.get("type"), "message": error.get("msg")})
    return errors


def parse_xhs_note_json(raw_text: str) -> dict[str, Any]:
    match = JSON_BLOCK_RE.search(raw_text)
    if match is None:
        return {
            "status": "FORMAT_INVALID",
            "errors": [
                {"code": "missing_json_code_block", "message": "Missing fenced JSON block."}
            ],
        }
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        return {
            "status": "FORMAT_INVALID",
            "errors": [{"code": "json_decode_error", "message": exc.msg, "pos": exc.pos}],
        }
    try:
        note = XhsNote.model_validate(payload)
    except ValidationError as exc:
        return {"status": "SCHEMA_INVALID", "errors": _format_errors(exc)}
    if note.ai_disclosure != "AI 辅助创作":
        return {
            "status": "SCHEMA_INVALID",
            "errors": [
                {
                    "field": "ai_disclosure",
                    "code": "literal_mismatch",
                    "message": "ai_disclosure must be 'AI 辅助创作'.",
                }
            ],
        }
    return {"status": "OK", "note": note.model_dump()}


def detect_xhs_risks(note: dict[str, Any]) -> list[str]:
    text = "\n".join(
        [
            str(note.get("title") or ""),
            str(note.get("body") or ""),
            str(note.get("cover_text") or ""),
            " ".join(str(item) for item in note.get("hashtags") or []),
        ]
    )
    checks: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("fabricated_personal_experience", ("我亲身经历", "亲身经历", "亲测", "本人实测")),
        ("absolute_ad_claim", ("最有效", "第一", "唯一", "保证", "100%", "永久")),
        (
            "medical_financial_or_effect_claim",
            ("根治", "治愈", "疗效", "保证收益", "稳赚", "收益翻倍", "功效"),
        ),
        ("traffic_diversion", ("微信", "私信", "加群", "VX", "v信", "二维码", "链接领取")),
    )
    return [flag for flag, needles in checks if any(needle in text for needle in needles)]


@tool(args_schema=CreateXhsContentJobArgs)
def create_xhs_content_job(
    topic: str,
    audience: str = "",
    tone: str = "",
    image_count: int = 3,
    extra_requirements: list[str] | None = None,
) -> str:
    """Create a local XHS content job folder and manifest."""

    job_id = f"xhs-{uuid4().hex[:12]}"
    directory = job_dir(job_id, root=XHS_JOB_ROOT)
    manifest = {
        "status": "CREATED",
        "job_id": job_id,
        "topic": topic,
        "audience": audience,
        "tone": tone,
        "image_count": image_count,
        "extra_requirements": extra_requirements or [],
        "artifact_dir": str(directory),
    }
    write_json_artifact(directory, "manifest.json", manifest)
    return json.dumps(manifest, ensure_ascii=False)


@tool(args_schema=BuildChatgptXhsPromptArgs)
def build_chatgpt_xhs_prompt(
    job_id: str,
    topic: str,
    audience: str = "",
    tone: str = "",
    image_count: int = 3,
    extra_requirements: list[str] | None = None,
) -> str:
    """Build and persist the ChatGPT prompt for an XHS note."""

    directory = job_dir(job_id, root=XHS_JOB_ROOT)
    requirements = "\n".join(f"- {item}" for item in (extra_requirements or [])) or "- 无"
    prompt = f"""请为小红书生成一篇图文笔记内容。
必须只输出一个 ```json 代码块，不要输出代码块外文字。

主题：{topic}
目标受众：{audience or "普通小红书用户"}
语气：{tone or "自然、克制、真实，不虚构亲身经历"}
图片数量：{image_count}
额外要求：
{requirements}

JSON schema：
{{
  "title": "80字以内标题",
  "body": "正文，不能虚构亲身经历，不能有绝对化广告词、医疗/金融/功效承诺或导流",
  "hashtags": ["话题1", "话题2"],
  "cover_text": "封面文字",
  "image_prompts": ["第1张图片提示词"],
  "risk_flags": [],
  "ai_disclosure": "AI 辅助创作"
}}
"""
    write_text_artifact(directory, "chatgpt_prompt.txt", prompt)
    return json.dumps(
        {
            "status": "OK",
            "job_id": safe_job_id(job_id),
            "prompt": prompt,
            "artifact_dir": str(directory),
        },
        ensure_ascii=False,
    )


@tool(args_schema=ValidateXhsNoteJsonArgs)
def validate_xhs_note_json(raw_text: str, job_id: str | None = None) -> str:
    """Validate ChatGPT's fenced JSON response for an XHS note."""

    result = parse_xhs_note_json(raw_text)
    if job_id:
        directory = job_dir(job_id, root=XHS_JOB_ROOT)
        write_text_artifact(directory, "chatgpt_raw_output.txt", raw_text)
        write_json_artifact(directory, "chatgpt_parsed.json", result)
    return json.dumps(result, ensure_ascii=False)


@tool(args_schema=CheckXhsContentRiskArgs)
def check_xhs_content_risk(note: dict[str, Any], job_id: str | None = None) -> str:
    """Check XHS note content for common unsafe claims and diversion language."""

    risk_flags = detect_xhs_risks(note)
    result = {
        "status": "RISK_FOUND" if risk_flags else "OK",
        "risk_flags": risk_flags,
        "note": dict(note) | {"risk_flags": risk_flags},
    }
    if job_id:
        write_json_artifact(job_dir(job_id, root=XHS_JOB_ROOT), "content_risk.json", result)
    return json.dumps(result, ensure_ascii=False)
