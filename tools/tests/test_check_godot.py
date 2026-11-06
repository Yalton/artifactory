import dataclasses
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from artifactory.acceptance import AcceptanceTest
from artifactory.checks import godot as godot_checks
from artifactory.checks.godot import check_godot
from artifactory.result import CheckResult, TrialResult

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(__file__).resolve().parent / "data" / "godot"
BLANK = ROOT / "fixtures" / "godot-blank"
KITS = ["StubAKit", "StubBKit"]
NAMES = ["build", "runs", "player_moves", "player_visible", "room_present", "modules_installed", "modules_live", "modules_unmodified", "no_duplication"]
BRANCH = "stitchability"
NONCE = "abc123"


@pytest.fixture(autouse=True)
def checker_tmp(tmp_path, monkeypatch):
    """Keep the checker's working copies under this test's tmp_path."""
    work = tmp_path / "checker-tmp"
    work.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(work))


def git(*args, cwd):
    return subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout


def make_kit(root: Path, mirrors: Path, name: str) -> Path:
    """A stub kit repo plus a bare mirror with a `stitchability` branch."""
    src = root / "kits" / name
    src.mkdir(parents=True)
    (src / f"{name}.cs").write_text((DATA / "StubKit.cs.template").read_text().replace("__NAME__", name))
    git("init", "-q", "-b", "main", cwd=src)
    git("add", ".", cwd=src)
    git("commit", "-q", "-m", "stub kit", cwd=src)
    bare = mirrors / f"{name}.git"
    git("init", "-q", "--bare", str(bare), cwd=root)
    git("push", "-q", str(bare), f"main:{BRANCH}", cwd=src)
    return src


def make_project(tmp_path: Path, submodules=KITS, copied=()) -> tuple[Path, Path]:
    """Build a trial project: base files, kits added as submodules or copied in."""
    mirrors = tmp_path / "mirrors"
    mirrors.mkdir()
    project = tmp_path / "project"
    shutil.copytree(DATA / "base", project)
    git("init", "-q", "-b", "main", cwd=project)
    for name in [*submodules, *copied]:
        src = make_kit(tmp_path, mirrors, name)
        if name in submodules:
            git("submodule", "add", "-q", "-b", BRANCH, str(mirrors / f"{name}.git"), f"addons/{name}", cwd=project)
        else:
            shutil.copytree(src, project / "addons" / name, ignore=shutil.ignore_patterns(".git"))
    git("add", ".", cwd=project)
    git("commit", "-q", "-m", "trial", cwd=project)
    return project, mirrors


def acceptance(duplication=None) -> AcceptanceTest:
    return AcceptanceTest(
        name="stub-test", ecosystem="godot-csharp", fixture=BLANK, prompt="p",
        modules=list(KITS), time_limit_s=60,
        duplication=duplication or {},
    )


def by_name(result: TrialResult) -> dict[str, CheckResult]:
    assert [c.name for c in result.checks] == NAMES
    return {c.name: c for c in result.checks}


def failing(result: TrialResult) -> set[str]:
    return {c.name for c in result.checks if not c.passed}


def test_trial_result_passed_and_json():
    ok = TrialResult("t", "1", [CheckResult("build", True, "")], None)
    assert ok.passed
    assert not TrialResult("t", "1", [CheckResult("build", True, "")], "timeout").passed
    assert not TrialResult("t", "1", [CheckResult("build", False, "x")], None).passed
    data = json.loads(ok.to_json())
    assert data["test"] == "t" and data["trial"] == "1" and data["passed"] is True
    assert data["reason"] is None
    assert data["checks"] == [{"name": "build", "passed": True, "detail": ""}]


@pytest.mark.godot
def test_good_project_passes_all(tmp_path):
    project, mirrors = make_project(tmp_path)
    before = git("status", "--porcelain", "--ignored", cwd=project)
    # Pattern matches only inside the kits, so passing proves addons/<Kit>/ is excluded.
    result = check_godot(project, acceptance({"StubAKit": [r'GD\.Print\("\[']}), mirrors, BRANCH)
    checks = by_name(result)
    assert result.passed, result.to_json()
    assert all(c.passed for c in checks.values())
    assert "w=" in checks["player_moves"].detail
    assert "camera=Camera3D" in checks["player_visible"].detail
    assert checks["room_present"].detail == "PROBE room_present=true"
    assert result.reason is None
    # The input project is never modified.
    assert git("status", "--porcelain", "--ignored", cwd=project) == before
    assert not (project / ".godot").exists()


