"""Hallucination eval — citation analyzer flags missing URLs."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from ...graph.detectors import analyze_citations
from .report import EvalReport


def eval_hallucination(_store: Any | None = None) -> EvalReport:
    report = EvalReport(suite="hallucination")

    tool_msg = ToolMessage(content="results from the web", tool_call_id="t1", name="web_search")
    no_cite = AIMessage(content="The framework was released last Tuesday and is the best ever.")
    cite = AIMessage(content="Released last Tuesday, see https://example.com for details.")

    flagged = analyze_citations([tool_msg, no_cite])
    report.add(
        "missing_citation_flagged",
        passed=flagged.required and not flagged.satisfied,
        detail=f"required={flagged.required}, satisfied={flagged.satisfied}",
    )

    ok = analyze_citations([tool_msg, cite])
    report.add(
        "citation_satisfies_requirement",
        passed=ok.required and ok.satisfied,
        detail=f"required={ok.required}, satisfied={ok.satisfied}",
    )
    return report
