"""Deterministic eval suites.

Each suite is a small function that takes ``(store, **kwargs)`` and
returns an :class:`EvalReport`. Suites are intentionally cheap and
hermetic: they use the existing storage, the permission policy, and
deterministic synthetic inputs. No suite calls a real LLM.

Suites:

- :func:`eval_tool_safety` — verifies the permission policy denies
  dangerous shell commands and that risky tools require approval.
- :func:`eval_recall` — seeds memories, embeds them, and asserts that
  hybrid retrieval returns the seeded item for a paraphrased query.
- :func:`eval_compaction` — confirms the pre-compaction memory flush
  hook proposes a memory for "remember that …" user statements.
- :func:`eval_loop` — feeds a synthetic transcript with repeated tool
  calls to the loop detector and asserts the signal fires.
- :func:`eval_hallucination` — checks the citation analyzer flags a
  response that uses ``web_search`` results without citations.
"""

from __future__ import annotations

from .compaction import eval_compaction
from .hallucination import eval_hallucination
from .loop import eval_loop
from .recall import eval_recall
from .report import EvalCheck, EvalReport
from .tool_safety import eval_tool_safety

__all__ = [
    "EvalCheck",
    "EvalReport",
    "eval_compaction",
    "eval_hallucination",
    "eval_loop",
    "eval_recall",
    "eval_tool_safety",
]
