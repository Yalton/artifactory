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
    python_app: str | None = None  # module the checker runs as `python -m <app>` (Python tests)
    app_port: int = 8080  # port the app serves /healthz on (Python tests; the checker also sets PORT)
    main_pkg: str = "./cmd/shortener"  # Go: the package the checker builds and runs
    kit_checks: str = "gate"  # "gate": kit use gates the verdict; "report": reported only
    service: str = "shortener"  # which service contract the checker runs ("shortener" or "links")
    arc_overlay: Path | None = None  # files copied over the fixture in arc conditions (the declared packages)
    conditions: tuple[str, ...] = ()  # conditions the test supports in roadmap rounds (empty: not condition-driven)
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
        python_app=cfg.get("python_app"),
        app_port=int(cfg.get("app_port", 8080)),
        main_pkg=cfg.get("main_pkg", "./cmd/shortener"),
        kit_checks=cfg.get("kit_checks", "gate"),
        service=cfg.get("service", "shortener"),
        arc_overlay=(dir / cfg["arc_overlay"]).resolve() if cfg.get("arc_overlay") else None,
        conditions=tuple(str(x) for x in cfg.get("conditions") or ()),
        dir=dir,
    )
