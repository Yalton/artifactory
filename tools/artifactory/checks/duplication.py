"""The no_duplication check: duplication.yaml regexes must not match the trial's own code."""
from __future__ import annotations

import io
import re
import tokenize
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
            text = file.read_text(errors="replace")
        except OSError as e:
            if strict:
                raise
            hits.append(f"{rel} unreadable ({type(e).__name__})")
            continue
        if file.suffix == ".py":
            # Split as the tokenizer does (on \n only), so its rows line up with ours.
            lines = _blank_python_prose(text, [ln.rstrip("\r\n") for ln in io.StringIO(text).readlines()])
        else:
            lines = text.splitlines()
        for lineno, line in enumerate(lines, 1):
            for name, regexes in compiled.items():
                for rx in regexes:
                    if rx.search(line):
                        hits.append(f"{rel}:{lineno} matches {name} pattern {rx.pattern!r}")
    if hits:
        more = f" (+{len(hits) - MAX_LISTED} more)" if len(hits) > MAX_LISTED else ""
        return CheckResult("no_duplication", False, "; ".join(hits[:MAX_LISTED]) + more)
    return CheckResult("no_duplication", True, "no duplication patterns in project code")


# f-strings tokenize as FSTRING_START/MIDDLE/END on Python 3.12+; one with a {field} also has
# OP and NAME tokens, so it is never blanked.
_STRING_TOKENS = {tokenize.STRING} | {getattr(tokenize, n) for n in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")
                                      if hasattr(tokenize, n)}


def _blank_python_prose(text: str, lines: list[str]) -> list[str]:
    """Blank comments and bare string statements (docstrings) so prose that merely mentions a pattern
    is not flagged. Line numbers stay stable; a file that does not tokenize is scanned raw."""
    out = list(lines)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return lines

    def blank(tok: tokenize.TokenInfo) -> None:
        (r1, c1), (r2, c2) = tok.start, tok.end
        for r in range(r1, r2 + 1):
            if r > len(out):
                break
            a = c1 if r == r1 else 0
            b = c2 if r == r2 else len(out[r - 1])
            out[r - 1] = out[r - 1][:a] + " " * (b - a) + out[r - 1][b:]

    skip = {tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.COMMENT,
            tokenize.ENDMARKER, tokenize.ENCODING}
    logical: list[tokenize.TokenInfo] = []
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            blank(tok)
        if tok.type == tokenize.NEWLINE or tok.type == tokenize.ENDMARKER:
            if logical and all(t.type in _STRING_TOKENS for t in logical):
                for t in logical:
                    blank(t)
            logical = []
        elif tok.type not in skip:
            logical.append(tok)
    return out
