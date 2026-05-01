from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .types import RunCreatePayload

CODING_KEYWORDS = (
    "code",
    "coding",
    "repo",
    "file",
    "modify",
    "edit",
    "implement",
    "fix",
    "test",
    "build",
    "lint",
    "typecheck",
    "python",
    "pytest",
    "ruff",
    "npm",
    "next",
    "typescript",
    "javascript",
    "修改",
    "代码",
    "文件",
    "测试",
    "构建",
    "修复",
    "实现",
)


@dataclass(frozen=True)
class VerificationCommand:
    command: tuple[str, ...]
    cwd: Path

    @property
    def display(self) -> str:
        return " ".join(self.command)


@dataclass(frozen=True)
class VerificationAttempt:
    attempt: int
    command: str
    status: str
    exit_code: int | None = None
    output: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "command": self.command,
            "status": self.status,
            "exit_code": self.exit_code,
            "output": self.output,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class VerificationSummary:
    status: str
    attempts: list[VerificationAttempt] = field(default_factory=list)
    max_attempts: int = 1
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "attempts": [attempt.as_dict() for attempt in self.attempts],
            "attempt_count": len({attempt.attempt for attempt in self.attempts}),
            "max_attempts": self.max_attempts,
            "summary": self.summary,
        }


CommandRunner = Callable[[VerificationCommand, int], VerificationAttempt]


