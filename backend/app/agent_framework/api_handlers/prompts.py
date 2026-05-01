from __future__ import annotations

from fastapi import HTTPException

from ..server import CreatePromptRequest, PromptItem, UpdatePromptRequest
from ..storage.repos import PromptShortcutConflict


def list_prompts_impl(store, owner_user: str) -> dict[str, list[PromptItem]]:
    return {
        "prompts": [PromptItem(**prompt) for prompt in store.list_prompts(owner_user=owner_user)]
    }


def create_prompt_impl(store, request: CreatePromptRequest, owner_user: str) -> PromptItem:
    try:
        prompt = store.create_prompt(
            owner_user=owner_user,
            name=request.name,
            body=request.body,
            shortcut=request.shortcut,
        )
    except PromptShortcutConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PromptItem(**prompt)


def update_prompt_impl(
    store, prompt_id: str, request: UpdatePromptRequest, owner_user: str
) -> PromptItem:
    existing = store.get_prompt(prompt_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Prompt not found")
    if existing["kind"] != "user" or existing["owner_user"] != owner_user:
        raise HTTPException(status_code=403, detail="Prompt cannot be modified")
    try:
        updated = store.update_prompt(
            prompt_id,
            name=request.name,
            body=request.body,
            shortcut=request.shortcut,
        )
    except PromptShortcutConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return PromptItem(**updated)


def delete_prompt_impl(store, prompt_id: str, owner_user: str) -> dict[str, bool]:
    existing = store.get_prompt(prompt_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Prompt not found")
    if existing["kind"] != "user" or existing["owner_user"] != owner_user:
        raise HTTPException(status_code=403, detail="Prompt cannot be deleted")
    return {"deleted": store.delete_prompt(prompt_id)}
