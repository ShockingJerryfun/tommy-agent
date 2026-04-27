"""S4 ToolRuntime executor — validate → permission → run → persist → artifact.

The runtime is intentionally a small composition layer on top of the
existing :class:`~app.agent_framework.tools.ToolRegistry`. It does *not*
own tool definitions; it owns the policy & lifecycle around invoking
them so that:

- Argument validation produces a structured ``ToolError`` instead of a
  raw string.
- Permission gating is data-driven (``permissions.yaml``) and outright
  denials short-circuit before the tool runs.
- Every invocation persists a row in ``tool_calls`` with normalised
  status (``ok`` / ``error`` / ``pending_approval``).
- Outputs larger than ``ARTIFACT_SPILL_THRESHOLD`` bytes are auto-spilled
  to ``tool_artifacts`` and the ``ToolMessage`` content becomes a compact
  reference JSON instead.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from ..tools import RUNTIME_TOOL_CONTEXT, ToolRegistry
from .permissions import PermissionDecision, PermissionPolicy, default_permission_policy
from .result import ArtifactRef, ToolError, ToolResult


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


# 8 KiB by default; tunable per environment for token-budget tuning.
ARTIFACT_SPILL_THRESHOLD = _env_int("TOMMY_TOOL_ARTIFACT_SPILL_BYTES", 8 * 1024)
PREVIEW_CHARS = _env_int("TOMMY_TOOL_ARTIFACT_PREVIEW_CHARS", 480)


@dataclass(frozen=True)
class _ValidationOutcome:
    args: dict[str, Any]
    error: ToolError | None


class ToolRuntime:
    """Stateless executor wrapping a :class:`ToolRegistry`.

    A runtime can be reused across many calls; persistence side effects
    flow through the ``store`` instance the caller provides on
    ``execute``. Keeping the store off the constructor keeps the runtime
    cheap to instantiate (and trivially mockable in unit tests).
    """

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        policy: PermissionPolicy | None = None,
        spill_threshold_bytes: int | None = None,
    ) -> None:
        self.registry = registry
        self.policy = policy or default_permission_policy()
        self.spill_threshold_bytes = (
            spill_threshold_bytes
            if spill_threshold_bytes is not None
            else ARTIFACT_SPILL_THRESHOLD
        )

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------
    def execute(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        tool_call_id: str,
        context: dict[str, Any] | None = None,
        store: Any | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        command_scope: str = "restricted",
        persist: bool = True,
    ) -> ToolResult:
        ctx = dict(context or {})
        normalized_args = dict(args or {})

        # 1. validate -------------------------------------------------------
        validation = self._validate(name, normalized_args)
        if validation.error is not None:
            result = ToolResult(
                name=name,
                tool_call_id=tool_call_id,
                status="error",
                content=validation.error.to_message(),
                error=validation.error,
            )
            self._maybe_persist(
                store=store,
                session_id=session_id,
                run_id=run_id,
                tool_call_id=tool_call_id,
                name=name,
                args=normalized_args,
                result=result,
                persist=persist,
            )
            return result

        # 2. permission ------------------------------------------------------
        decision = self.policy.evaluate(name, validation.args, command_scope=command_scope)
        if decision.denied:
            err = ToolError(
                code="permission_denied",
                message=decision.deny_reason or "Tool call denied by permission policy.",
                details={"tool": name, "risk": decision.risk_level},
            )
            result = ToolResult(
                name=name,
                tool_call_id=tool_call_id,
                status="error",
                content=err.to_message(),
                error=err,
                metadata={"permission": decision.to_dict()},
            )
            self._maybe_persist(
                store=store,
                session_id=session_id,
                run_id=run_id,
                tool_call_id=tool_call_id,
                name=name,
                args=validation.args,
                result=result,
                persist=persist,
            )
            return result

        if decision.needs_approval and not ctx.get("approval_granted"):
            # ``pending_approval`` is intentionally surfaced as ``status="pending_approval"``
            # rather than ``error`` — the action node still queues the request and
            # returns the pending message; this branch only fires when callers use
            # ToolRuntime directly without an external approval layer.
            return self._build_pending_result(
                name=name,
                tool_call_id=tool_call_id,
                decision=decision,
                args=validation.args,
            )

        # 3. run -------------------------------------------------------------
        ctx.setdefault("session_id", session_id)
        if run_id is not None:
            ctx.setdefault("run_id", run_id)

        started = time.perf_counter()
        token = RUNTIME_TOOL_CONTEXT.set(ctx)
        try:
            try:
                raw = self._invoke_tool(name, validation.args)
            except KeyError as exc:
                err = ToolError(
                    code="not_found",
                    message=str(exc),
                    details={"tool": name},
                )
                result = ToolResult(
                    name=name,
                    tool_call_id=tool_call_id,
                    status="error",
                    content=err.to_message(),
                    error=err,
                )
            except Exception as exc:  # noqa: BLE001 — surface to model
                err = ToolError(
                    code="runtime_error",
                    message=f"{type(exc).__name__}: {exc}",
                    details={"tool": name},
                )
                result = ToolResult(
                    name=name,
                    tool_call_id=tool_call_id,
                    status="error",
                    content=err.to_message(),
                    error=err,
                )
            else:
                content = raw if isinstance(raw, str) else json.dumps(
                    raw, ensure_ascii=False, default=str
                )
                size = len(content.encode("utf-8", errors="replace"))
                result = ToolResult(
                    name=name,
                    tool_call_id=tool_call_id,
                    status="ok",
                    content=content,
                    raw_size_bytes=size,
                    metadata={"latency_ms": int((time.perf_counter() - started) * 1000)},
                )
        finally:
            RUNTIME_TOOL_CONTEXT.reset(token)

        # 4. artifact (auto-spill) ------------------------------------------
        if (
            result.ok
            and store is not None
            and session_id
            and result.raw_size_bytes >= self.spill_threshold_bytes
        ):
            artifact = self._spill(
                store=store,
                session_id=session_id,
                run_id=run_id,
                tool_call_id=tool_call_id,
                tool_name=name,
                body=result.content,
            )
            preview = result.content[:PREVIEW_CHARS]
            result = ToolResult(
                name=name,
                tool_call_id=tool_call_id,
                status="ok",
                content=artifact.to_message(preview=preview),
                raw_size_bytes=result.raw_size_bytes,
                spilled=True,
                artifact=artifact,
                metadata=dict(result.metadata) | {"spilled": True},
            )

        # 5. persist ---------------------------------------------------------
        self._maybe_persist(
            store=store,
            session_id=session_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            name=name,
            args=validation.args,
            result=result,
            persist=persist,
        )
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _invoke_tool(self, name: str, args: dict[str, Any]) -> Any:
        tool_ = self.registry.by_name.get(name)
        if tool_ is None:
            raise KeyError(f"Unknown tool: {name}")
        return tool_.invoke(args)

    def _validate(self, name: str, args: dict[str, Any]) -> _ValidationOutcome:
        tool_ = self.registry.by_name.get(name)
        if tool_ is None:
            return _ValidationOutcome(
                args=args,
                error=ToolError(
                    code="not_found",
                    message=f"Unknown tool: {name}",
                    details={"tool": name},
                ),
            )

        schema_cls = getattr(tool_, "args_schema", None)
        if isinstance(schema_cls, type) and issubclass(schema_cls, BaseModel):
            try:
                model = schema_cls.model_validate(args)
            except ValidationError as exc:
                return _ValidationOutcome(
                    args=args,
                    error=ToolError(
                        code="validation_error",
                        message=f"Invalid arguments for {name}.",
                        details={"tool": name, "errors": exc.errors()},
                    ),
                )
            return _ValidationOutcome(args=model.model_dump(exclude_unset=False), error=None)
        return _ValidationOutcome(args=args, error=None)

    def _build_pending_result(
        self,
        *,
        name: str,
        tool_call_id: str,
        decision: PermissionDecision,
        args: dict[str, Any],
    ) -> ToolResult:
        payload = {
            "status": "pending_approval",
            "tool_name": name,
            "summary": decision.summary,
            "risk_level": decision.risk_level,
            "args": args,
        }
        return ToolResult(
            name=name,
            tool_call_id=tool_call_id,
            status="pending_approval",
            content=json.dumps(payload, ensure_ascii=False, default=str),
            metadata={"permission": decision.to_dict()},
        )

    def _spill(
        self,
        *,
        store: Any,
        session_id: str,
        run_id: str | None,
        tool_call_id: str,
        tool_name: str,
        body: str,
    ) -> ArtifactRef:
        repo = getattr(store, "tool_artifacts", None)
        if repo is None:
            raise RuntimeError(
                "ToolRuntime auto-spill requires store.tool_artifacts; "
                "this PostgresAgentStore appears stale."
            )
        record = repo.create(
            session_id=session_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            body=body,
        )
        return ArtifactRef(
            artifact_id=record["id"],
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            size_bytes=record["size_bytes"],
            sha256=record["sha256"],
            mime=record.get("mime", "text/plain"),
        )

    def _maybe_persist(
        self,
        *,
        store: Any | None,
        session_id: str | None,
        run_id: str | None,
        tool_call_id: str,
        name: str,
        args: dict[str, Any],
        result: ToolResult,
        persist: bool,
    ) -> None:
        if not persist or store is None or not session_id:
            return
        try:
            store.upsert_tool_call(
                session_id,
                run_id=str(run_id or f"run-{session_id}"),
                tool_call_id=tool_call_id,
                name=name,
                status=result.status,
                args=args,
                result=result.content,
            )
        except Exception:  # noqa: BLE001 — persistence failures must not break the turn.
            pass


def make_tool_runtime(
    registry: ToolRegistry,
    *,
    policy: PermissionPolicy | None = None,
) -> ToolRuntime:
    """Convenience factory for callers that don't want to import ``ToolRuntime`` directly."""

    return ToolRuntime(registry, policy=policy)