class TaskVerifier:
    def __init__(
        self,
        *,
        command_runner: CommandRunner | None = None,
        timeout_seconds: int = 60,
        max_output_chars: int = 4000,
    ) -> None:
        self._command_runner = command_runner or self._run_command
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars

    def should_verify(self, payload: RunCreatePayload, *, changed_files_seen: bool = False) -> bool:
        if payload.metadata.get("verification") is False:
            return False
        if changed_files_seen:
            return True
        task_type = str(payload.metadata.get("task_type") or "").casefold()
        if task_type in {"coding", "repo", "code", "build", "test"}:
            return True
        text = " ".join(
            [
                payload.message,
                json.dumps(payload.metadata, ensure_ascii=False, default=str),
            ]
        ).casefold()
        return any(keyword in text for keyword in CODING_KEYWORDS)

    async def verify(
        self,
        *,
        payload: RunCreatePayload,
        run_id: str,
        max_attempts: int,
    ) -> VerificationSummary:
        del run_id
        attempts_limit = max(1, int(max_attempts))
        commands = self._select_commands(payload)
        if not commands:
            return VerificationSummary(
                status="skipped",
                max_attempts=attempts_limit,
                summary="未找到可用的 Python/Node verifier 命令，已跳过验证。",
            )

        attempts: list[VerificationAttempt] = []
        final_status = "skipped"
        for attempt_index in range(1, attempts_limit + 1):
            current = [
                self._command_runner(command, attempt_index)
                for command in commands
            ]
            attempts.extend(current)
            if any(item.status == "failed" for item in current):
                final_status = "failed"
                continue
            if any(item.status == "passed" for item in current):
                final_status = "passed"
                break
            final_status = "skipped"
            break

        return VerificationSummary(
            status=final_status,
            attempts=attempts,
            max_attempts=attempts_limit,
            summary=self._summarize(final_status, attempts, attempts_limit),
        )

    def _select_commands(self, payload: RunCreatePayload) -> list[VerificationCommand]:
        cwd = self._resolve_working_directory(payload)
        commands: list[VerificationCommand] = []
        for project_root in self._candidate_project_roots(cwd):
            if self._is_python_project(project_root):
                commands.extend(self._python_commands(project_root))
            if (project_root / "package.json").is_file():
                commands.extend(self._node_commands(project_root))
        return commands

    def _resolve_working_directory(self, payload: RunCreatePayload) -> Path:
        settings = payload.metadata.get("frontend_settings")
        raw = settings.get("workingDirectory") if isinstance(settings, dict) else None
        if isinstance(raw, str) and raw.strip():
            candidate = Path(raw).expanduser()
            if candidate.is_dir():
                return candidate.resolve()
        return Path(os.getenv("AGENT_WORKSPACE_ROOT", Path.cwd())).expanduser().resolve()

    def _candidate_project_roots(self, cwd: Path) -> list[Path]:
        roots: list[Path] = []
        for candidate in (cwd, cwd / "backend", cwd / "frontend"):
            if candidate.is_dir() and candidate not in roots:
                roots.append(candidate)
        return roots

    def _is_python_project(self, root: Path) -> bool:
        return any(
            (root / name).exists()
            for name in ("pyproject.toml", "pytest.ini", "setup.cfg", "setup.py", "tests")
        )

    def _python_commands(self, root: Path) -> list[VerificationCommand]:
        commands = [VerificationCommand((sys.executable, "-m", "pytest", "-q"), root)]
        if (root / "pyproject.toml").exists() or (root / "ruff.toml").exists():
            commands.append(VerificationCommand((sys.executable, "-m", "ruff", "check", "."), root))
        return commands

    def _node_commands(self, root: Path) -> list[VerificationCommand]:
        npm = shutil.which("npm")
        if npm is None:
            return [
                VerificationCommand(("npm", "run", "lint"), root),
            ]
        scripts = self._package_scripts(root)
        commands: list[VerificationCommand] = []
        for script in ("typecheck", "lint", "build"):
            if script in scripts:
                commands.append(VerificationCommand((npm, "run", script), root))
        return commands

    def _package_scripts(self, root: Path) -> set[str]:
        try:
            package = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        scripts = package.get("scripts") if isinstance(package, dict) else None
        return set(scripts) if isinstance(scripts, dict) else set()

    def _run_command(self, command: VerificationCommand, attempt: int) -> VerificationAttempt:
        if command.command[0] == "npm" and shutil.which("npm") is None:
            return VerificationAttempt(
                attempt=attempt,
                command=command.display,
                status="skipped",
                reason="npm executable not found",
            )
        try:
            completed = subprocess.run(
                command.command,
                cwd=command.cwd,
                text=True,
                capture_output=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            return VerificationAttempt(
                attempt=attempt,
                command=command.display,
                status="skipped",
                reason=str(exc),
            )
        except subprocess.TimeoutExpired as exc:
            return VerificationAttempt(
                attempt=attempt,
                command=command.display,
                status="failed",
                reason=f"Timed out after {self._timeout_seconds}s",
                output=str(exc)[: self._max_output_chars],
            )
        output = ((completed.stdout or "") + (completed.stderr or ""))[: self._max_output_chars]
        if self._looks_like_missing_dependency(output):
            return VerificationAttempt(
                attempt=attempt,
                command=command.display,
                status="skipped",
                exit_code=completed.returncode,
                output=output,
                reason="Verifier dependency or script is unavailable.",
            )
        return VerificationAttempt(
            attempt=attempt,
            command=command.display,
            status="passed" if completed.returncode == 0 else "failed",
            exit_code=completed.returncode,
            output=output,
        )

    def _looks_like_missing_dependency(self, output: str) -> bool:
        lowered = output.casefold()
        return any(
            marker in lowered
            for marker in (
                "no module named pytest",
                "no module named ruff",
                "missing script:",
                "command not found",
            )
        )

    def _summarize(
        self,
        status: str,
        attempts: list[VerificationAttempt],
        max_attempts: int,
    ) -> str:
        if not attempts:
            return "未执行验证命令。"
        failed = [attempt.command for attempt in attempts if attempt.status == "failed"]
        skipped = [attempt.command for attempt in attempts if attempt.status == "skipped"]
        if status == "passed":
            return f"验证通过：执行了 {len(attempts)} 个 verifier 命令。"
        if status == "failed":
            return (
                f"验证失败：{', '.join(sorted(set(failed))) or 'unknown'}；"
                f"已达到最多 {max_attempts} 次尝试。"
            )
        return f"验证跳过：{', '.join(sorted(set(skipped))) or '没有可用 verifier'}。"