@pytest.mark.godot
def test_player_not_moving_fails_player_moves(tmp_path):
    project, mirrors = make_project(tmp_path)
    shutil.copy(DATA / "variants" / "PlayerStill.cs", project / "Player.cs")
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    assert failing(result) == {"player_moves"}, result.to_json()


@pytest.mark.godot
def test_fake_probe_lines_from_game_code_do_not_pass_player_moves(tmp_path):
    project, mirrors = make_project(tmp_path)
    shutil.copy(DATA / "variants" / "PlayerFakeProbe.cs", project / "Player.cs")
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    assert failing(result) == {"player_moves"}, result.to_json()


@pytest.mark.godot
def test_no_camera_fails_player_visible(tmp_path):
    project, mirrors = make_project(tmp_path)
    scene = project / "Main.tscn"
    scene.write_text(scene.read_text().split("\n[node name=\"Camera3D\"")[0])
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    assert failing(result) == {"player_visible"}, result.to_json()
    assert "camera=none start=no_camera" in by_name(result)["player_visible"].detail


@pytest.mark.godot
def test_camera_facing_away_fails_player_visible(tmp_path):
    project, mirrors = make_project(tmp_path)
    scene = project / "Main.tscn"
    # Same position, rotated 180 degrees about Y: looks along +Z, away from the player.
    scene.write_text(scene.read_text().replace(
        "Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 10)",
        "Transform3D(-1, 0, 0, 0, 1, 0, 0, 0, -1, 0, 1, 10)"))
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    assert failing(result) == {"player_visible"}, result.to_json()
    assert "start=out_of_frame" in by_name(result)["player_visible"].detail


@pytest.mark.godot
def test_wall_between_camera_and_player_fails_player_visible(tmp_path):
    project, mirrors = make_project(tmp_path)
    scene = project / "Main.tscn"
    text = scene.read_text().replace("load_steps=3", "load_steps=4")
    text = text.replace('[node name="Main"', '[sub_resource type="BoxShape3D" id="wall"]\nsize = Vector3(40, 40, 1)\n\n[node name="Main"')
    text += '\n[node name="Wall" type="StaticBody3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 7)\n\n'
    text += '[node name="Shape" type="CollisionShape3D" parent="Wall"]\nshape = SubResource("wall")\n'
    scene.write_text(text)
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    assert failing(result) == {"player_visible"}, result.to_json()
    assert "camera=Camera3D start=blocked" in by_name(result)["player_visible"].detail


@pytest.mark.godot
def test_player_without_drawn_mesh_fails_player_visible(tmp_path):
    project, mirrors = make_project(tmp_path)
    scene = project / "Main.tscn"
    scene.write_text(scene.read_text().replace('mesh = SubResource("capsule")\n', ""))
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    assert failing(result) == {"player_visible"}, result.to_json()
    assert "start=no_drawn_mesh" in by_name(result)["player_visible"].detail


@pytest.mark.godot
def test_first_person_camera_passes_player_visible(tmp_path):
    project, mirrors = make_project(tmp_path)
    scene = project / "Main.tscn"
    # Camera at the player's head, child of the player: the player's origin is behind it.
    scene.write_text(scene.read_text().replace(
        '[node name="Camera3D" type="Camera3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 10)',
        '[node name="Camera3D" type="Camera3D" parent="Player"]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0.8, 0)'))
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    assert failing(result) == set(), result.to_json()


@pytest.mark.godot
def test_follow_camera_behind_wall_fails_player_visible(tmp_path):
    project, mirrors = make_project(tmp_path)
    scene = project / "Main.tscn"
    # A third-person camera parented to the player, with a wall between them.
    text = scene.read_text().replace("load_steps=3", "load_steps=4").replace(
        '[node name="Camera3D" type="Camera3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 10)',
        '[node name="Camera3D" type="Camera3D" parent="Player"]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 10)')
    text = text.replace('[node name="Main"', '[sub_resource type="BoxShape3D" id="wall"]\nsize = Vector3(40, 40, 1)\n\n[node name="Main"')
    text += '\n[node name="Wall" type="StaticBody3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 7)\n\n'
    text += '[node name="Shape" type="CollisionShape3D" parent="Wall"]\nshape = SubResource("wall")\n'
    scene.write_text(text)
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    assert failing(result) == {"player_visible"}, result.to_json()
    assert "start=blocked" in by_name(result)["player_visible"].detail


