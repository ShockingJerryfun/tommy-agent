"""Deterministic workflow worker cache key helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def workflow_worker_input_hash(
    *,
    role_id: str,
    prompt: str,
    workflow_spec_id: str,
    workflow_phase_id: str,
    item: Any,
    agent_definition_version: str = "",
) -> str:
    payload = {
        "agent_definition_version": agent_definition_version,
        "item": item,
        "prompt": prompt,
        "role_id": role_id,
        "workflow_phase_id": workflow_phase_id,
        "workflow_spec_id": workflow_spec_id,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
