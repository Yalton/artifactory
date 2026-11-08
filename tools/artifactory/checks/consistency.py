"""Layout-agnostic consistency checks on a Go project (all informational, never gating).

Each check reads the project's own non-test .go files (outside vendor/ and dot-directories) and
returns one CheckResult. A package is a directory, relative to the project ("." for the root).
A kit call (config.Load, kvstore.Open) counts as the one place, like a direct call, but only in a
file that imports the kit, under the name it imports it as. Generated files are skipped.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

from artifactory.result import CheckResult

KIT_PREFIX = "repo.billbert.co/artifactory"
ENV_CALLS = re.compile(r"\bos\.(Getenv|LookupEnv|Environ)\(")
FILE_CALLS = re.compile(r"\bos\.(Open|OpenFile|ReadFile|WriteFile|Create)\(")
# Handler definitions only (an anonymous handler, or any func with the handler signature), not
# route registration: wiring next to the routes is normal in every condition.
HANDLER_DEFS = re.compile(r"\bfunc\s*\(\s*\w+\s+http\.ResponseWriter"
                          r"|\(\s*\w+\s+http\.ResponseWriter\s*,\s*\w+\s+\*http\.Request\s*\)")
GENERATED = re.compile(r"^// Code generated .* DO NOT EDIT\.$", re.M)
IMPORT_BLOCK = re.compile(r"\bimport\s*\(([^)]*)\)", re.S)
IMPORT_ONE = re.compile(r"\bimport\s+([\w.]+\s+)?(\"[^\"]*\"|`[^`]*`)")
IMPORT_SPEC = re.compile(r"(?:^|;)\s*([\w.]+\s+)?(\"[^\"]*\"|`[^`]*`)", re.M)
MIN_BODY_LINES = 3
MAX_LISTED = 10
FUNCS_TIMEOUT_S = 120


def check_consistency(project: Path, env: dict[str, str] | None = None) -> list[CheckResult]:
    project = Path(project)
    return [config_one_place(project), storage_one_place(project), handlers_no_file_io(project),
            no_duplicate_funcs(project, env)]


def go_files(project: Path) -> list[Path]:
    """The project's own non-test, non-generated .go files, sorted."""
    out = []
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = [d for d in dirnames if d != "vendor" and not d.startswith(".")]
        out += [Path(dirpath) / f for f in filenames if f.endswith(".go") and not f.endswith("_test.go")]
    return sorted(f for f in out if not is_generated(f))


def is_generated(path: Path) -> bool:
    """Go's convention: a `// Code generated ... DO NOT EDIT.` line before the package clause."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return False
    m = re.search(r"^package\s", text, re.M)
    return bool(GENERATED.search(text[:m.start()] if m else text))


def import_names(src: str) -> dict[str, str]:
    """Import path -> the name the (comment-stripped) file uses for it. The default name is the last
    path element without a /vN suffix; `_` and `.` imports are kept as given."""
    specs = [m.groups() for block in IMPORT_BLOCK.findall(src) for m in IMPORT_SPEC.finditer(block)]
    specs += [m.groups() for m in IMPORT_ONE.finditer(src)]
    out = {}
    for alias, quoted in specs:
        path = quoted[1:-1]
        parts = path.split("/")
        default = parts[-2] if len(parts) > 1 and re.fullmatch(r"v\d+", parts[-1]) else parts[-1]
        out[path] = alias.strip() if alias else default
    return out


def _kit_call(src: str, kit: str, func: str) -> bool:
    """Whether the file calls `func` of the Artifactory kit `kit` under its imported name."""
    name = import_names(src).get(f"{KIT_PREFIX}/{kit}")
    if name is None or name == "_":
        return False
    rx = rf"(?<![\w.]){re.escape(func)}\(" if name == "." else rf"\b{re.escape(name)}\.{re.escape(func)}\("
    return re.search(rx, src) is not None


def reads_env(src: str) -> bool:
    return bool(ENV_CALLS.search(src)) or _kit_call(src, "config", "Load")


def does_file_io(src: str) -> bool:
    return bool(FILE_CALLS.search(src)) or _kit_call(src, "kvstore", "Open")


def strip_comments(src: str) -> str:
    """`src` with Go comments blanked (newlines kept); string, raw-string and rune literals left alone."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", src[i:j]))
            i = j
        elif c in "\"'`":
            j = i + 1
            while j < n and src[j] != c and not (c != "`" and src[j] == "\n"):
                j += 2 if c != "`" and src[j] == "\\" else 1
            out.append(src[i:j + 1])
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _sources(project: Path) -> list[tuple[str, str]]:
    """(relative path, comment-stripped source) per Go file."""
    out = []
    for f in go_files(project):
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        out.append((f.relative_to(project).as_posix(), strip_comments(text)))
    return out


def _pkg(rel: str) -> str:
    return rel.rsplit("/", 1)[0] if "/" in rel else "."


def _listed(items: list[str]) -> str:
    more = f" (+{len(items) - MAX_LISTED} more)" if len(items) > MAX_LISTED else ""
    return ", ".join(items[:MAX_LISTED]) + more