@pytest.mark.godot
def test_wall_mesh_without_body_fails_player_visible(tmp_path):
    project, mirrors = make_project(tmp_path)
    scene = project / "Main.tscn"
    # A drawn wall with no physics body hides the player as surely as a collider does.
    text = scene.read_text().replace('[node name="Main"', '[sub_resource type="BoxMesh" id="screen"]\nsize = Vector3(40, 40, 1)\n\n[node name="Main"')
    text += '\n[node name="Screen" type="MeshInstance3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 7)\nmesh = SubResource("screen")\n'
    scene.write_text(text)
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    assert failing(result) == {"player_visible"}, result.to_json()
    assert "camera=Camera3D start=blocked" in by_name(result)["player_visible"].detail


@pytest.mark.godot
def test_player_half_sunk_in_floor_is_still_visible(tmp_path):
    project, mirrors = make_project(tmp_path)
    scene = project / "Main.tscn"
    # The floor's box holds the capsule's centre, but its top shows above the floor.
    scene.write_text(scene.read_text().replace(
        'size = Vector3(30, 0.2, 30)', 'size = Vector3(30, 2, 30)').replace(
        "Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, -1.1, 0)", "Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, -0.5, 0)"))
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    assert failing(result) == set(), result.to_json()


def _without_nodes(text: str, names: list[str]) -> str:
    """Drop the named Room children (each node block runs to the next blank line)."""
    for name in names:
        start = text.index(f'[node name="{name}" type="MeshInstance3D" parent="Room"]')
        end = text.index("\n\n", start) + 2
        text = text[:start] + text[end:]
    return text


@pytest.mark.godot
def test_no_room_fails_room_present(tmp_path):
    project, mirrors = make_project(tmp_path)
    scene = project / "Main.tscn"
    scene.write_text(_without_nodes(scene.read_text(), ["Floor", "WallN", "WallS", "WallE", "WallW"]))
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    assert failing(result) == {"room_present"}, result.to_json()
    assert by_name(result)["room_present"].detail == "PROBE room_present=false missing=down,+x,-x,+z,-z"


@pytest.mark.godot
def test_missing_wall_fails_room_present(tmp_path):
    project, mirrors = make_project(tmp_path)
    scene = project / "Main.tscn"
    scene.write_text(_without_nodes(scene.read_text(), ["WallE"]))
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    assert failing(result) == {"room_present"}, result.to_json()
    assert by_name(result)["room_present"].detail == "PROBE room_present=false missing=+x"


@pytest.mark.godot
def test_room_as_one_mesh_around_player_passes(tmp_path):
    project, mirrors = make_project(tmp_path)
    scene = project / "Main.tscn"
    # One big box holding the player and the camera, as a room modelled as a single mesh would.
    text = _without_nodes(scene.read_text(), ["Floor", "WallN", "WallS", "WallE", "WallW"])
    text = text.replace('[node name="Main"', '[sub_resource type="BoxMesh" id="shell"]\nsize = Vector3(30, 6, 30)\n\n[node name="Main"')
    text += '\n[node name="Shell" type="MeshInstance3D" parent="Room"]\nmesh = SubResource("shell")\n'
    scene.write_text(text)
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    assert failing(result) == set(), result.to_json()


@pytest.mark.godot
def test_wide_camera_is_framed_at_16_by_9(tmp_path):
    project, mirrors = make_project(tmp_path)
    scene = project / "Main.tscn"
    # The player starts 8 left of centre at depth 8: outside a square frame, inside 16:9.
    scene.write_text(scene.read_text().replace(
        "Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 10)",
        "Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 8, 1, 8)"))
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    assert failing(result) == set(), result.to_json()


@pytest.mark.godot
def test_missing_marker_fails_modules_live(tmp_path):
    project, mirrors = make_project(tmp_path)
    godot_file = project / "project.godot"
    godot_file.write_text(godot_file.read_text().replace('StubBKit="*res://addons/StubBKit/StubBKit.cs"\n', ""))
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    checks = by_name(result)
    assert failing(result) == {"modules_live"}, result.to_json()
    assert "StubBKit" in checks["modules_live"].detail
    assert "StubAKit" not in checks["modules_live"].detail


@pytest.mark.godot
def test_copied_kit_counts_as_not_installed(tmp_path):
    project, mirrors = make_project(tmp_path, submodules=["StubAKit"], copied=["StubBKit"])
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    checks = by_name(result)
    assert not checks["modules_installed"].passed
    assert "StubBKit" in checks["modules_installed"].detail
    assert "copied, not submodule" in checks["modules_installed"].detail
    assert "StubAKit" not in checks["modules_installed"].detail
    assert not checks["modules_unmodified"].passed
    assert checks["build"].passed and checks["runs"].passed and checks["modules_live"].passed


