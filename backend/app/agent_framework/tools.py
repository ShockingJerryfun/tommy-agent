from __future__ import annotations

import json
import os
import subprocess
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from .context import merge_context_pact
from .skills import SkillCatalog, SkillProposal
from .store import SQLiteAgentStore

RUNTIME_TOOL_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "runtime_tool_context",
    default=None,
)


class WebSearchArgs(BaseModel):
    query: str = Field(..., min_length=1, description="Search query to run.")
    search_depth: Literal["ultra-fast", "fast", "basic", "advanced"] = Field(
        default="fast",
        description=(
            "Search depth. Use fast by default for relevant snippets at low token/cost; "
            "use advanced only when precision is more important."
        ),
    )
    topic: Literal["general", "news", "finance"] = Field(
        default="general",
        description="Search topic. Use news for fresh news queries and finance for market data.",
    )
    max_results: int = Field(
        default=5,
        ge=1,
        le=8,
        description="Maximum number of results to return. Keep small to save context.",
    )
    chunks_per_source: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Maximum relevant chunks per source for fast/advanced searches.",
    )
    content_max_chars: int = Field(
        default=700,
        ge=160,
        le=1600,
        description="Maximum characters returned per source content snippet.",
    )
    time_range: Literal["day", "week", "month", "year", "d", "w", "m", "y"] | None = Field(
        default=None,
        description="Optional recency filter for freshness-sensitive queries.",
    )
    include_domains: list[str] = Field(
        default_factory=list,
        description="Optional trusted domains to restrict the search to.",
    )
    exclude_domains: list[str] = Field(
        default_factory=list,
        description="Optional domains to exclude from results.",
    )
    exact_match: bool = Field(
        default=False,
        description='Require exact quoted phrases in the query, e.g. "John Smith".',
    )


class ReadWorkspaceFileArgs(BaseModel):
    path: str = Field(..., description="Workspace-relative file path to read.")
    max_chars: int = Field(
        default=8000,
        ge=1,
        le=50000,
        description="Maximum number of characters to return.",
    )


class ListWorkspaceArgs(BaseModel):
    path: str = Field(default=".", description="Workspace-relative directory path to list.")


class ReadLocalFileArgs(BaseModel):
    path: str = Field(
        ...,
        description="Absolute path, ~ path, or path relative to the local file access root.",
    )
    max_chars: int = Field(
        default=20000,
        ge=1,
        le=200000,
        description="Maximum number of characters to return.",
    )


class ListLocalDirectoryArgs(BaseModel):
    path: str = Field(
        default=".",
        description="Absolute path, ~ path, or path relative to the local file access root.",
    )
    max_entries: int = Field(
        default=200,
        ge=1,
        le=1000,
        description="Maximum number of directory entries to return.",
    )


class WriteLocalFileArgs(BaseModel):
    path: str = Field(
        ...,
        description="Absolute path, ~ path, or path relative to the local file access root.",
    )
    content: str = Field(..., description="Text content to write.")
    mode: Literal["overwrite", "append"] = Field(
        default="overwrite",
        description="Whether to overwrite the file or append to it.",
    )
    create_parents: bool = Field(
        default=True,
        description="Create parent directories when they do not exist.",
    )


class RunShellCommandArgs(BaseModel):
    command: str = Field(..., min_length=1, description="Shell command to run after approval.")
    cwd: str = Field(default=".", description="Workspace-relative working directory.")
    timeout_seconds: int = Field(default=20, ge=1, le=120)
    max_output_chars: int = Field(default=12000, ge=1000, le=50000)


class SkillProposeArgs(BaseModel):
    name: str = Field(..., min_length=1, description="Human-readable skill name.")
    action: Literal["create", "update"] = Field(default="create")
    rationale: str = Field(..., min_length=1, description="Why this skill should exist or change.")
    content: str = Field(..., min_length=1, description="Full SKILL.md content to propose.")
    relative_path: str | None = Field(default=None, description="Path relative to skills root.")
    risks: list[str] = Field(default_factory=list)
    allow_auto_apply: bool = Field(
        default=False,
        description="Only true when the user explicitly permits automatic skill writes.",
    )


class ContextPactUpdateArgs(BaseModel):
    summary: str | None = Field(default=None)
    goals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    active_skills: list[str] = Field(default_factory=list)


class DelegateTaskArgs(BaseModel):
    task: str = Field(..., min_length=1)
    target_agent: str = Field(default="researcher")
    reason: str = Field(default="")


@tool
def get_current_time() -> str:
    """Return the current UTC time in ISO-8601 format."""
    return datetime.now(UTC).isoformat()


def _truncate_text(value: Any, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1].rstrip()}…"


