"""Shared report dataclasses for eval suites."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvalCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class EvalReport:
    suite: str
    checks: list[EvalCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failure_count(self) -> int:
        return sum(1 for check in self.checks if not check.passed)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(EvalCheck(name=name, passed=passed, detail=detail))