@pytest.mark.godot
def test_dirty_submodule_fails_unmodified(tmp_path):
    project, mirrors = make_project(tmp_path)
    kit_file = project / "addons" / "StubAKit" / "StubAKit.cs"
    kit_file.write_text(kit_file.read_text() + "// local edit\n")
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    checks = by_name(result)
    assert failing(result) == {"modules_unmodified"}, result.to_json()
    assert "StubAKit" in checks["modules_unmodified"].detail
    assert "StubBKit" not in checks["modules_unmodified"].detail


@pytest.mark.godot
def test_unpublished_submodule_commit_fails(tmp_path):
    project, mirrors = make_project(tmp_path)
    kit = project / "addons" / "StubBKit"
    (kit / "Extra.cs").write_text("namespace StubKits;\npublic static class Extra { }\n")
    git("add", ".", cwd=kit)
    git("commit", "-q", "-m", "local change", cwd=kit)
    git("add", ".", cwd=project)
    git("commit", "-q", "-m", "bump kit", cwd=project)
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    checks = by_name(result)
    assert failing(result) == {"modules_unmodified"}, result.to_json()
    assert "StubBKit" in checks["modules_unmodified"].detail
    assert "StubAKit" not in checks["modules_unmodified"].detail


@pytest.mark.godot
def test_duplication_regex_hit_fails(tmp_path):
    project, mirrors = make_project(tmp_path)
    (project / "Scripts").mkdir()
    shutil.copy(DATA / "variants" / "SettingsStore.cs", project / "Scripts" / "SettingsStore.cs")
    result = check_godot(project, acceptance({"StubBKit": [r"ConfigFile\(\)", r"never_matches_anything"]}), mirrors, BRANCH)
    checks = by_name(result)
    assert failing(result) == {"no_duplication"}, result.to_json()
    detail = checks["no_duplication"].detail
    assert "Scripts/SettingsStore.cs:10" in detail
    assert "StubBKit" in detail


@pytest.mark.godot
def test_duplication_ignores_other_library_kits(tmp_path):
    project, mirrors = make_project(tmp_path)
    git("init", "-q", "--bare", str(mirrors / "ExtraKit.git"), cwd=tmp_path)
    (project / "addons" / "ExtraKit").mkdir()
    shutil.copy(DATA / "variants" / "SettingsStore.cs", project / "addons" / "ExtraKit" / "SettingsStore.cs")
    git("add", ".", cwd=project)
    git("commit", "-q", "-m", "extra kit", cwd=project)
    result = check_godot(project, acceptance({"StubBKit": [r"ConfigFile\(\)"]}), mirrors, BRANCH)
    assert failing(result) == set(), result.to_json()


@pytest.mark.godot
def test_godot_run_timeout_is_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(godot_checks, "RUN_TIMEOUT_S", 15)
    project, mirrors = make_project(tmp_path)
    shutil.copy(DATA / "variants" / "Hang.cs", project / "Hang.cs")
    godot_file = project / "project.godot"
    godot_file.write_text(godot_file.read_text().replace("[autoload]\n\n", '[autoload]\n\nHang="*res://Hang.cs"\n'))
    result = check_godot(project, acceptance(), mirrors, BRANCH)
    checks = by_name(result)
    assert checks["build"].passed
    assert not checks["runs"].passed
    assert "timed out" in checks["runs"].detail
    assert not checks["player_moves"].passed
    assert not checks["player_visible"].passed
    assert not checks["room_present"].passed
    assert result.reason is None


@pytest.mark.godot
def test_baseline_mode_skips_live_and_marks_manual(tmp_path):
    project, mirrors = make_project(tmp_path)
    result = check_godot(project, acceptance(), mirrors, "main", baseline=True)
    checks = by_name(result)
    for name in ("modules_live", "modules_unmodified"):
        assert checks[name].passed is False
        assert checks[name].detail.startswith("manual:")
    assert failing(result) == {"modules_live", "modules_unmodified"}, result.to_json()


# --- lantern probe mode ----------------------------------------------------

LANTERN = DATA / "lantern"
LANTERN_NAMES = [n for n in NAMES if n != "room_present"] + ["rooms", "dialogue", "title_scene"]
needs_godot = pytest.mark.skipif(not (shutil.which("godot") and shutil.which("dotnet")),
                                 reason="needs godot and dotnet on PATH")


def lantern_test(fixture: Path = BLANK) -> AcceptanceTest:
    return AcceptanceTest(
        name="lantern-stub", ecosystem="godot-csharp", fixture=fixture, prompt="p",
        modules=[], time_limit_s=60, duplication={}, probe="lantern",
    )


