"""Run a subprocess with output to a file and a hard timeout that kills the whole process group."""
from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


@dataclass
class Proc:
    code: int | None  # None on timeout
    output: str
    seconds: float

    @property
    def timed_out(self) -> bool:
        return self.code is None


def run(cmd: list[str], cwd: Path, timeout: float, log: Path, env: dict[str, str] | None = None) -> Proc:
    """Run with output to a file (no pipe for stray children to hold) and kill the whole group on timeout."""
    log.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    with open(log, "wb") as out:
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env, start_new_session=True)
        try:
            code: int | None = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            code = None
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
    text = ANSI.sub("", log.read_bytes().decode("utf-8", errors="replace"))
    return Proc(code, text, time.monotonic() - start)
