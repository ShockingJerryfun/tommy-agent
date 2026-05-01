"""Phased hook registry with order, timeout, and failure policy.

Design constraints (blueprint §13):

- Phases are closed (see :class:`HookPhase`). Hooks register against
  a single phase.
- Order is deterministic: hooks are sorted by ``order`` ascending,
  then by registration time. ``order`` defaults to 100.
- Timeout is per-hook. A hook that exceeds its timeout is killed via
  the dispatcher and recorded as ``timeout``. Subsequent hooks still
  run.
- Failure policy is per-hook:

  - ``ignore`` — log the error, continue.
  - ``warn``   — record the error in the outcome, continue.
  - ``halt``   — record the error and stop dispatch; remaining hooks
    are reported as ``skipped``.

- Dispatch is synchronous and never raises out of the registry. The
  caller inspects the returned outcomes if it cares.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from itertools import count
from typing import Literal

from .context import HookContext, HookOutcome
from .phases import HookPhase

HookCallable = Callable[[HookContext], None]
HookFailurePolicy = Literal["ignore", "warn", "halt"]


@dataclass(frozen=True)
class HookRegistration:
    name: str
    phase: HookPhase
    callable: HookCallable
    order: int = 100
    timeout_seconds: float = 5.0
    failure_policy: HookFailurePolicy = "warn"
    seq: int = 0


class HookRegistry:
    """Thread-safe registry of phased hooks with timeout + failure policy."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hooks: dict[HookPhase, list[HookRegistration]] = {phase: [] for phase in HookPhase}
        self._counter = count()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tommy-hook")

    # ----------------------------------------------------------------- registration

    def register(
        self,
        *,
        name: str,
        phase: HookPhase,
        callable: HookCallable,
        order: int = 100,
        timeout_seconds: float = 5.0,
        failure_policy: HookFailurePolicy = "warn",
    ) -> HookRegistration:
        if not name:
            raise ValueError("hook name is required")
        if not callable:
            raise ValueError("hook callable is required")
        with self._lock:
            registration = HookRegistration(
                name=name,
                phase=phase,
                callable=callable,
                order=int(order),
                timeout_seconds=float(timeout_seconds),
                failure_policy=failure_policy,
                seq=next(self._counter),
            )
            self._hooks[phase].append(registration)
        return registration

    def unregister(self, *, name: str, phase: HookPhase | None = None) -> int:
        """Remove all hooks named ``name``. Returns the count removed."""

        removed = 0
        with self._lock:
            phases = [phase] if phase is not None else list(HookPhase)
            for ph in phases:
                before = len(self._hooks[ph])
                self._hooks[ph] = [h for h in self._hooks[ph] if h.name != name]
                removed += before - len(self._hooks[ph])
        return removed

    def list(self, phase: HookPhase | None = None) -> list[HookRegistration]:
        with self._lock:
            if phase is None:
                return [h for hs in self._hooks.values() for h in hs]
            return list(self._hooks[phase])

    def clear(self) -> None:
        with self._lock:
            for phase in HookPhase:
                self._hooks[phase].clear()

    # ----------------------------------------------------------------- dispatch

    def dispatch(
        self,
        phase: HookPhase,
        context: HookContext | None = None,
    ) -> list[HookOutcome]:
        ctx = context or HookContext(phase=phase)
        if ctx.phase != phase:
            ctx = HookContext(
                phase=phase,
                session_id=ctx.session_id,
                run_id=ctx.run_id,
                agent_id=ctx.agent_id,
                payload=dict(ctx.payload),
                data=dict(ctx.data),
            )
        with self._lock:
            ordered = sorted(self._hooks[phase], key=lambda h: (h.order, h.seq))

        outcomes: list[HookOutcome] = []
        halted = False
        for registration in ordered:
            if halted:
                outcomes.append(
                    HookOutcome(
                        name=registration.name,
                        phase=phase,
                        status="skipped",
                        duration_ms=0.0,
                    )
                )
                continue
            outcome = self._invoke(registration, ctx)
            outcomes.append(outcome)
            if outcome.status in {"error", "timeout"} and registration.failure_policy == "halt":
                halted = True
        return outcomes

    def _invoke(
        self,
        registration: HookRegistration,
        context: HookContext,
    ) -> HookOutcome:
        start = time.perf_counter()
        try:
            future = self._executor.submit(registration.callable, context)
            future.result(timeout=registration.timeout_seconds)
        except FutureTimeoutError:
            return HookOutcome(
                name=registration.name,
                phase=registration.phase,
                status="timeout",
                duration_ms=(time.perf_counter() - start) * 1000.0,
                error=f"hook exceeded {registration.timeout_seconds}s",
            )
        except Exception as exc:  # noqa: BLE001 — registry never raises out.
            return HookOutcome(
                name=registration.name,
                phase=registration.phase,
                status="error",
                duration_ms=(time.perf_counter() - start) * 1000.0,
                error=f"{type(exc).__name__}: {exc}",
            )
        return HookOutcome(
            name=registration.name,
            phase=registration.phase,
            status="ok",
            duration_ms=(time.perf_counter() - start) * 1000.0,
        )

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------- default

_DEFAULT: HookRegistry | None = None
_DEFAULT_LOCK = threading.Lock()


def default_hook_registry() -> HookRegistry:
    """Return a process-wide default registry (lazy)."""

    global _DEFAULT
    if _DEFAULT is None:
        with _DEFAULT_LOCK:
            if _DEFAULT is None:
                _DEFAULT = HookRegistry()
    return _DEFAULT


def reset_default_hook_registry() -> None:
    """Tests reset the global registry between cases."""

    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is not None:
            _DEFAULT.shutdown()
        _DEFAULT = None