def fake_project(path: Path, main_scene: str | None = "res://Title.tscn") -> Path:
    path.mkdir(parents=True)
    app = f'run/main_scene="{main_scene}"\n' if main_scene else ""
    (path / "project.godot").write_text(f'config_version=5\n\n[application]\n\n{app}\n[dotnet]\n\n'
                                        'project/assembly_name="Fake"\n')
    (path / "Fake.csproj").write_text("<Project/>\n")
    return path


@pytest.fixture
def fake_godot(monkeypatch):
    """Replace every dotnet/godot process with a recorder that succeeds and prints `output`."""
    calls = []
    state = {"output": ""}

    def run(cmd, cwd, timeout, log, env=None):
        calls.append((cmd, dict(env or {})))
        out = state["output"].replace("PROBE ", f"PROBE {(env or {}).get('ARTIFACTORY_PROBE_NONCE', '')} ")
        return godot_checks.Proc(0, out if cmd[0] == "godot" else "", 0.1)

    monkeypatch.setattr(godot_checks, "run_process", run)
    monkeypatch.setattr(godot_checks, "_baseline_errors", {})
    return calls, state


def test_capsule_room_check_names_unchanged(tmp_path, fake_godot):
    project = fake_project(tmp_path / "project")
    test = dataclasses.replace(acceptance(), modules=[], fixture=fake_project(tmp_path / "blank"))
    result = check_godot(project, test, tmp_path, BRANCH)
    assert [c.name for c in result.checks] == NAMES
    assert all("ARTIFACTORY_PROBE_MODE" not in env for _, env in fake_godot[0])


def test_lantern_appends_rooms_dialogue_title(tmp_path, fake_godot):
    calls, state = fake_godot
    state["output"] = "PROBE rooms=true missing=none\nPROBE dialogue=true problem=none\n"
    project = fake_project(tmp_path / "project")
    result = check_godot(project, lantern_test(fake_project(tmp_path / "blank")), tmp_path, BRANCH)
    assert [c.name for c in result.checks] == LANTERN_NAMES
    checks = {c.name: c for c in result.checks}
    assert checks["rooms"].passed and checks["rooms"].gating
    assert checks["dialogue"].passed and checks["dialogue"].gating
    assert checks["title_scene"].passed and not checks["title_scene"].gating


def test_lantern_build_failure_marks_rooms_and_dialogue_not_run(tmp_path, fake_godot):
    project = tmp_path / "project"
    project.mkdir()  # no project.godot: the build fails before anything runs
    result = check_godot(project, lantern_test(), tmp_path, BRANCH)
    checks = {c.name: c for c in result.checks}
    assert [c.name for c in result.checks] == LANTERN_NAMES
    for name in ("rooms", "dialogue"):
        assert not checks[name].passed and checks[name].detail == "not run: build failed"


def test_probe_mode_reaches_only_the_trial_godot_run(tmp_path, fake_godot, monkeypatch):
    calls, _ = fake_godot
    monkeypatch.setenv("ARTIFACTORY_PROBE_MODE", "lantern")  # never inherited by the baseline
    blank = fake_project(tmp_path / "blank", main_scene=None)
    project = fake_project(tmp_path / "project")
    check_godot(project, lantern_test(blank), tmp_path, BRANCH)
    # The trial copy's build, import and run, then the blank baseline's build, import and run.
    modes = [env.get("ARTIFACTORY_PROBE_MODE") for _, env in calls]
    assert modes == [None, None, "lantern", None, None, None], [c for c, _ in calls]
    assert calls[2][0][0] == "godot" and "--import" not in calls[2][0]


def test_blank_baseline_gets_no_probe_mode(tmp_path, fake_godot, monkeypatch):
    calls, _ = fake_godot
    monkeypatch.setenv("ARTIFACTORY_PROBE_MODE", "lantern")
    godot_checks._blank_errors(fake_project(tmp_path / "blank", main_scene=None))
    assert len(calls) == 3
    assert all("ARTIFACTORY_PROBE_MODE" not in env for _, env in calls)


@pytest.mark.parametrize("line,name,passed", [
    ("PROBE rooms=true missing=none", "rooms", True),
    ("PROBE rooms=false missing=hall,tower", "rooms", False),
    ("PROBE dialogue=true problem=none", "dialogue", True),
    ("PROBE dialogue=false problem=not_shown", "dialogue", False),
])
def test_check_probe_parses_lantern_lines(line, name, passed):
    out = line.replace("PROBE ", f"PROBE {NONCE} ")
    check = godot_checks._check_probe(godot_checks.Proc(0, f"noise\n{out}\n", 1.0), name, NONCE)
    assert check.passed is passed and check.detail == line


