import json
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
NAMES = ["build", "runs", "player_moves", "modules_installed", "modules_live", "modules_unmodified", "no_duplication"]
BRANCH = "stitchability"


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