def _tavily_search(payload: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("Missing TAVILY_API_KEY. Set it in the backend environment.")

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        "https://api.tavily.com/search",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
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
        if not isinstance(result, dict):
            continue
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


def _frontend_settings() -> dict[str, Any]:
    metadata = _runtime_context().get("metadata")
    if not isinstance(metadata, dict):
        return {}
    settings = metadata.get("frontend_settings")
    return settings if isinstance(settings, dict) else {}


def _configured_local_file_root() -> Path:
    return Path(os.getenv("AGENT_FILE_ACCESS_ROOT", str(Path.home()))).expanduser().resolve()


def _selected_working_directory() -> Path | None:
    raw = str(_frontend_settings().get("workingDirectory") or "").strip()
    if not raw:
        return None

    access_root = _configured_local_file_root()
    candidate = Path(raw).expanduser()
    resolved = (candidate if candidate.is_absolute() else access_root / candidate).resolve()
    if access_root != resolved and access_root not in resolved.parents:
        raise PermissionError(
            f"Working directory escapes local file access root ({access_root}): {raw}"
        )
    if not resolved.is_dir():
        raise NotADirectoryError(f"Working directory is not a directory: {raw}")
    return resolved


def _workspace_root() -> Path:
    return _selected_working_directory() or Path(
        os.getenv("AGENT_WORKSPACE_ROOT", Path.cwd())
    ).resolve()


def _local_file_root() -> Path:
    return _selected_working_directory() or _configured_local_file_root()


def _resolve_workspace_path(path: str) -> Path:
    root = _workspace_root()
    resolved = (root / path).resolve()
    if root != resolved and root not in resolved.parents:
        raise PermissionError(f"Path escapes workspace: {path}")
    return resolved


def _resolve_local_path(path: str) -> Path:
    root = _local_file_root()
    candidate = Path(path).expanduser()
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if root != resolved and root not in resolved.parents:
        raise PermissionError(f"Path escapes local file access root ({root}): {path}")
    return resolved


@tool(args_schema=ReadWorkspaceFileArgs)
def read_workspace_file(path: str, max_chars: int = 8000) -> str:
    """Read a text file from the allowed workspace."""
    resolved = _resolve_workspace_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"Not a file: {path}")
    return resolved.read_text(encoding="utf-8", errors="replace")[:max_chars]


@tool(args_schema=ListWorkspaceArgs)
def list_workspace(path: str = ".") -> str:
    """List files and directories under the allowed workspace."""
    resolved = _resolve_workspace_path(path)
    if not resolved.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")
    entries = []
    children = sorted(
        resolved.iterdir(),
        key=lambda item: (not item.is_dir(), item.name.lower()),
    )
    for child in children:
        entries.append({"name": child.name, "type": "directory" if child.is_dir() else "file"})
    return json.dumps({"path": path, "entries": entries}, ensure_ascii=False)


@tool(args_schema=ReadLocalFileArgs)
def read_local_file(path: str, max_chars: int = 20000) -> str:
    """Read a text file from the local machine under the configured file access root."""
    resolved = _resolve_local_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"Not a file: {path}")
    return resolved.read_text(encoding="utf-8", errors="replace")[:max_chars]


@tool(args_schema=ListLocalDirectoryArgs)
def list_local_directory(path: str = ".", max_entries: int = 200) -> str:
    """List files and directories on the local machine under the configured file access root."""
    resolved = _resolve_local_path(path)
    if not resolved.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")
    entries = []
    children = sorted(
        resolved.iterdir(),
        key=lambda item: (not item.is_dir(), item.name.lower()),
    )
    for child in children[:max_entries]:
        entries.append(
            {
                "name": child.name,
                "path": str(child),
                "type": "directory" if child.is_dir() else "file",
            }
        )
    return json.dumps(
        {"path": str(resolved), "root": str(_local_file_root()), "entries": entries},
        ensure_ascii=False,
    )


@tool(args_schema=WriteLocalFileArgs)
def write_local_file(
    path: str,
    content: str,
    mode: Literal["overwrite", "append"] = "overwrite",
    create_parents: bool = True,
) -> str:
    """Write or append a text file on the local machine under the configured file access root."""
    _require_approval("write_local_file")
    resolved = _resolve_local_path(path)
    if resolved.exists() and resolved.is_dir():
        raise IsADirectoryError(f"Cannot write to directory: {path}")
    if create_parents:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    elif not resolved.parent.exists():
        raise FileNotFoundError(f"Parent directory does not exist: {resolved.parent}")

    if mode == "append":
        with resolved.open("a", encoding="utf-8") as handle:
            handle.write(content)
    else:
        resolved.write_text(content, encoding="utf-8")
    return json.dumps({"path": str(resolved), "mode": mode, "bytes": len(content.encode("utf-8"))})


def _runtime_context() -> dict[str, Any]:
    return dict(RUNTIME_TOOL_CONTEXT.get() or {})


def _require_approval(tool_name: str) -> None:
    if not _runtime_context().get("approval_granted"):
        raise PermissionError(f"{tool_name} requires explicit user approval before execution.")


