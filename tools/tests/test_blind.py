import json
from pathlib import Path

from artifactory.blind import REMOVE, blind_export


def _trial(base, rnd, cond, k, *, doc):
    p = base / f"round-{rnd}-{cond}" / f"trial-{k}" / "project"
    (p / "internal/store").mkdir(parents=True)
    (p / "main.go").write_text("package main\n")
    (p / "internal/store/store.go").write_text("package store\n")
    (p / "internal/store/doc.go").write_text(doc)
    for d in (".arch", ".beads", ".opencode", ".claude", ".agents", ".git"):
        (p / d).mkdir()
        (p / d / "x").write_text("x")
    for f in ("artifactory.yaml", "MODULES.md", "AGENTS.md", "ARCHITECTURE.md"):
        (p / f).write_text("x")
    return p


def test_export(tmp_path):
    res = tmp_path / "results" / "t"
    _trial(res, 1, "control", 1, doc="package store\n")
    _trial(res, 1, "arc", 1, doc="// real docs\npackage store\n")
    _trial(res, 2, "arc", 1, doc="package store\n")  # other round, ignored
    out = tmp_path / "out"
    key = blind_export(res, 1, ["control", "arc"], out, seed=3)
    assert key == tmp_path / "key.json" and not key.is_relative_to(out)
    k = json.loads(key.read_text())
    assert sorted(k) == ["P01", "P02"]
    assert sorted((v["condition"], v["trial"]) for v in k.values()) == [("arc", 1), ("control", 1)]
    for label, v in k.items():
        d = out / label
        assert (d / "main.go").exists() and (d / "internal/store/store.go").exists()
        for r in REMOVE:
            assert not (d / r).exists(), r
        assert (d / "internal/store/doc.go").exists() == (v["condition"] == "arc")
    # seeded: same seed same key
    key2 = blind_export(res, 1, ["control", "arc"], tmp_path / "out2", seed=3)
    assert json.loads(key2.read_text()) == k
