import json

from artifactory import cli
from artifactory.roadmap import CONTRACTS, score_roadmap

KITS = ["SettingsKit", "CursorKit", "TransitionKit"]


def write(path, beads):
    path.write_text("".join(json.dumps(b) + "\n" for b in beads))
    return path


def bead(id, description, status="open", labels=None, title="t"):
    b = {"_type": "issue", "id": id, "title": title, "description": description, "status": status}
    if labels is not None:
        b["labels"] = labels
    return b


def test_kits_unknown_names_and_missing_lines(tmp_path):
    f = write(tmp_path / "r.jsonl", [
        bead("a", "Fade rooms.\nModules: TransitionKit, SettingsKit"),
        bead("b", "Modules: Bogus , CursorKit"),
        bead("c", "Modules: none"),
        bead("d", "No line here"),
    ])
    s = score_roadmap(f, KITS, CONTRACTS)
    assert s["kits_named"] == ["CursorKit", "SettingsKit", "TransitionKit"]
    assert s["unknown_modules"] == ["Bogus"]
    assert s["no_modules_line"] == ["d"]
    assert s["beads"] == 4


def test_status_counts_and_non_issue_rows_ignored(tmp_path):
    f = write(tmp_path / "r.jsonl", [
        bead("a", "Modules: none", "closed"), bead("b", "Modules: none", "blocked"),
        bead("c", "Modules: none"), {"_type": "memory", "key": "x"},
    ])
    s = score_roadmap(f, KITS, CONTRACTS)
    assert s["by_status"] == {"closed": 1, "blocked": 1, "open": 1}
    assert s["beads"] == 3


def test_gap_bead_covering_dialogue(tmp_path):
    yes = write(tmp_path / "y.jsonl", [bead("a", "Build the dialogue box.\nModules: none", labels=["gap"])])
    no = write(tmp_path / "n.jsonl", [bead("a", "Build the dialogue box.\nModules: none", labels=["ui"]),
                                      bead("b", "Add saves.\nModules: none", labels=["gap"])])
    assert score_roadmap(yes, KITS, CONTRACTS)["gap_covers_dialogue"] is True
    assert score_roadmap(no, KITS, CONTRACTS)["gap_covers_dialogue"] is False


def test_contracts_match_whole_words_only(tmp_path):
    f = write(tmp_path / "r.jsonl", [
        bead("a", "Add a player in res://rooms/hall.tscn.\nModules: none"),
        bead("b", "The players and keeperless interaction.\nModules: none"),
    ])
    s = score_roadmap(f, KITS, CONTRACTS)
    assert s["contracts"] == ["player", "res://rooms/hall.tscn"]


def test_cli_prints_text_and_json(tmp_path, capsys):
    t = tmp_path / "test"
    t.mkdir()
    (t / "test.yaml").write_text("ecosystem: godot-csharp\nfixture: .\nprompt: p.md\ntime_limit_s: 1\n"
                                 "modules: [SettingsKit]\n")
    (t / "p.md").write_text("x")
    (t / "duplication.yaml").write_text("{}")
    f = write(tmp_path / "r.jsonl", [bead("a", "Modules: SettingsKit, Nope")])
    assert cli.main(["roadmap-score", str(f), "--test", str(t)]) == 0
    out = capsys.readouterr().out
    assert "SettingsKit" in out and "Nope" in out
    assert cli.main(["roadmap-score", str(f), "--test", str(t), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["kits_named"] == ["SettingsKit"]
