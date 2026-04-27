from __future__ import annotations


class RunStopped(RuntimeError):
    """Raised when a run has been explicitly stopped by the user."""
