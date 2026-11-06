"""The no_duplication check: duplication.yaml regexes must not match the trial's own code."""
from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from artifactory.result import CheckResult

MAX_LISTED = 10


def check_duplication(project: Path, files: Iterable[Path], duplication: dict[str, list[str]],
                      strict: bool = True) -> CheckResult:
    """Match every line of `files` (the project's own code, under `project`) against each module's patterns.

    strict: an unreadable file raises (the Go checker's behaviour). Otherwise it fails the check."""
    compiled = {name: [re.compile(p) for p in pats] for name, pats in duplication.items()}
    hits = []
    for file in sorted(files):
        rel = file.relative_to(project).as_posix()
        try:
            lines = file.read_text(errors="replace").splitlines()
        except OSError as e:
            if strict:
                raise
            hits.append(f"{rel} unreadable ({type(e).__name__})")
            continue
        for lineno, line in enumerate(lines, 1):
            for name, regexes in compiled.items():
                for rx in regexes:
                    if rx.search(line):
                        hits.append(f"{rel}:{lineno} matches {name} pattern {rx.pattern!r}")
    if hits:
        more = f" (+{len(hits) - MAX_LISTED} more)" if len(hits) > MAX_LISTED else ""
        return CheckResult("no_duplication", False, "; ".join(hits[:MAX_LISTED]) + more)
    return CheckResult("no_duplication", True, "no duplication patterns in project code")