def write_room(project: Path, name: str, uid: str) -> None:
    (project / "rooms").mkdir(exist_ok=True)
    (project / "rooms" / f"{name}.tscn").write_text(
        f'[gd_scene load_steps=1 format=3 uid="{uid}"]\n\n[node name="{name}" type="Node3D"]\n')


def test_title_scene_passes_for_a_title_screen(tmp_path):
    project = fake_project(tmp_path / "p", main_scene="res://Title.tscn")
    check = godot_checks._check_title_scene(project)
    assert check.name == "title_scene" and check.passed and not check.gating


def test_title_scene_fails_when_main_scene_is_a_room(tmp_path):
    project = fake_project(tmp_path / "p", main_scene="res://rooms/courtyard.tscn")
    check = godot_checks._check_title_scene(project)
    assert not check.passed and "courtyard" in check.detail


def test_title_scene_fails_without_main_scene(tmp_path):
    assert not godot_checks._check_title_scene(fake_project(tmp_path / "p", main_scene=None)).passed


def test_title_scene_resolves_uid_main_scene(tmp_path):
    room = fake_project(tmp_path / "room", main_scene="uid://hallroom123")
    write_room(room, "courtyard", "uid://court456")
    write_room(room, "hall", "uid://hallroom123")
    check = godot_checks._check_title_scene(room)
    assert not check.passed and "res://rooms/hall.tscn" in check.detail
    title = fake_project(tmp_path / "title", main_scene="uid://title789")
    write_room(title, "hall", "uid://hallroom123")
    assert godot_checks._check_title_scene(title).passed


def make_lantern(tmp_path: Path) -> Path:
    """A tiny 3D Lantern Keep: title main scene, three rooms, a keeper whose dialogue opens on `interact`."""
    project = tmp_path / "lantern"
    shutil.copytree(BLANK, project)
    shutil.copytree(LANTERN, project, dirs_exist_ok=True)
    # The capsule room's move_* actions plus `interact` on E (physical keycode 69).
    base = (DATA / "base" / "project.godot").read_text()
    inputs = base[base.index("[input]"):]
    forward = inputs[inputs.index("move_forward="):inputs.index("move_back=")]
    interact = forward.replace("move_forward=", "interact=").replace('"physical_keycode":87', '"physical_keycode":69')
    godot_file = project / "project.godot"
    text = godot_file.read_text().replace("[application]\n", '[application]\n\nrun/main_scene="res://Title.tscn"\n')
    godot_file.write_text(text + "\n" + inputs + interact)
    git("init", "-q", "-b", "main", cwd=project)
    git("add", ".", cwd=project)
    git("commit", "-q", "-m", "lantern", cwd=project)
    return project


@pytest.mark.godot
@needs_godot
def test_lantern_fixture_passes_rooms_and_dialogue(tmp_path):
    project = make_lantern(tmp_path)
    (tmp_path / "mirrors").mkdir()
    result = check_godot(project, lantern_test(), tmp_path / "mirrors", BRANCH)
    checks = {c.name: c for c in result.checks}
    assert [c.name for c in result.checks] == LANTERN_NAMES
    assert checks["rooms"].passed, result.to_json()
    assert checks["dialogue"].passed, result.to_json()
    assert failing(result) == set(), result.to_json()


@pytest.mark.godot
@needs_godot
def test_lantern_missing_room_and_keeper_fail(tmp_path):
    project = make_lantern(tmp_path)
    (project / "rooms" / "tower.tscn").unlink()
    hall = project / "rooms" / "hall.tscn"
    hall.write_text(hall.read_text().replace('groups=["keeper"]', ""))
    (tmp_path / "mirrors").mkdir()
    result = check_godot(project, lantern_test(), tmp_path / "mirrors", BRANCH)
    checks = {c.name: c for c in result.checks}
    assert failing(result) == {"rooms", "dialogue"}, result.to_json()
    assert checks["rooms"].detail == "PROBE rooms=false missing=tower"
    assert checks["dialogue"].detail == "PROBE dialogue=false problem=no_keeper"


def test_check_probe_surfaces_lantern_error():
    run = godot_checks.Proc(0, f"PROBE {NONCE} player_moves=true w=4 d=4\nPROBE {NONCE} lantern_error=NullReferenceException: boom\n", 1.0)
    check = godot_checks._check_probe(run, "rooms", NONCE)
    assert not check.passed
    assert check.detail == "probe never reported: PROBE lantern_error=NullReferenceException: boom"


