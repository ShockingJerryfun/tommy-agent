from __future__ import annotations

import pytest

from app.agent_framework.skill_runtime.metadata import (
    normalize_skill_relative_path,
    parse_skill_markdown,
)
from app.agent_framework.skill_runtime.types import SkillMetadata


def test_parse_skill_markdown_frontmatter_body_and_signature():
    document = parse_skill_markdown(
        """---
name: browser
description: Browser automation helpers.
required_tools:
  - browser.open
  - browser.click
triggers:
  - inspect localhost
  - screenshot
domains: [frontend, qa]
platforms:
  - web
safety_notes:
  - Ask before destructive navigation.
allowed_tools:
  - Bash
  - browser.open
user_invocable: true
disable_model_invocation: false
metadata:
  hermes:
    role: browser-worker
    handoff_triggers:
      - visual check
---

# Browser Skill

Use the browser for local UI verification.
""",
        source_path="skills/browser/SKILL.md",
    )

    assert document.metadata == SkillMetadata(
        name="browser",
        description="Browser automation helpers.",
        source_path="skills/browser/SKILL.md",
        required_tools=("browser.open", "browser.click"),
        triggers=("inspect localhost", "screenshot"),
        domains=("frontend", "qa"),
        platforms=("web",),
        safety_notes=("Ask before destructive navigation.",),
        allowed_tools=("Bash", "browser.open"),
        user_invocable=True,
        disable_model_invocation=False,
        hermes={"role": "browser-worker", "handoff_triggers": ("visual check",)},
    )
    assert document.body == "# Browser Skill\n\nUse the browser for local UI verification.\n"
    assert document.signature_text == (
        "allowed_tools=Bash,browser.open\n"
        "description=Browser automation helpers.\n"
        "disable_model_invocation=false\n"
        "domains=frontend,qa\n"
        "hermes.handoff_triggers=visual check\n"
        "hermes.role=browser-worker\n"
        "name=browser\n"
        "platforms=web\n"
        "required_tools=browser.open,browser.click\n"
        "safety_notes=Ask before destructive navigation.\n"
        "source_path=skills/browser/SKILL.md\n"
        "triggers=inspect localhost,screenshot\n"
        "user_invocable=true"
    )


def test_parse_skill_markdown_allows_missing_frontmatter():
    document = parse_skill_markdown("# Title\n\nBody only.\n")

    assert document.metadata == SkillMetadata()
    assert document.body == "# Title\n\nBody only.\n"
    assert document.signature_text == (
        "disable_model_invocation=false\n"
        "user_invocable=false"
    )


@pytest.mark.parametrize("bad_path", ["/tmp/SKILL.md", "../SKILL.md", "skills/../secret.md"])
def test_normalize_skill_relative_path_rejects_unsafe_paths(bad_path):
    with pytest.raises(ValueError):
        normalize_skill_relative_path(bad_path)


def test_parse_skill_markdown_rejects_unsafe_source_path():
    with pytest.raises(ValueError):
        parse_skill_markdown("---\nname: unsafe\n---\n", source_path="../SKILL.md")


def test_allowed_tools_are_tool_names_not_paths():
    document = parse_skill_markdown("---\nallowed_tools:\n  - ../not-a-path\n---\n")

    assert document.metadata.allowed_tools == ("../not-a-path",)
