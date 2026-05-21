from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from .types import ResolvedSkill, SkillResolution


class SkillResolver:
    def __init__(
        self,
        *,
        catalog_rows: Iterable[dict[str, Any]] | None = None,
        activator: Any | None = None,
        available_tools: Iterable[str] | None = None,
    ) -> None:
        self._catalog_rows = list(catalog_rows or [])
        self._activator = activator
        self._available_tools = None if available_tools is None else set(available_tools)

    def resolve(
        self,
        query: str,
        *,
        agent_id: str = "default",
        catalog_rows: Iterable[dict[str, Any]] | None = None,
        max_skills: int = 3,
        min_score: float = 1.0,
    ) -> SkillResolution:
        rows_by_path: dict[str, dict[str, Any]] = {}
        semantic_scores: dict[str, float] = {}

        for row in catalog_rows if catalog_rows is not None else self._catalog_rows:
            normalized = _row_payload(row)
            if normalized.get("relative_path"):
                rows_by_path[str(normalized["relative_path"])] = normalized

        for row in self._recall(agent_id=agent_id, query=query, k=max_skills):
            normalized = _row_payload(row)
            relative_path = str(normalized.get("relative_path") or "")
            if not relative_path:
                continue
            rows_by_path.setdefault(relative_path, normalized)
            semantic_scores[relative_path] = max(
                semantic_scores.get(relative_path, 0.0),
                float(normalized.get("similarity") or 0.0),
            )

        diagnostics: list[dict[str, str]] = []
        candidates: list[ResolvedSkill] = []
        for row in rows_by_path.values():
            status = str(row.get("status") or "active")
            if status == "retired":
                continue

            relative_path = str(row.get("relative_path") or "")
            required_tools = _required_tools(row)
            missing_tools = (
                []
                if self._available_tools is None
                else [tool for tool in required_tools if tool not in self._available_tools]
            )
            row_diagnostics: list[dict[str, str]] = []
            if missing_tools:
                diagnostic = {
                    "path": relative_path,
                    "severity": "warning",
                    "message": f"missing required tools: {', '.join(missing_tools)}",
                }
                diagnostics.append(diagnostic)
                row_diagnostics.append(diagnostic)

            score, reason_codes = _score_row(
                row,
                query=query,
                semantic_score=semantic_scores.get(relative_path, 0.0),
            )
            if score < min_score or not _has_relevance_reason(reason_codes):
                continue

            candidates.append(
                ResolvedSkill(
                    name=str(row.get("name") or relative_path),
                    relative_path=relative_path,
                    description=str(row.get("description") or ""),
                    score=score,
                    status=status,
                    required_tools=tuple(required_tools),
                    reason_codes=tuple(reason_codes),
                    diagnostics=tuple(row_diagnostics),
                    row=dict(row),
                )
            )

        selected = sorted(
            candidates,
            key=lambda skill: (-skill.score, skill.name.lower(), skill.relative_path),
        )[: max(1, min(3, int(max_skills)))]
        selected_paths = {skill.relative_path for skill in selected}
        selected_diagnostics = [
            diagnostic for diagnostic in diagnostics if diagnostic["path"] in selected_paths
        ]
        return SkillResolution(selected=selected, diagnostics=selected_diagnostics)

    def _recall(self, *, agent_id: str, query: str, k: int) -> list[Any]:
        if self._activator is None:
            return []
        try:
            return list(
                self._activator.recall(
                    agent_id=agent_id,
                    query=query,
                    k=max(3, int(k)),
                    statuses=("active",),
                )
            )
        except TypeError:
            return list(self._activator.recall(query=query))


def _row_payload(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "to_payload"):
        return dict(row.to_payload())
    return dict(getattr(row, "__dict__", {}))


def _score_row(
    row: dict[str, Any],
    *,
    query: str,
    semantic_score: float,
) -> tuple[float, list[str]]:
    query_lower = query.lower()
    tokens = set(_tokens(query))
    name = str(row.get("name") or "")
    relative_path = str(row.get("relative_path") or "")
    description = str(row.get("description") or "")
    metadata = _normalized_metadata(row)
    score = 0.0
    reason_codes: list[str] = []

    if name and name.lower() in query_lower:
        score += 100.0
        reason_codes.append("explicit_mention")
    if relative_path and relative_path.lower() in query_lower:
        score += 120.0
        reason_codes.append("explicit_path")

    for trigger in _string_list(metadata.get("triggers")):
        trigger_lower = trigger.lower()
        trigger_tokens = set(_tokens(trigger))
        if trigger_lower and trigger_lower in query_lower:
            score += 25.0
            reason_codes.append("trigger_match")
        elif trigger_tokens:
            overlap = len(tokens & trigger_tokens)
            if overlap:
                score += 8.0 * overlap / len(trigger_tokens)
                reason_codes.append("trigger_token_match")

    for domain in _string_list(metadata.get("domains")):
        if domain.lower() in query_lower:
            score += 10.0
            reason_codes.append("domain_match")

    keyword_overlap = len(tokens & set(_tokens(f"{name} {description}")))
    if keyword_overlap:
        score += 2.0 * keyword_overlap
        reason_codes.append("keyword_match")
    if semantic_score > 0:
        score += 20.0 * max(0.0, semantic_score)
        reason_codes.append("semantic_match")
    metrics_adjustment = _metrics_adjustment(row)
    if metrics_adjustment:
        score += metrics_adjustment
        reason_codes.append("historical_metrics")
    return round(score, 6), list(dict.fromkeys(reason_codes))


def _required_tools(row: dict[str, Any]) -> list[str]:
    tool_chain = _string_list(row.get("tool_chain"))
    metadata_tools = _string_list(_normalized_metadata(row).get("required_tools"))
    return list(dict.fromkeys([*tool_chain, *metadata_tools]))


def _normalized_metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    normalized = metadata.get("normalized")
    if isinstance(normalized, dict):
        return normalized
    return metadata


def _metrics_adjustment(row: dict[str, Any]) -> float:
    metrics = row.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    success_rate = _float_value(metrics.get("success_rate"))
    failure_count = _float_value(metrics.get("failure_count", row.get("failure_count")))
    adjustment = 0.0
    if success_rate is not None:
        adjustment += (success_rate - 0.5) * 2.0
    if failure_count is not None:
        adjustment -= min(3.0, failure_count * 0.25)
    return adjustment


def _has_relevance_reason(reason_codes: list[str]) -> bool:
    return any(reason != "historical_metrics" for reason in reason_codes)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", value.lower())


def _float_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
