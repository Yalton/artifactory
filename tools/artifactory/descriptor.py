"""Load and validate a module's module.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

ECOSYSTEMS = ("godot-csharp", "go")
STR_FIELDS = ("name", "ecosystem", "version", "summary", "install", "liveness", "docs", "example", "test")
LIST_FIELDS = ("replaces", "setup", "entry")


class DescriptorError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


@dataclass(frozen=True)
class Descriptor:
    name: str
    ecosystem: Literal["godot-csharp", "go"]
    version: str
    summary: str
    replaces: list[str]
    install: str
    setup: list[str]
    entry: list[str]
    liveness: str
    docs: str
    example: str
    test: str
    path: Path


def load_descriptor(module_dir: Path) -> Descriptor:
    module_dir = Path(module_dir)
    file = module_dir / "module.yaml"
    if not file.is_file():
        raise DescriptorError([f"{file}: module.yaml not found"])
    try:
        data = yaml.safe_load(file.read_text())
    except yaml.YAMLError as e:
        raise DescriptorError([f"{file}: invalid YAML: {e}"])
    if not isinstance(data, dict):
        raise DescriptorError([f"{file}: must be a mapping"])

    problems: list[str] = []
    values: dict = {}
    for f in STR_FIELDS:
        v = data.get(f)
        if v is None or (isinstance(v, str) and not v.strip()):
            problems.append(f"missing field: {f}")
        elif not isinstance(v, (str, int, float)) or isinstance(v, bool):
            problems.append(f"{f}: must be a string")
        else:
            values[f] = str(v).strip()
    for f in LIST_FIELDS:
        v = data.get(f)
        if v is None and f == "setup":
            values[f] = []
        elif v is None:
            problems.append(f"missing field: {f}")
        elif not isinstance(v, list) or not all(isinstance(i, str) for i in v):
            problems.append(f"{f}: must be a list of strings")
        else:
            values[f] = [i.strip() for i in v]

    eco = values.get("ecosystem")
    if eco is not None and eco not in ECOSYSTEMS:
        problems.append(f"ecosystem: must be one of {', '.join(ECOSYSTEMS)}")
    summary = values.get("summary")
    if summary is not None and ("\n" in summary or len(summary) >= 100):
        problems.append("summary: must be one line under 100 characters")
    replaces = values.get("replaces")
    if replaces is not None:
        if not 1 <= len(replaces) <= 5:
            problems.append("replaces: needs 1 to 5 items")
        if any(not r or len(r) >= 80 for r in replaces):
            problems.append("replaces: each item must be non-empty and under 80 characters")
    if eco == "godot-csharp" and values.get("name") is not None:
        folder = module_dir.resolve().name
        if values["name"] != folder:
            problems.append(f"name: {values['name']!r} must match folder name {folder!r}")

    if problems:
        raise DescriptorError(problems)
    return Descriptor(path=module_dir, **values)