@tool(args_schema=RunShellCommandArgs)
def run_shell_command(
    command: str,
    cwd: str = ".",
    timeout_seconds: int = 20,
    max_output_chars: int = 12000,
) -> str:
    """Run an approved shell command inside the configured workspace root."""

    _require_approval("run_shell_command")
    from .approvals import assert_command_allowed

    assert_command_allowed(command)
    working_directory = _resolve_workspace_path(cwd)
    if not working_directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {cwd}")
    completed = subprocess.run(
        command,
        shell=True,
        cwd=working_directory,
        executable=os.getenv("SHELL", "/bin/zsh"),
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    stdout = (completed.stdout or "")[:max_output_chars]
    stderr = (completed.stderr or "")[:max_output_chars]
    return json.dumps(
        {
            "command": command,
            "cwd": str(working_directory),
            "exit_code": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
        },
        ensure_ascii=False,
    )


@tool(args_schema=SkillProposeArgs)
def skill_propose(
    name: str,
    action: Literal["create", "update"] = "create",
    rationale: str = "",
    content: str = "",
    relative_path: str | None = None,
    risks: list[str] | None = None,
    allow_auto_apply: bool = False,
) -> str:
    """Create a reviewable skill proposal.

    Auto-apply only when the user explicitly permits it.
    """

    context = _runtime_context()
    agent_id = str(context.get("agent_id") or "default")
    metadata = dict(context.get("metadata") or {})
    auto_apply = bool(allow_auto_apply or metadata.get("allow_auto_apply"))
    catalog = SkillCatalog(agent_id=agent_id)
    result = catalog.create_proposal(
        SkillProposal(
            name=name,
            action=action,
            rationale=rationale,
            content=content,
            relative_path=relative_path,
            risks=risks or [],
            metadata={
                "source": "agent_tool",
                "session_id": context.get("session_id"),
            },
        ),
        allow_auto_apply=auto_apply,
    )
    return json.dumps(result, ensure_ascii=False, default=str)


@tool(args_schema=ContextPactUpdateArgs)
def context_pact_update(
    summary: str | None = None,
    goals: list[str] | None = None,
    constraints: list[str] | None = None,
    facts: list[str] | None = None,
    open_questions: list[str] | None = None,
    active_skills: list[str] | None = None,
) -> str:
    """Merge durable session context into the current context pact."""

    context = _runtime_context()
    session_id = str(context.get("session_id") or "")
    if not session_id:
        raise ValueError("session_id is required for context pact updates.")
    agent_id = str(context.get("agent_id") or "default")
    store = SQLiteAgentStore()
    current = store.get_context_pact(session_id, agent_id=agent_id)
    patch = {
        "summary": summary,
        "goals": goals or [],
        "constraints": constraints or [],
        "facts": facts or [],
        "open_questions": open_questions or [],
        "active_skills": active_skills or [],
    }
    patch = {key: value for key, value in patch.items() if value}
    pact = merge_context_pact(current, patch)
    store.upsert_context_pact(session_id, agent_id=agent_id, pact=pact)
    return json.dumps({"session_id": session_id, "pact": pact}, ensure_ascii=False, default=str)


@tool(args_schema=DelegateTaskArgs)
def delegate_task(task: str, target_agent: str = "researcher", reason: str = "") -> str:
    """Record a bounded delegation request for future multi-agent execution."""

    context = _runtime_context()
    if context.get("approval_granted"):
        session_id = str(context.get("session_id") or "")
        parent_run_id = str((context.get("metadata") or {}).get("run_id") or "")
        if SQLiteAgentStore().run_stop_requested(session_id=session_id, run_id=parent_run_id):
            return json.dumps(
                {
                    "status": "stopped",
                    "target_agent": target_agent,
                    "session_id": session_id,
                    "parent_run_id": parent_run_id,
                    "message": "Delegation was not started because the run was stopped.",
                },
                ensure_ascii=False,
                default=str,
            )
        from .orchestrator import run_delegate_task

        result = run_delegate_task(
            task=task,
            target_agent=target_agent,
            reason=reason,
            session_id=session_id,
            parent_run_id=parent_run_id,
            approval_id=str(context.get("approval_id") or "unrestricted"),
            agent_id=str(context.get("agent_id") or "default"),
        )
        return json.dumps(result, ensure_ascii=False, default=str)

    payload = {
        "status": "queued",
        "target_agent": target_agent,
        "task": task,
        "reason": reason,
        "session_id": context.get("session_id"),
        "note": (
            "Delegation is recorded for orchestration; "
            "the main LangGraph agent remains in control."
        ),
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


@dataclass(frozen=True)
class ToolRegistry:
    tools: tuple[BaseTool, ...]

    @property
    def by_name(self) -> dict[str, BaseTool]:
        return {tool_.name: tool_ for tool_ in self.tools}

    def schemas(self) -> list[BaseTool]:
        return list(self.tools)

    def invoke(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        context: dict[str, Any] | None = None,
    ) -> str:
        tool_ = self.by_name.get(name)
        if tool_ is None:
            raise KeyError(f"Unknown tool: {name}")

        token = RUNTIME_TOOL_CONTEXT.set(context or {})
        try:
            result = tool_.invoke(args or {})
        finally:
            RUNTIME_TOOL_CONTEXT.reset(token)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)


def create_default_registry() -> ToolRegistry:
    return ToolRegistry(
        tools=(
            get_current_time,
            web_search,
            read_workspace_file,
            list_workspace,
            read_local_file,
            list_local_directory,
            write_local_file,
            run_shell_command,
            skill_propose,
            context_pact_update,
            delegate_task,
        )
    )
