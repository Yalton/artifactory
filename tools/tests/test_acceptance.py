import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from artifactory.acceptance import load_acceptance
from artifactory.harness import bd_binary, bd_env, bd_run, build_arc

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


def test_python_url_shortener_loads():
    t = load_acceptance(ROOT / "tests/acceptance/python-url-shortener")
    assert t.ecosystem == "python" and t.modules == ["env-settings", "json-kv", "http-runner"]
    assert t.python_app == "shortener" and t.app_port == 8080 and t.python_wheels == ()
    assert t.fixture == (ROOT / "fixtures/python-blank").resolve() and (t.fixture / ".gitignore").is_file()
    assert set(t.duplication) == set(t.modules)
    for p in (q for ps in t.duplication.values() for q in ps):
        re.compile(p)
    for contract in ("python -m shortener", "SHORTENER_PORT", "SHORTENER_DATA", "POST /links", "/healthz"):
        assert contract in t.prompt


LINKS = ROOT / "tests/acceptance/go-link-service"


def test_load_link_service():
    t = load_acceptance(LINKS)
    assert t.ecosystem == "go" and t.modules == ["config", "httpserver", "shortid", "kvstore"]
    assert t.main_pkg == "./cmd/links" and t.kit_checks == "report" and t.service == "links"
    assert t.time_limit_s == 7200 and t.conditions == ("control", "artifactory", "arc", "both")
    assert t.fixture == (ROOT / "fixtures/go-links-blank").resolve()
    assert (t.fixture / "go.mod").read_text().startswith("module links")
    assert t.arc_overlay == (ROOT / "fixtures/go-links-arc").resolve() and t.arc_overlay.is_dir()
    assert (LINKS / "arc-registry.yaml").is_file() and (LINKS / "roadmaps/frontier.jsonl").is_file()


def test_defaults_unchanged():
    t = load_acceptance(ROOT / "tests/acceptance/go-url-shortener")
    assert t.main_pkg == "./cmd/shortener" and t.kit_checks == "gate" and t.service == "shortener"
    assert t.arc_overlay is None and t.conditions == ()


def _roadmap():
    return [json.loads(l) for l in (LINKS / "roadmaps/frontier.jsonl").read_text().splitlines() if l.strip()]


def test_roadmap_shape():
    issues = _roadmap()
    assert [i["id"] for i in issues] == [f"links-{n}" for n in range(1, 5)]
    for n, i in enumerate(issues):
        deps = [(d["depends_on_id"], d["type"]) for d in i.get("dependencies", [])]
        assert deps == ([(f"links-{n}", "blocks")] if n else [])
        assert "Check:" in i["description"] and i["description"].rstrip().split("Check:")[-1].strip()


FORBIDDEN = re.compile(r"module|kit|artifactory|arc|AGENTS|MODULES|internal/|package|library|\bpkg\b", re.I)


def test_bead_texts_name_no_forbidden_word():
    for i in _roadmap():
        text = i["title"] + "\n" + i["description"]
        text = text.replace("./cmd/links", "").replace("go.mod", "")
        hit = FORBIDDEN.search(text)
        assert not hit, f"{i['id']}: {hit.group(0)!r} in ...{text[max(0, hit.start() - 30):hit.end() + 30]}..."


def test_roadmap_imports_into_bd(tmp_path):
    try:
        bd_binary()
    except FileNotFoundError:
        pytest.skip("bd not installed")
    home = tmp_path / "home"
    home.mkdir()
    proj = tmp_path / "p"
    proj.mkdir()
    env = bd_env("test", home)
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"], ["git", "config", "user.name", "t"]):
        subprocess.run(cmd, cwd=proj, check=True, env={"PATH": os.environ["PATH"], "HOME": str(home)})
    r = bd_run(proj, env, "init", "--stealth", "--non-interactive")
    assert r.returncode == 0, r.stdout + r.stderr
    r = bd_run(proj, env, "import", str(LINKS / "roadmaps/frontier.jsonl"))
    assert r.returncode == 0, r.stdout + r.stderr
    r = bd_run(proj, env, "ready", "--json")
    assert r.returncode == 0, r.stderr
    assert [i["id"] for i in json.loads(r.stdout)] == ["links-1"]


def test_registry_validates_against_fixture_and_overlay(tmp_path):
    try:
        arc = build_arc(tmp_path / "arcbuild")
    except (RuntimeError, FileNotFoundError, OSError) as e:
        pytest.skip(f"arc cannot be built: {e}")
    proj = tmp_path / "proj"
    t = load_acceptance(LINKS)
    shutil.copytree(t.fixture, proj)
    shutil.copytree(t.arc_overlay, proj, dirs_exist_ok=True)
    (proj / ".arch").mkdir()
    shutil.copy(LINKS / "arc-registry.yaml", proj / ".arch" / "registry.yaml")
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    subprocess.run(["git", "add", "-A"], cwd=proj, check=True)
    r = subprocess.run([str(arc), "validate"], cwd=proj, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
