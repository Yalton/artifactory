"""Build a file-based GOPROXY tree from Go module directories.

Layout per module and version, under <out>/<module path>/@v/:
list, v<version>.info, v<version>.mod, v<version>.zip. Zips follow the
golang.org/x/mod/zip rules: every path is prefixed `<module>@<version>/`,
go.mod is included, vendor/ and nested modules are left out.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import yaml

ZIP_TIME = (2026, 1, 1, 0, 0, 0)
INFO_TIME = "2026-01-01T00:00:00Z"
SKIP_DIRS = {".git", "vendor"}
MODULE_LINE = re.compile(r"^module\s+(\S+)", re.M)


def build_goproxy(module_dirs: list[Path], out: Path) -> None:
    out = Path(out)
    for d in module_dirs:
        d = Path(d)
        gomod = (d / "go.mod").read_text()
        match = MODULE_LINE.search(gomod)
        if not match:
            raise ValueError(f"{d}/go.mod has no module line")
        module = match.group(1)
        version = "v" + str(yaml.safe_load((d / "module.yaml").read_text())["version"]).lstrip("v")

        base = out / module / "@v"
        base.mkdir(parents=True, exist_ok=True)
        (base / "list").write_text(_merge_list(base / "list", version))
        (base / f"{version}.info").write_text(json.dumps({"Version": version, "Time": INFO_TIME}))
        (base / f"{version}.mod").write_text(gomod)
        with zipfile.ZipFile(base / f"{version}.zip", "w", zipfile.ZIP_DEFLATED) as z:
            for file in _module_files(d):
                info = zipfile.ZipInfo(f"{module}@{version}/{file.relative_to(d).as_posix()}", ZIP_TIME)
                info.external_attr = 0o644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, file.read_bytes())


def _merge_list(path: Path, version: str) -> str:
    versions = set(path.read_text().split()) if path.is_file() else set()
    versions.add(version)
    return "\n".join(sorted(versions)) + "\n"


def _module_files(root: Path):
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if not path.is_file() or path.is_symlink():
            continue
        dirs = rel.parts[:-1]
        if any(p in SKIP_DIRS for p in dirs):
            continue
        if any((root.joinpath(*dirs[: i + 1]) / "go.mod").is_file() for i in range(len(dirs))):
            continue  # inside a nested module
        yield path
