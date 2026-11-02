"""Ecosystem-neutral results of grading one acceptance-test trial."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


@dataclass
class TrialResult:
    test: str
    trial: str
    checks: list[CheckResult] = field(default_factory=list)
    # Set by the harness (e.g. "timeout"), never by a checker.
    reason: str | None = None
    # Times the harness resumed the agent after a dropped model connection.
    resumes: int = 0

    @property
    def passed(self) -> bool:
        return self.reason is None and all(c.passed for c in self.checks)

    def to_json(self) -> str:
        return json.dumps(
            {
                "test": self.test,
                "trial": self.trial,
                "passed": self.passed,
                "reason": self.reason,
                "resumes": self.resumes,
                "checks": [asdict(c) for c in self.checks],
            },
            indent=2,
        )