def _one_place(project: Path, name: str, hit, what: str) -> CheckResult:
    pkgs = sorted({_pkg(rel) for rel, src in _sources(project) if hit(src)})
    detail = f"{what} in {len(pkgs)} package(s)" + (f": {_listed(pkgs)}" if pkgs else "")
    return CheckResult(name, len(pkgs) <= 1, detail, gating=False)


def config_one_place(project: Path) -> CheckResult:
    """Environment variables are read in at most one package (os.Getenv/LookupEnv/Environ, config.Load)."""
    return _one_place(project, "config_one_place", reads_env, "environment read")


def storage_one_place(project: Path) -> CheckResult:
    """Files are opened or written in at most one package (os file calls, kvstore.Open)."""
    return _one_place(project, "storage_one_place", does_file_io, "file I/O")


def handlers_no_file_io(project: Path) -> CheckResult:
    """No file that defines an HTTP handler also makes a raw file call (os.Open, os.ReadFile, ...).
    Kit constructors (kvstore.Open) do not count: opening the store beside the routes is wiring."""
    bad = [rel for rel, src in _sources(project) if HANDLER_DEFS.search(src) and FILE_CALLS.search(src)]
    if bad:
        return CheckResult("handlers_no_file_io", False, f"handler files with file I/O: {_listed(bad)}", gating=False)
    return CheckResult("handlers_no_file_io", True, "no handler file does file I/O", gating=False)


# Lists every function and method body of the files named on stdin, as JSON lines. Files that do
# not parse contribute what the parser recovered. Stdlib only, built from a temp module.
_FUNCS_GO = r'''package main

import (
	"bufio"
	"encoding/json"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
)

func main() {
	enc := json.NewEncoder(os.Stdout)
	in := bufio.NewScanner(os.Stdin)
	in.Buffer(make([]byte, 1<<20), 1<<20)
	for in.Scan() {
		path := in.Text()
		src, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		fset := token.NewFileSet()
		f, _ := parser.ParseFile(fset, path, src, parser.SkipObjectResolution)
		if f == nil {
			continue
		}
		for _, d := range f.Decls {
			fd, ok := d.(*ast.FuncDecl)
			if !ok || fd.Body == nil {
				continue
			}
			a, b := fset.Position(fd.Body.Lbrace), fset.Position(fd.Body.Rbrace)
			if !a.IsValid() || !b.IsValid() || b.Offset < a.Offset || b.Offset >= len(src) {
				continue
			}
			enc.Encode(map[string]any{"file": path, "name": fd.Name.Name, "line": fset.Position(fd.Pos()).Line,
				"body": string(src[a.Offset : b.Offset+1])})
		}
	}
}
'''


def _func_bodies(project: Path, files: list[Path], env: dict[str, str] | None) -> list[dict]:
    env = dict(env if env is not None else os.environ)
    env.update({"GOWORK": "off", "GOFLAGS": "-mod=mod", "GOTOOLCHAIN": "local"})
    with tempfile.TemporaryDirectory(prefix="artifactory-funcs-") as tmp:
        (Path(tmp) / "go.mod").write_text("module funcs\n\ngo 1.21\n")
        (Path(tmp) / "main.go").write_text(_FUNCS_GO)
        r = subprocess.run(["go", "run", "."], cwd=tmp, env=env, input="\n".join(map(str, files)) + "\n",
                           capture_output=True, text=True, timeout=FUNCS_TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError(f"function lister failed: {r.stderr.strip()[-300:]}")
    return [json.loads(line) for line in r.stdout.splitlines() if line.strip()]


def _normalize(body: str) -> str:
    return "\n".join(" ".join(line.split()) for line in body.splitlines() if line.strip())


def no_duplicate_funcs(project: Path, env: dict[str, str] | None = None) -> CheckResult:
    """No two function bodies of at least MIN_BODY_LINES lines are identical after whitespace normalization."""
    project = Path(project)
    files = go_files(project)
    if not files:
        return CheckResult("no_duplicate_funcs", True, "no Go files", gating=False)
    try:
        funcs = _func_bodies(project, files, env)
    except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError) as e:
        return CheckResult("no_duplicate_funcs", False, f"not run: {type(e).__name__}: {e}", gating=False)
    groups: dict[str, list[str]] = defaultdict(list)
    for fn in funcs:
        body = _normalize(fn["body"])
        if len(body.splitlines()) < MIN_BODY_LINES:  # counted after normalization, blank lines dropped
            continue
        rel = Path(fn["file"]).relative_to(project).as_posix()
        groups[body].append(f"{rel}:{fn['line']} {fn['name']}")
    dups = [" = ".join(sorted(locs)) for locs in groups.values() if len(locs) > 1]
    if dups:
        return CheckResult("no_duplicate_funcs", False, f"{len(dups)} duplicated body(ies): " + "; ".join(dups[:MAX_LISTED]),
                           gating=False)
    return CheckResult("no_duplicate_funcs", True, f"no duplicated function bodies in {len(funcs)} function(s)",
                       gating=False)
