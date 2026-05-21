from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def run_go_shell_command(
    *,
    command: str,
    cwd: Path,
    timeout_seconds: int,
    max_output_chars: int,
) -> str:
    request = {
        "command": command,
        "cwd": str(cwd),
        "shell": os.getenv("SHELL", "/bin/zsh"),
        "timeout_seconds": timeout_seconds,
        "max_output_chars": max_output_chars,
    }
    response = _run_with_http_sidecar(request, timeout_seconds=timeout_seconds)
    if response is None:
        response = _run_with_cli(request, timeout_seconds=timeout_seconds)
    return json.dumps(response, ensure_ascii=False)


def _run_with_http_sidecar(
    request: dict[str, Any],
    *,
    timeout_seconds: int,
) -> dict[str, Any] | None:
    base_url = os.getenv("TOMMY_GO_RUNNER_URL", "").strip().rstrip("/")
    if not base_url:
        return None
    body = json.dumps(request).encode("utf-8")
    http_request = urllib.request.Request(
        f"{base_url}/v1/shell/run",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=timeout_seconds + 5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Go shell runner sidecar unavailable: {exc}") from exc


def _run_with_cli(
    request: dict[str, Any],
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    completed = subprocess.run(
        _runner_command(),
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=timeout_seconds + 10,
        check=False,
        cwd=_runner_workdir(),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Go shell runner failed: "
            f"exit={completed.returncode} stderr={completed.stderr.strip()}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Go shell runner returned invalid JSON: {completed.stdout!r}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Go shell runner returned a non-object payload")
    return payload


def _runner_command() -> list[str]:
    configured = os.getenv("TOMMY_GO_RUNNER_BIN", "").strip()
    if configured:
        return [configured, "exec"]
    built = _repo_root() / "runner" / "bin" / "tommy-runner"
    if built.exists():
        return [str(built), "exec"]
    return ["go", "run", "./cmd/tommy-runner", "exec"]


def _runner_workdir() -> Path:
    return _repo_root() / "runner"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]
