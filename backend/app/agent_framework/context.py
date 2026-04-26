from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


PACT_LIST_FIELDS = ("goals", "constraints", "facts", "open_questions", "active_skills")


def empty_context_pact() -> dict[str, Any]:
    return {
        "summary": "",
        "goals": [],
        "constraints": [],
        "facts": [],
        "open_questions": [],
        "active_skills": [],
        "updated_at": datetime.now(UTC).isoformat(),
    }


def normalize_context_pact(value: dict[str, Any] | None) -> dict[str, Any]:
    pact = empty_context_pact()
    for key, item in (value or {}).items():
        if key in PACT_LIST_FIELDS:
            pact[key] = _dedupe_strings(item if isinstance(item, list) else [item])
        elif key == "summary":
            pact[key] = str(item or "")
        else:
            pact[key] = item
    pact["updated_at"] = str(value.get("updated_at") if value else pact["updated_at"])
    return pact


def merge_context_pact(
    current: dict[str, Any] | None,
    patch: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = normalize_context_pact(current)
    incoming = patch or {}

    if "summary" in incoming:
        merged["summary"] = str(incoming.get("summary") or "")

    for field in PACT_LIST_FIELDS:
        if field in incoming:
            existing = merged.get(field) if isinstance(merged.get(field), list) else []
            incoming_items = incoming.get(field)
            if not isinstance(incoming_items, list):
                incoming_items = [incoming_items]
            merged[field] = _dedupe_strings([*existing, *incoming_items])

    for key, value in incoming.items():
        if key not in PACT_LIST_FIELDS and key != "summary":
            merged[key] = value

    merged["updated_at"] = datetime.now(UTC).isoformat()
    return merged


def pact_markdown(pact: dict[str, Any] | None) -> str:
    normalized = normalize_context_pact(pact)
    sections = [f"Summary: {normalized.get('summary') or 'No session summary yet.'}"]
    for field, label in (
        ("goals", "Goals"),
        ("constraints", "Constraints"),
        ("facts", "Facts"),
        ("open_questions", "Open Questions"),
        ("active_skills", "Active Skills"),
    ):
        values = normalized.get(field)
        if not isinstance(values, list) or not values:
            continue
        sections.append(f"{label}:\n" + "\n".join(f"- {item}" for item in values))
    return "\n\n".join(sections)


def _dedupe_strings(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
