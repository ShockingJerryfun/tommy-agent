"""OpenTelemetry tracer thin wrapper with safe no-op fallback.

We use ``opentelemetry-api`` for symbol resolution but never assume
an SDK / exporter is configured. If no SDK is set up, ``trace.get_tracer``
returns a no-op tracer; the code paths still work and tests stay
hermetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

try:  # opentelemetry-api ships with a no-op default provider.
    from opentelemetry import trace as _otel_trace

    _OTEL_AVAILABLE = True
except Exception:  # noqa: BLE001 — keep module importable without OTel.
    _otel_trace = None  # type: ignore[assignment]
    _OTEL_AVAILABLE = False


_DEFAULT_TRACER_NAME = "tommy.agent"


def get_tracer(name: str = _DEFAULT_TRACER_NAME) -> Any:
    """Return an OTel tracer (or a no-op shim)."""

    if _OTEL_AVAILABLE and _otel_trace is not None:
        return _otel_trace.get_tracer(name)
    return _NoopTracer()


@contextmanager
def span(name: str, *, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """Open an OTel span. Safe regardless of provider configuration."""

    tracer = get_tracer()
    if hasattr(tracer, "start_as_current_span"):
        with tracer.start_as_current_span(name) as current_span:
            if attributes and hasattr(current_span, "set_attribute"):
                for key, value in attributes.items():
                    try:
                        current_span.set_attribute(key, _coerce_attr(value))
                    except Exception:  # noqa: BLE001 — never raise from telemetry.
                        continue
            yield current_span
    else:
        yield None


def _coerce_attr(value: Any) -> Any:
    if isinstance(value, str | int | float | bool):
        return value
    return str(value)


class _NoopSpan:
    def set_attribute(self, *_: Any, **__: Any) -> None:
        return None

    def add_event(self, *_: Any, **__: Any) -> None:
        return None

    def __enter__(self) -> _NoopSpan:
        return self

    def __exit__(self, *_: Any) -> None:
        return None


class _NoopTracer:
    @contextmanager
    def start_as_current_span(self, _name: str) -> Iterator[_NoopSpan]:
        yield _NoopSpan()
