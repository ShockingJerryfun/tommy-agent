"""Worker runner protocol types."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from .types import WorkerResult, WorkerTask

WorkerRunner = Callable[[WorkerTask], WorkerResult | Awaitable[WorkerResult]]
