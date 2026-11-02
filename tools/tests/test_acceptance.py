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
