from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from .context import require_approval, runtime_context


class ReadWorkspaceFileArgs(BaseModel):
    path: str = Field(..., description="Workspace-relative file path to read.")
    max_chars: int = Field(default=8000, ge=1, le=50000)


class ListWorkspaceArgs(BaseModel):
    path: str = Field(default=".", description="Workspace-relative directory path to list.")


class ReadLocalFileArgs(BaseModel):
    path: str = Field(..., description="Absolute, ~, or local-root-relative path.")
    max_chars: int = Field(default=20000, ge=1, le=200000)


class ListLocalDirectoryArgs(BaseModel):
    path: str = Field(default=".", description="Absolute, ~, or local-root-relative path.")
    max_entries: int = Field(default=200, ge=1, le=1000)


class WriteLocalFileArgs(BaseModel):
    path: str = Field(..., description="Absolute, ~, or local-root-relative path.")
    content: str
    mode: Literal["overwrite", "append"] = "overwrite"
    create_parents: bool = True


class RunShellCommandArgs(BaseModel):
    command: str = Field(..., min_length=1, description="Shell command to run after approval.")
    cwd: str = Field(default=".", description="Workspace-relative working directory.")
    timeout_seconds: int = Field(default=20, ge=1, le=120)
    max_output_chars: int = Field(default=12000, ge=1000, le=50000)


def _frontend_settings() -> dict[str, Any]:
    metadata = runtime_context().get("metadata")
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
    return (
        _selected_working_directory()
        or Path(os.getenv("AGENT_WORKSPACE_ROOT", Path.cwd())).resolve()
    )


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
    entries = [
        {"name": child.name, "type": "directory" if child.is_dir() else "file"}
        for child in sorted(
            resolved.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())
        )
    ]
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
    entries = [
        {"name": child.name, "path": str(child), "type": "directory" if child.is_dir() else "file"}
        for child in sorted(
            resolved.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())
        )[:max_entries]
    ]
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
    require_approval("write_local_file")
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


@tool(args_schema=RunShellCommandArgs)
def run_shell_command(
    command: str,
    cwd: str = ".",
    timeout_seconds: int = 20,
    max_output_chars: int = 12000,
) -> str:
    """Run an approved shell command inside the configured workspace root."""
    require_approval("run_shell_command")
    from ..tool_runtime.approvals import assert_command_allowed

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
    return json.dumps(
        {
            "command": command,
            "cwd": str(working_directory),
            "exit_code": completed.returncode,
            "stdout": (completed.stdout or "")[:max_output_chars],
            "stderr": (completed.stderr or "")[:max_output_chars],
        },
        ensure_ascii=False,
    )
