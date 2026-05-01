from __future__ import annotations

import json
import os
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from langchain_core.tools import tool
from pydantic import BaseModel, Field


class WebSearchArgs(BaseModel):
    query: str = Field(..., min_length=1, description="Search query to run.")
    search_depth: Literal["ultra-fast", "fast", "basic", "advanced"] = Field(
        default="fast",
        description=(
            "Search depth. Use fast by default for relevant snippets at low token/cost; "
            "use advanced only when precision is more important."
        ),
    )
    topic: Literal["general", "news", "finance"] = Field(default="general")
    max_results: int = Field(default=5, ge=1, le=8)
    chunks_per_source: int = Field(default=2, ge=1, le=5)
    content_max_chars: int = Field(default=700, ge=160, le=1600)
    time_range: Literal["day", "week", "month", "year", "d", "w", "m", "y"] | None = None
    include_domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)
    exact_match: bool = False


def _truncate_text(value: Any, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1].rstrip()}..."


def _tavily_search(payload: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("Missing TAVILY_API_KEY. Set it in the backend environment.")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        "https://api.tavily.com/search",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed HTTPS endpoint.
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"Tavily search failed ({exc.code}): {details}") from exc
    except URLError as exc:
        raise RuntimeError(f"Tavily search request failed: {exc.reason}") from exc


@tool(args_schema=WebSearchArgs)
def web_search(
    query: str,
    search_depth: Literal["ultra-fast", "fast", "basic", "advanced"] = "fast",
    topic: Literal["general", "news", "finance"] = "general",
    max_results: int = 5,
    chunks_per_source: int = 2,
    content_max_chars: int = 700,
    time_range: Literal["day", "week", "month", "year", "d", "w", "m", "y"] | None = None,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    exact_match: bool = False,
) -> str:
    """Search the live web with Tavily and return compact, cited snippets for the LLM."""
    payload: dict[str, Any] = {
        "query": query.strip(),
        "auto_parameters": False,
        "topic": topic,
        "search_depth": search_depth,
        "chunks_per_source": chunks_per_source,
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
        "include_image_descriptions": False,
        "include_favicon": False,
        "include_usage": False,
        "exact_match": exact_match,
    }
    if time_range:
        payload["time_range"] = time_range
    if include_domains:
        payload["include_domains"] = include_domains[:20]
    if exclude_domains:
        payload["exclude_domains"] = exclude_domains[:20]

    response = _tavily_search(payload)
    compact_results = []
    for result in response.get("results", [])[:max_results]:
        if isinstance(result, dict):
            compact_results.append(
                {
                    "title": _truncate_text(result.get("title"), 140),
                    "url": result.get("url"),
                    "content": _truncate_text(result.get("content"), content_max_chars),
                    "score": result.get("score"),
                    "published_date": result.get("published_date"),
                }
            )
    return json.dumps(
        {
            "query": response.get("query", query),
            "search_depth": search_depth,
            "results": compact_results,
            "response_time": response.get("response_time"),
            "request_id": response.get("request_id"),
        },
        ensure_ascii=False,
    )
