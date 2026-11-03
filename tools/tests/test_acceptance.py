import re
from pathlib import Path

from artifactory.acceptance import load_acceptance

ROOT = Path(__file__).resolve().parents[2]
GODOT = ["InputRemapKit", "SettingsKit", "CursorKit", "DebugLogKit", "DevConsoleKit", "CrashKit", "TransitionKit", "RunSaveKit"]


def test_load_both_acceptance_tests():
    godot = load_acceptance(ROOT / "tests/acceptance/godot-capsule-room")
    go = load_acceptance(ROOT / "tests/acceptance/go-url-shortener")
    assert godot.ecosystem == "godot-csharp" and len(godot.modules) == 8
    assert godot.modules == GODOT and godot.time_limit_s == 7200
    assert go.ecosystem == "go" and go.modules == ["config", "kvstore", "shortid", "httpserver"]
    assert go.time_limit_s == 2700
    for t in (godot, go):
        assert t.fixture.is_dir() and t.prompt.strip()
        assert set(t.duplication) <= set(t.modules) and t.duplication
        for patterns in t.duplication.values():
            assert patterns
            for p in patterns:
                re.compile(p)
    assert (godot.fixture / "project.godot").is_file()
    assert (go.fixture / "go.mod").read_text().startswith("module shortener")


def test_lantern_keep_has_roadmap_prompt_and_probe():
    t = load_acceptance(ROOT / "tests/acceptance/godot-lantern-keep")
    assert t.name == "godot-lantern-keep" and t.ecosystem == "godot-csharp"
    assert t.modules == GODOT and t.time_limit_s == 14400
    assert t.probe == "lantern"
    assert t.roadmap_prompt and "BRIEF.md" in t.roadmap_prompt
    assert "Modules:" in t.roadmap_prompt and "-l gap" in t.roadmap_prompt
    assert "Write the roadmap only. Do not build anything." in t.roadmap_prompt
    assert t.dir == (ROOT / "tests/acceptance/godot-lantern-keep").resolve()
    assert (t.fixture / "project.godot").is_file()
    for contract in ("`player`", "`keeper`", "`dialogue`", "`interact`", "res://rooms/tower.tscn", "dotnet build"):
        assert contract in t.prompt
    for p in (q for ps in t.duplication.values() for q in ps):
        re.compile(p)


def test_capsule_room_has_no_roadmap_prompt_or_probe():
    path = ROOT / "tests/acceptance/godot-capsule-room"
    t = load_acceptance(path)
    assert t.roadmap_prompt is None and t.probe is None
    assert t.dir == path.resolve()
