"""Load an acceptance-test definition (tests/acceptance/<name>/)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class AcceptanceTest:
    name: str
    ecosystem: str
    fixture: Path
    prompt: str
    modules: list[str]
    time_limit_s: int
    duplication: dict[str, list[str]]
    roadmap_prompt: str | None = None
    probe: str | None = None
    python_wheels: tuple[str, ...] = ()  # requirement specs put in the trial's wheel index (Python tests)
    dir: Path = Path(".")


def load_acceptance(dir: Path) -> AcceptanceTest:
    dir = Path(dir).resolve()
    cfg = yaml.safe_load((dir / "test.yaml").read_text())
    dup = yaml.safe_load((dir / "duplication.yaml").read_text()) or {}
    return AcceptanceTest(
        name=cfg.get("name", dir.name),
        ecosystem=cfg["ecosystem"],
        fixture=(dir / cfg["fixture"]).resolve(),
        prompt=(dir / cfg.get("prompt", "prompt.md")).read_text(),
        modules=list(cfg["modules"]),
        time_limit_s=int(cfg["time_limit_s"]),
        duplication={k: list(v) for k, v in dup.items()},
        roadmap_prompt=(dir / cfg["roadmap_prompt"]).read_text() if cfg.get("roadmap_prompt") else None,
        probe=cfg.get("probe"),
        python_wheels=tuple(str(x) for x in cfg.get("python_wheels") or ()),
        dir=dir,
    )
