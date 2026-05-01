"""Best-of-N merger — run multiple subagent attempts and pick the winner.

Scoring is intentionally deterministic so the merger's choice is
reproducible across runs:

    score = 0.5 * length_score + 0.5 * citation_score

- ``length_score``: a saturating function on response length (rewarding
  substantive answers up to ~1.2k chars, penalising one-liners).
- ``citation_score``: saturating function on the number of citations
  (URLs or markdown links). Caps at 5 citations.

Failed attempts get score 0.0 and are kept for audit but excluded from
winner selection. If every attempt fails, ``MergedSubagentResult.status``
becomes ``"failed"`` and ``final_response`` is empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..storage import PostgresAgentStore
from .delegate import SubagentDelegator, SubagentResult


def score_response(text: str, *, citations_count: int) -> float:
    """Deterministic 0..1 score for a subagent response."""

    if not text.strip():
        return 0.0
    length = len(text)
    length_score = min(length, 1200) / 1200.0
    citation_score = min(citations_count, 5) / 5.0
    return round(0.5 * length_score + 0.5 * citation_score, 4)


@dataclass
class MergedSubagentResult:
    winner: SubagentResult | None
    attempts: list[SubagentResult] = field(default_factory=list)
    status: str = "completed"

    @property
    def final_response(self) -> str:
        return self.winner.final_response if self.winner else ""

    @property
    def score(self) -> float:
        return self.winner.score if self.winner else 0.0


class BestOfNMerger:
    def __init__(self, store: PostgresAgentStore, delegator: SubagentDelegator) -> None:
        self.store = store
        self.delegator = delegator

    def run(
        self,
        *,
        task: str,
        role_id: str,
        parent_session_id: str,
        parent_run_id: str,
        n: int = 3,
        reason: str = "",
        agent_id: str = "default",
        approval_id: str = "",
    ) -> MergedSubagentResult:
        if n < 1:
            raise ValueError("n must be >= 1")
        attempts: list[SubagentResult] = []
        for index in range(n):
            attempt = self.delegator.dispatch(
                task=task,
                role_id=role_id,
                parent_session_id=parent_session_id,
                parent_run_id=parent_run_id,
                agent_id=agent_id,
                reason=reason,
                attempt_index=index,
                approval_id=approval_id,
            )
            attempts.append(attempt)
            if attempt.status == "stopped":
                break

        completed = [a for a in attempts if a.status == "completed" and a.final_response]
        if not completed:
            stopped = any(a.status == "stopped" for a in attempts)
            return MergedSubagentResult(
                winner=None,
                attempts=attempts,
                status="stopped" if stopped else "failed",
            )

        winner = max(completed, key=lambda a: (a.score, len(a.final_response)))
        return MergedSubagentResult(winner=winner, attempts=attempts, status="completed")
