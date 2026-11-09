"""Count how a trial's agent used the Artifactory and arc tools, from its opencode transcripts.

Only shell tool commands and MCP tool calls count; file paths, prose and tool output never do.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

# opencode names an MCP tool "<server>_<tool>" (both sanitised); the harness configures the server as "artifactory".
MCP_PREFIX = "artifactory_"
SHELL_TOOLS = {"shell", "bash"}
# opencode's code-mode tool: MCP tools are called from JS as tools.<server>.<tool>(...) (seen in the Nov 8 smoke round).
CODE_TOOL = "execute"
# `go env` with no variable names (or -json) prints GOPROXY; `go env GOROOT` does not.
_GO_ENV_ALL = re.compile(r"\bgo env(?:\s+-json)?\s*(?:$|[;&|)])", re.M)
_CODE_MCP = re.compile(r"\btools\.artifactory\.(\w+)\s*\(")
# A command word: start of a line, or right after && ; | || or $(.
_CMD = re.compile(r"(?:^|&&|;|\||\$\()[ \t]*(artifactory|arc)[ \t]+([A-Za-z][\w-]*)", re.M)


def _calls(transcript: Path):
    """(tool, input) of every tool call in one opencode JSON-lines transcript."""
    for line in Path(transcript).read_text(errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        part = ev.get("part")
        if ev.get("type") != "tool_use" or not isinstance(part, dict):
            continue
        state = part.get("state")
        inp = state.get("input") if isinstance(state, dict) else None
        yield str(part.get("tool", "")), inp if isinstance(inp, dict) else {}


def count_tool_use(transcripts: list[Path], proxy: Path | None) -> dict:
    cli: dict[str, Counter] = {"artifactory": Counter(), "arc": Counter()}
    mcp: Counter = Counter()
    snoop = 0
    for t in transcripts:
        for tool, inp in _calls(t):
            if tool.startswith(MCP_PREFIX):
                mcp[tool[len(MCP_PREFIX):]] += 1
            elif tool == CODE_TOOL and isinstance(inp.get("code"), str):
                for m in _CODE_MCP.finditer(inp["code"]):
                    mcp[m.group(1)] += 1
            elif tool in SHELL_TOOLS and isinstance(inp.get("command"), str):
                cmd = inp["command"]
                for m in _CMD.finditer(cmd):
                    cli[m.group(1)][m.group(2)] += 1
                if "GOPROXY" in cmd or _GO_ENV_ALL.search(cmd) or (proxy is not None and str(proxy) in cmd):
                    snoop += 1
    return {"artifactory": dict(cli["artifactory"]), "mcp": dict(mcp), "arc": dict(cli["arc"]), "proxy_snoop": snoop}
