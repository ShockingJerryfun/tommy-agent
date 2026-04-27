"""Built-in hooks shipped with the framework.

Each builder returns a ``(name, callable)``-style :class:`HookRegistration`
spec via the registry's ``register`` method. The hooks are intentionally
small, idempotent, and side-effect-bounded:

- :func:`make_memory_flush_hook` — pre-compact pass that flushes any
  user-stated facts into proposed memories before the run summarises
  the conversation.
- :func:`make_stale_approval_cleanup_hook` — run-end pass that resolves
  approvals stuck pending past a TTL as ``rejected``.
- :func:`make_checkpoint_prune_hook` — run-end pass that asks the
  checkpointer to drop transient threads (best-effort; no-op if the
  checkpointer doesn't expose ``delete_thread``).

Tests can also use :func:`install_builtin_hooks` to wire all three at
once against an injected registry.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .context import HookContext
from .phases import HookPhase
from .registry import HookRegistry

# --------------------------------------------------------------------- memory


def make_memory_flush_hook(
    store: Any,
    *,
    name: str = "memory.flush_before_compact",
) -> tuple[str, HookPhase, Callable[[HookContext], None]]:
    def _hook(ctx: HookContext) -> None:
        from ..memory_platform import get_default_memory_provider

        session_id = ctx.session_id or str(ctx.payload.get("session_id") or "")
        agent_id = ctx.agent_id or str(ctx.payload.get("agent_id") or "default")
        if not session_id:
            return
        messages = list(ctx.payload.get("messages") or [])
        if not messages:
            return
        provider = get_default_memory_provider(store)
        provider.on_pre_compact_flush(
            session_id=session_id,
            agent_id=agent_id,
            messages=messages,
        )

    return (name, HookPhase.PRE_COMPACT, _hook)


# --------------------------------------------------------------------- approvals


def make_stale_approval_cleanup_hook(
    store: Any,
    *,
    ttl_seconds: int = 60 * 60 * 6,
    name: str = "approvals.cleanup_stale",
) -> tuple[str, HookPhase, Callable[[HookContext], None]]:
    def _hook(ctx: HookContext) -> None:
        cutoff = datetime.now(UTC) - timedelta(seconds=ttl_seconds)
        session_id = ctx.session_id or None
        pending = store.list_approval_requests(session_id=session_id, status="pending")
        for request in pending:
            created_raw = request.get("created_at") or ""
            try:
                created_at = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
            except ValueError:
                continue
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            if created_at < cutoff:
                try:
                    store.resolve_approval_request(
                        request["id"],
                        status="rejected",
                        result="",
                        error="approval expired (stale > TTL)",
                    )
                except Exception:  # noqa: BLE001 — best-effort cleanup.
                    continue

    return (name, HookPhase.RUN_END, _hook)


# --------------------------------------------------------------------- checkpoint


def make_checkpoint_prune_hook(
    checkpointer: Any | None,
    *,
    name: str = "checkpoint.prune_run",
) -> tuple[str, HookPhase, Callable[[HookContext], None]]:
    def _hook(ctx: HookContext) -> None:
        if checkpointer is None or not ctx.session_id:
            return
        if not ctx.payload.get("prune_checkpoint"):
            return
        delete = getattr(checkpointer, "delete_thread", None)
        if delete is None:
            return
        try:
            delete(ctx.session_id)
        except Exception:  # noqa: BLE001 — best-effort prune.
            return

    return (name, HookPhase.RUN_END, _hook)


# --------------------------------------------------------------------- bundle


@dataclass(frozen=True)
class BuiltinHookSet:
    memory_flush: str
    stale_approval_cleanup: str
    checkpoint_prune: str


def install_builtin_hooks(
    registry: HookRegistry,
    *,
    store: Any | None = None,
    checkpointer: Any | None = None,
    approval_ttl_seconds: int = 60 * 60 * 6,
) -> BuiltinHookSet:
    """Register the canonical built-in hook set on ``registry``.

    Each hook is registered with ``failure_policy="warn"`` so a misbehaving
    extension can never block a turn.
    """

    if store is not None:
        n1, p1, h1 = make_memory_flush_hook(store)
        registry.register(
            name=n1,
            phase=p1,
            callable=h1,
            order=10,
            timeout_seconds=15.0,
            failure_policy="warn",
        )
        n2, p2, h2 = make_stale_approval_cleanup_hook(
            store, ttl_seconds=approval_ttl_seconds
        )
        registry.register(
            name=n2,
            phase=p2,
            callable=h2,
            order=80,
            timeout_seconds=10.0,
            failure_policy="warn",
        )
    else:
        n1, n2 = "memory.flush_before_compact", "approvals.cleanup_stale"

    n3, p3, h3 = make_checkpoint_prune_hook(checkpointer)
    registry.register(
        name=n3,
        phase=p3,
        callable=h3,
        order=90,
        timeout_seconds=5.0,
        failure_policy="ignore",
    )

    return BuiltinHookSet(
        memory_flush=n1,
        stale_approval_cleanup=n2,
        checkpoint_prune=n3,
    )
