"""Reflector / Consolidator / Forgetter / on_pre_compact flush.

Per blueprint §13 the queue substrate is in-process ``asyncio`` for now,
so each pipeline is a plain async method on :class:`MemoryProvider` (see
``provider.py``). Keeping them as pure functions on this module lets us
test them with a stub store and call them from either the run pipeline
or a future scheduler without changes.

Heuristics here are intentionally conservative; S3+ will replace the
heuristics with LLM-driven extraction. The contract this module commits
to is the *side-effect shape*:

- :func:`reflect_messages` proposes new ``memories`` rows in ``proposed``
  status, returning the proposals it created.
- :func:`consolidate` merges duplicates (same normalised content), keeping
  the oldest row and rejecting the rest with ``metadata.duplicate_of``.
- :func:`apply_forgetting` decays the score of active memories and may
  reject items that fall below ``forget_threshold`` and ``importance_floor``.
- :func:`flush_for_compaction` is the pre-compact hook: it reflects on
  the soon-to-be-compacted message tail and writes a ``flush`` row to
  ``memory_consolidation_runs`` with the proposal ids it created.

Every pipeline writes one ``memory_consolidation_runs`` row so the audit
trail is complete.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Lightweight, deterministic patterns that mark a message as "memorable".
# S3+ will replace this with the reflector LLM node; the patterns here are
# the safety net used during pre-compact flush so we never lose user-stated
# facts when the message tail is summarised.
_USER_REMEMBER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bremember(?:\s+(?:that|this))?\b[:,]?\s*(.+)", re.IGNORECASE),
    re.compile(r"\b(?:please\s+)?(?:save|note|记住|记一下|记下)[:,]?\s*(.+)", re.IGNORECASE),
    re.compile(r"\bmy\s+name\s+is\s+(.+)", re.IGNORECASE),
    re.compile(r"\bi\s+(?:am|'m)\s+(.+)", re.IGNORECASE),
)


@dataclass(frozen=True)
class ReflectorOutput:
    proposals: list[dict[str, Any]]
    inputs_count: int
    outputs_count: int


@dataclass(frozen=True)
class ConsolidationOutput:
    merged: list[tuple[str, str]]  # (kept_id, dropped_id)
    inputs_count: int
    outputs_count: int


@dataclass(frozen=True)
class ForgetterOutput:
    decayed: int
    forgotten: int
    scanned: int


# ---------------------------------------------------------- reflector


def extract_candidates(messages: list[Any]) -> list[str]:
    """Pull memorable snippets from a message tail using the patterns above.

    Each returned string is trimmed and capped at 320 chars; downstream
    callers feed each one into :class:`MemoryRepo.create_memory` as
    ``status='proposed'``.
    """

    candidates: list[str] = []
    seen: set[str] = set()
    for message in messages:
        role = getattr(message, "role", None) or getattr(message, "type", None) or ""
        if str(role).lower() not in {"user", "human"}:
            continue
        content = getattr(message, "content", None)
        if isinstance(content, list):
            content = " ".join(str(part) for part in content)
        text = str(content or "").strip()
        if not text:
            continue
        for pattern in _USER_REMEMBER_PATTERNS:
            match = pattern.search(text)
            if match is None:
                continue
            snippet = match.group(1).strip().rstrip(".。!?")
            if not snippet:
                continue
            normalised = " ".join(snippet.split())[:320]
            if normalised and normalised.lower() not in seen:
                seen.add(normalised.lower())
                candidates.append(normalised)
    return candidates


def reflect_messages(
    store: Any,
    *,
    agent_id: str,
    session_id: str | None,
    run_id: str | None,
    messages: list[Any],
    embedder: Any | None = None,
    record_audit: bool = True,
) -> ReflectorOutput:
    """Propose memories from a message tail. Returns the proposals."""

    candidates = extract_candidates(messages)
    proposals: list[dict[str, Any]] = []
    for snippet in candidates:
        proposal = store.create_memory(
            agent_id=agent_id,
            content=snippet,
            status="proposed",
            source_session_id=session_id,
            metadata={
                "source": "reflector",
                "run_id": run_id,
                "trigger": "auto",
            },
        )
        if embedder is not None:
            try:
                vec = embedder.embed(snippet)
                if vec:
                    store.memories.update_embedding(
                        proposal["id"], embedding=vec, model=embedder.model
                    )
            except Exception:  # noqa: BLE001 — audit only
                pass
        proposals.append(proposal)

    if record_audit:
        try:
            store.consolidation_runs.append(
                agent_id=agent_id,
                session_id=session_id,
                run_id=run_id,
                kind="reflect",
                inputs_count=len(messages),
                outputs_count=len(proposals),
                summary=(
                    f"Proposed {len(proposals)} memory item(s) from {len(messages)} message(s)."
                ),
                metadata={"snippets": candidates},
            )
        except Exception:  # noqa: BLE001 — audit only
            pass

    return ReflectorOutput(
        proposals=proposals,
        inputs_count=len(messages),
        outputs_count=len(proposals),
    )


# ------------------------------------------------------- consolidator


def _normalise(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def consolidate(
    store: Any,
    *,
    agent_id: str,
    limit: int = 200,
    record_audit: bool = True,
) -> ConsolidationOutput:
    """Merge duplicate proposals/active memories.

    Two memories are duplicates iff their normalised content is identical
    (lowercased, whitespace-collapsed). The oldest survives; the rest
    flip to ``rejected`` with ``metadata.duplicate_of`` set.
    """

    rows = store.list_memories(agent_id=agent_id, limit=limit)
    by_norm: dict[str, dict[str, Any]] = {}
    merged: list[tuple[str, str]] = []
    for row in sorted(rows, key=lambda r: r.get("created_at") or ""):
        if str(row.get("status")) == "rejected":
            continue
        key = _normalise(row.get("content"))
        if not key:
            continue
        canonical = by_norm.get(key)
        if canonical is None:
            by_norm[key] = row
            continue
        store.memories.update_status(row["id"], status="rejected")
        merged.append((canonical["id"], row["id"]))

    if record_audit:
        try:
            store.consolidation_runs.append(
                agent_id=agent_id,
                session_id=None,
                run_id=None,
                kind="consolidate",
                inputs_count=len(rows),
                outputs_count=len(merged),
                summary=f"Merged {len(merged)} duplicate(s).",
                metadata={"merged": [{"kept": k, "dropped": d} for k, d in merged]},
            )
        except Exception:  # noqa: BLE001 - audit only
            pass

    return ConsolidationOutput(
        merged=merged,
        inputs_count=len(rows),
        outputs_count=len(merged),
    )


# ----------------------------------------------------------- forgetter


def apply_forgetting(
    store: Any,
    *,
    agent_id: str,
    decay_step: float = 0.02,
    forget_threshold: float = -0.5,
    importance_floor: float = 0.6,
    limit: int = 200,
    record_audit: bool = True,
) -> ForgetterOutput:
    """Decay active memories and forget the worst offenders.

    Delegates to :meth:`MemoryRepo.apply_decay` so the SQL stays in one
    place. Records an audit row by default.
    """

    repo = store.memories if hasattr(store, "memories") else store
    summary = repo.apply_decay(
        agent_id=agent_id,
        decay_step=decay_step,
        forget_threshold=forget_threshold,
        importance_floor=importance_floor,
        limit=limit,
    )
    decayed = int(summary.get("decayed", 0))
    forgotten = int(summary.get("forgotten", 0))
    scanned = int(summary.get("scanned", 0))

    if record_audit:
        try:
            store.consolidation_runs.append(
                agent_id=agent_id,
                session_id=None,
                run_id=None,
                kind="forget",
                inputs_count=scanned,
                outputs_count=forgotten,
                summary=f"Decayed {decayed}, forgot {forgotten}, scanned {scanned}.",
                metadata={
                    "decay_step": decay_step,
                    "forget_threshold": forget_threshold,
                    "importance_floor": importance_floor,
                },
            )
        except Exception:  # noqa: BLE001 - audit only
            pass

    return ForgetterOutput(decayed=decayed, forgotten=forgotten, scanned=scanned)


# --------------------------------------------------- on_pre_compact flush


def flush_for_compaction(
    store: Any,
    *,
    agent_id: str,
    session_id: str,
    run_id: str | None,
    messages: list[Any],
    embedder: Any | None = None,
) -> ReflectorOutput:
    """Pre-compaction memory flush.

    Called by the run pipeline immediately before
    ``compact_transcript_records`` rewrites the session summary. Reflects
    on the older message tail (the part about to be summarised) and
    proposes new memory items so user-stated facts survive compaction.

    A dedicated ``flush`` audit row is written separately from
    ``reflect_messages``' default ``reflect`` row so the compaction event
    can be reasoned about independently.
    """

    output = reflect_messages(
        store,
        agent_id=agent_id,
        session_id=session_id,
        run_id=run_id,
        messages=messages,
        embedder=embedder,
        record_audit=False,
    )
    try:
        store.consolidation_runs.append(
            agent_id=agent_id,
            session_id=session_id,
            run_id=run_id,
            kind="flush",
            inputs_count=output.inputs_count,
            outputs_count=output.outputs_count,
            summary=(
                "Pre-compaction flush proposed "
                f"{output.outputs_count} memory item(s) from "
                f"{output.inputs_count} message(s)."
            ),
            metadata={
                "proposal_ids": [item["id"] for item in output.proposals],
            },
        )
    except Exception:  # noqa: BLE001 - audit only
        pass
    return output