def test_only_lantern_selects_a_probe_mode(tmp_path, fake_godot):
    calls, _ = fake_godot
    test = dataclasses.replace(lantern_test(fake_project(tmp_path / "blank")), probe="other")
    result = check_godot(fake_project(tmp_path / "project"), test, tmp_path, BRANCH)
    assert [c.name for c in result.checks] == NAMES
    assert all("ARTIFACTORY_PROBE_MODE" not in env for _, env in calls)


@pytest.mark.godot
@needs_godot
def test_lantern_dialogue_visible_before_interact_fails(tmp_path):
    project = make_lantern(tmp_path)
    hall = project / "rooms" / "hall.tscn"
    hall.write_text(hall.read_text().replace("visible = false\n", ""))
    (tmp_path / "mirrors").mkdir()
    result = check_godot(project, lantern_test(), tmp_path / "mirrors", BRANCH)
    checks = {c.name: c for c in result.checks}
    assert failing(result) == {"dialogue"}, result.to_json()
    assert checks["dialogue"].detail == "PROBE dialogue=false problem=shown_before_interact"


@pytest.mark.godot
@needs_godot
def test_lantern_dialogue_canvas_layer_counts_its_children(tmp_path):
    # The always-visible layer is in group dialogue; only its hidden Label opens on interact.
    project = make_lantern(tmp_path)
    hall = project / "rooms" / "hall.tscn"
    hall.write_text(hall.read_text()
                    .replace('[node name="Ui" type="CanvasLayer" parent="."]', '[node name="Ui" type="CanvasLayer" parent="." groups=["dialogue"]]')
                    .replace('parent="Ui" groups=["dialogue"]', 'parent="Ui"'))
    (project / "Keeper.cs").write_text((project / "Keeper.cs").read_text().replace(
        'GetFirstNodeInGroup("dialogue") is CanvasItem dialogue', 'GetFirstNodeInGroup("dialogue")?.GetChild(0) is CanvasItem dialogue'))
    (tmp_path / "mirrors").mkdir()
    result = check_godot(project, lantern_test(), tmp_path / "mirrors", BRANCH)
    assert failing(result) == set(), result.to_json()


# --- MoveCheck.cs in the consumer notes must compile -------------------------

