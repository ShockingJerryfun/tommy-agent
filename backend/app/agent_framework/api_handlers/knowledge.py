from __future__ import annotations

import os
from typing import Any

from fastapi import HTTPException

from ..paths import DATA_ROOT
from ..prompt_context import merge_context_pact, normalize_context_pact
from ..runtime.compaction import compact_transcript_records
from ..server import (
    CompactSessionRequest,
    ContextPactPatchRequest,
    MemoryProposalRequest,
    MemorySearchResponse,
    SkillProposalRequest,
)
from ..skills_forge.catalog import SkillCatalog, SkillProposal
from ..storage import LocalMemoryStore


def search_messages_impl(store, q: str, limit: int) -> dict[str, list[dict[str, Any]]]:
    return {
        "results": [
            {
                "message_id": row["message_id"],
                "session_id": row["session_id"],
                "session_title": row["session_title"],
                "role": row["role"],
                "position": row["position"],
                "created_at": row["created_at"],
                "snippet": row["snippet"],
            }
            for row in store.search_messages(q, limit=limit)
        ]
    }


def search_memory_impl(store, query: str, agent_id: str, limit: int) -> MemorySearchResponse:
    results = [
        {"path": item["id"], "snippet": item["content"]}
        for item in store.search_memories(agent_id=agent_id, query=query, limit=limit)
    ]
    if not results:
        results = LocalMemoryStore(agent_id=agent_id).search(query, limit=limit)
    return MemorySearchResponse(results=results)


def create_memory_proposal_impl(store, request: MemoryProposalRequest) -> dict[str, Any]:
    proposal = store.create_memory(
        agent_id=request.agent_id,
        content=request.content,
        status="proposed",
        source_session_id=request.session_id,
        metadata=request.metadata,
    )
    return {"proposal": proposal}


def confirm_memory_impl(store, memory_id: str, agent_id: str) -> dict[str, Any]:
    memory = store.confirm_memory(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory proposal not found")
    if markdown_export_on_confirm_enabled():
        LocalMemoryStore(agent_id=agent_id, root=DATA_ROOT).append_memory_export(memory["content"])
    return {"memory": memory}


def import_markdown_memory_seed_impl(store, agent_id: str = "default") -> dict[str, Any]:
    local_store = LocalMemoryStore(agent_id=agent_id, root=DATA_ROOT)
    seed_items = local_store.read_memory_seed_items()
    existing = {
        str(item.get("content") or "").strip().casefold()
        for item in store.list_memories(agent_id=agent_id, limit=1000)
    }
    imported: list[dict[str, Any]] = []
    skipped_count = 0
    for content in seed_items:
        key = content.casefold()
        if key in existing:
            skipped_count += 1
            continue
        memory = store.create_memory(
            agent_id=agent_id,
            content=content,
            status="active",
            metadata={
                "source": "markdown_seed",
                "source_path": "MEMORY.md",
            },
        )
        existing.add(key)
        imported.append(memory)
    return {
        "imported_count": len(imported),
        "skipped_count": skipped_count,
        "memories": imported,
    }


def export_markdown_memories_impl(store, agent_id: str = "default") -> dict[str, Any]:
    memories = store.list_memories(agent_id=agent_id, status="active", limit=1000)
    path = LocalMemoryStore(agent_id=agent_id, root=DATA_ROOT).export_memories(memories)
    return {
        "exported_count": len(memories),
        "path": str(path),
    }


def markdown_export_on_confirm_enabled() -> bool:
    value = os.getenv("TOMMY_MEMORY_MARKDOWN_EXPORT_ON_CONFIRM", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def create_skill_proposal_impl(store, request: SkillProposalRequest) -> dict[str, Any]:
    catalog = SkillCatalog(agent_id=request.agent_id, store=store)
    return catalog.create_proposal(
        SkillProposal(
            name=request.name,
            action=request.action,
            rationale=request.rationale,
            content=request.content,
            relative_path=request.relative_path,
            risks=request.risks,
            metadata=request.metadata,
        ),
        allow_auto_apply=bool(request.metadata.get("allow_auto_apply")),
    )


def list_skills_impl(store, agent_id: str) -> dict[str, Any]:
    catalog = SkillCatalog(agent_id=agent_id, store=store)
    return {
        "skills": [
            {
                "name": skill.name,
                "path": skill.path,
                "description": skill.description,
                "updated_at": skill.updated_at,
            }
            for skill in catalog.list_skills()
        ],
        "proposals": catalog.list_proposals(status="proposed"),
    }


def apply_skill_proposal_impl(store, proposal_id: str, agent_id: str) -> dict[str, Any]:
    catalog = SkillCatalog(agent_id=agent_id, store=store)
    try:
        return {"proposal": catalog.apply_proposal(proposal_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def reject_skill_proposal_impl(store, proposal_id: str, agent_id: str) -> dict[str, Any]:
    catalog = SkillCatalog(agent_id=agent_id, store=store)
    try:
        return {"proposal": catalog.reject_proposal(proposal_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def read_skill_impl(store, skill_path: str, agent_id: str) -> dict[str, str]:
    catalog = SkillCatalog(agent_id=agent_id, store=store)
    try:
        return {
            "path": catalog.normalize_relative_path(skill_path),
            "content": catalog.read_skill(skill_path),
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def get_context_pact_impl(store, session_id: str, agent_id: str) -> dict[str, Any]:
    store.ensure_session(session_id, agent_id=agent_id)
    return {"pact": normalize_context_pact(store.get_context_pact(session_id, agent_id=agent_id))}


def patch_context_pact_impl(
    store, session_id: str, request: ContextPactPatchRequest
) -> dict[str, Any]:
    store.ensure_session(session_id, agent_id=request.agent_id)
    current = store.get_context_pact(session_id, agent_id=request.agent_id)
    pact = merge_context_pact(
        current,
        {
            "summary": request.summary,
            "goals": request.goals,
            "constraints": request.constraints,
            "facts": request.facts,
            "open_questions": request.open_questions,
            "active_skills": request.active_skills,
        },
    )
    store.upsert_context_pact(session_id, agent_id=request.agent_id, pact=pact)
    return {"pact": pact}


def compact_session_impl(
    store, session_id: str, request: CompactSessionRequest | None
) -> dict[str, Any]:
    payload = request or CompactSessionRequest()
    store.ensure_session(session_id, agent_id=payload.agent_id)
    messages = store.list_messages(session_id)
    result = compact_transcript_records(messages, keep_recent=payload.keep_recent)
    if not result.summary:
        return {"compaction": None, "pact": normalize_context_pact({})}
    store.set_session_summary(session_id, result.summary)
    current = store.get_context_pact(session_id, agent_id=payload.agent_id)
    pact = merge_context_pact(current, {"summary": result.summary})
    store.upsert_context_pact(session_id, agent_id=payload.agent_id, pact=pact)
    record = store.append_compaction_run(
        session_id,
        run_id=payload.run_id,
        summary=result.summary,
        message_count=len(messages),
        kept_messages=len(result.recent_tail),
        metadata={"trigger": "manual_api"},
    )
    return {"compaction": record, "pact": pact}
