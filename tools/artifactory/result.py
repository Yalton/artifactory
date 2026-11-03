"""Ecosystem-neutral results of grading one acceptance-test trial."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str
    # False for informational checks (e.g. arc_gate): reported, never decide `passed`.
    gating: bool = True


@dataclass
class TrialResult:
    test: str
    trial: str
    checks: list[CheckResult] = field(default_factory=list)
    # Set by the harness (e.g. "timeout"), never by a checker.
    reason: str | None = None
    # Arc mode only: how many writes arc denied (set by the harness from the transcript).
    arc_denials: int | None = None
    # Arc mode only: True when arc's hook left session state in the trial project, so it ran at
    # least once under the agent. False makes `arc_denials: 0` meaningless. Informational.
    arc_hook_live: bool | None = None

    @property
    def passed(self) -> bool:
        return self.reason is None and all(c.passed for c in self.checks if c.gating)

    def to_json(self) -> str:
        return json.dumps(
            {
                "test": self.test,
                "trial": self.trial,
                "passed": self.passed,
                "reason": self.reason,
                "arc_denials": self.arc_denials,
                "arc_hook_live": self.arc_hook_live,
                "checks": [{k: v for k, v in asdict(c).items() if k != "gating" or not v} for c in self.checks],
            },
            indent=2,
        )