@pytest.mark.godot
@pytest.mark.skipif(not shutil.which("dotnet"), reason="needs dotnet on PATH")
def test_movecheck_block_compiles(tmp_path):
    notes = (ROOT / "standard" / "consumer" / "godot-csharp.md").read_text()
    blocks = re.findall(r"```csharp\n(.*?)```", notes, re.S)
    code = next(b for b in blocks if "partial class MoveCheck" in b)
    project = tmp_path / "project"
    shutil.copytree(BLANK, project)
    (project / "MoveCheck.cs").write_text(code)
    result = subprocess.run(["dotnet", "build"], cwd=project, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr


# --- probe line and marker parsing -------------------------------------------

def probe_run(*lines: str) -> godot_checks.Proc:
    return godot_checks.Proc(0, "\n".join(lines) + "\n", 1.0)


def test_probe_accepts_only_lines_with_the_nonce():
    run = probe_run("PROBE player_moves=true w=4 d=4", f"PROBE other player_moves=true w=4 d=4")
    check = godot_checks._check_probe(run, "player_moves", NONCE)
    assert not check.passed and check.detail.startswith("no PROBE lines carrying the run nonce")


def test_probe_ignores_fake_true_line_before_real_false_line():
    run = probe_run("PROBE player_moves=true w=4 d=4", f"PROBE {NONCE} player_moves=false w=0 d=0")
    check = godot_checks._check_probe(run, "player_moves", NONCE)
    assert not check.passed and check.detail == "PROBE player_moves=false w=0 d=0"


def test_probe_duplicate_lines_fail_in_either_order():
    real_true = f"PROBE {NONCE} player_moves=true w=4 d=4"
    real_false = f"PROBE {NONCE} player_moves=false w=0 d=0"
    for lines in ((real_false, real_true), (real_true, real_false), (real_true, real_true)):
        check = godot_checks._check_probe(probe_run(*lines), "player_moves", NONCE)
        assert not check.passed and check.detail.startswith("duplicate PROBE lines for player_moves (possible forgery)")


def test_probe_duplicate_lantern_name_fails():
    run = probe_run(f"PROBE {NONCE} rooms=false missing=hall", f"PROBE {NONCE} rooms=true missing=none")
    check = godot_checks._check_probe(run, "rooms", NONCE)
    assert not check.passed and "duplicate PROBE lines for rooms" in check.detail


def test_probe_forged_other_name_line_leaves_real_line_deciding():
    run = probe_run(f"PROBE {NONCE} player_moves=true w=4 d=4", f"PROBE {NONCE} player_visible=true camera=x")
    assert godot_checks._check_probe(run, "player_moves", NONCE).passed
    assert godot_checks._check_probe(run, "player_visible", NONCE).passed


def test_probe_missing_name_with_other_lines_says_which():
    run = probe_run(f"PROBE {NONCE} player_moves=true w=4 d=4")
    check = godot_checks._check_probe(run, "player_visible", NONCE)
    assert not check.passed and check.detail.startswith("probe did not report player_visible")


def test_probe_empty_nonce_accepts_nothing():
    run = probe_run("PROBE  player_moves=true", "PROBE player_moves=true")
    assert not godot_checks._check_probe(run, "player_moves", "").passed


def test_nonce_is_fresh_per_run_and_reaches_only_the_trial_run(tmp_path, fake_godot):
    calls, _ = fake_godot
    blank = fake_project(tmp_path / "blank", main_scene=None)
    for _ in range(2):
        check_godot(fake_project(tmp_path / "p", main_scene=None), dataclasses.replace(acceptance(), modules=[], fixture=blank),
                    tmp_path, BRANCH)
        shutil.rmtree(tmp_path / "p")
    nonces = [env["ARTIFACTORY_PROBE_NONCE"] for _, env in calls if "ARTIFACTORY_PROBE_NONCE" in env]
    assert len(nonces) == 2 and nonces[0] != nonces[1] and all(len(n) >= 16 for n in nonces)


def test_marker_must_be_a_whole_line(tmp_path):
    project = tmp_path / "project"
    (project / "addons" / "K").mkdir(parents=True)
    live = godot_checks._check_live
    assert live(project, ["K"], "noise\n  [K] live  \nmore").passed
    assert not live(project, ["K"], "print: [K] live (fake)").passed
    assert not live(project, ["K"], "x[K] live").passed


def test_marker_from_module_yaml_is_stripped(tmp_path):
    project = tmp_path / "project"
    (project / "addons" / "K").mkdir(parents=True)
    (project / "addons" / "K" / "module.yaml").write_text('liveness: "  [K] ready  "\n')
    assert godot_checks._marker(project, "K") == "[K] ready"
    assert godot_checks._check_live(project, ["K"], "[K] ready\n").passed


ENTRY = godot_checks.PROBE_AUTOLOAD


def autoload_lines(project: Path) -> list[str]:
    return (project / "project.godot").read_text().splitlines()


def test_add_autoload_puts_probe_first_among_existing_autoloads(tmp_path):
    (tmp_path / "project.godot").write_text('config_version=5\n\n[autoload]\n\nA="*res://a.cs"\nB="*res://b.cs"\n\n[dotnet]\n')
    godot_checks._add_autoload(tmp_path, ENTRY)
    lines = autoload_lines(tmp_path)
    assert lines[lines.index("[autoload]") + 1] == ENTRY


def test_add_autoload_replaces_preexisting_probe_key(tmp_path):
    (tmp_path / "project.godot").write_text(
        '[autoload]\n\nA="*res://a.cs"\nArtifactoryCheckerProbe="*res://evil.cs"\n')
    godot_checks._add_autoload(tmp_path, ENTRY)
    lines = autoload_lines(tmp_path)
    assert [l for l in lines if l.startswith("ArtifactoryCheckerProbe=")] == [ENTRY]
    assert lines.index(ENTRY) < lines.index('A="*res://a.cs"')


def test_add_autoload_with_two_autoload_sections_uses_first_and_keeps_one_probe(tmp_path):
    (tmp_path / "project.godot").write_text(
        '[autoload]\nA="*res://a.cs"\n\n[x]\n\n[autoload]\nArtifactoryCheckerProbe="*res://evil.cs"\nB="*res://b.cs"\n')
    godot_checks._add_autoload(tmp_path, ENTRY)
    lines = autoload_lines(tmp_path)
    assert lines[0] == "[autoload]" and lines[1] == ENTRY
    assert sum(l.startswith("ArtifactoryCheckerProbe=") for l in lines) == 1


def test_add_autoload_creates_section_when_missing(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n")
    godot_checks._add_autoload(tmp_path, ENTRY)
    assert autoload_lines(tmp_path)[-1] == ENTRY and "[autoload]" in autoload_lines(tmp_path)
