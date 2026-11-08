"""Blind export: copy experiment trial projects under shuffled labels with the tool traces removed."""
from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

REMOVE = (".arch", ".beads", ".opencode", ".claude", ".agents", ".git",
          "artifactory.yaml", "MODULES.md", "AGENTS.md", "ARCHITECTURE.md")
OVERLAY = Path(__file__).resolve().parents[2] / "fixtures" / "go-links-arc"


def _overlay_docs(overlay: Path) -> list[Path]:
    return [p.relative_to(overlay) for p in sorted(overlay.rglob("doc.go"))]


def _is_one_line(p: Path) -> bool:
    return len(p.read_text(errors="replace").strip().splitlines()) == 1


def blind_export(results_test_dir: Path, round_no: int, conditions: list[str], out: Path, seed: int,
                 overlay: Path = OVERLAY) -> Path:
    results_test_dir, out = Path(results_test_dir), Path(out)
    trials = []
    for c in conditions:
        for t in sorted((results_test_dir / f"round-{round_no}-{c}").glob("trial-*"),
                        key=lambda p: int(p.name.split("-")[1]) if p.name.split("-")[1].isdigit() else 0):
            if (t / "project").is_dir():
                trials.append((c, t))
    random.Random(seed).shuffle(trials)
    docs = _overlay_docs(overlay) if overlay.is_dir() else []
    key = {}
    for i, (c, t) in enumerate(trials, 1):
        label = f"P{i:02d}"
        dest = out / label
        shutil.copytree(t / "project", dest, symlinks=True)
        for name in REMOVE:
            p = dest / name
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
            elif p.exists() or p.is_symlink():
                p.unlink()
        for d in docs:
            p = dest / d
            if p.is_file() and _is_one_line(p):
                p.unlink()
        key[label] = {"condition": c, "trial": int(t.name.split("-")[1])}
    key_path = out.parent / "key.json"
    key_path.write_text(json.dumps(key, indent=2) + "\n")
    return key_path
