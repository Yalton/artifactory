from pathlib import Path

from artifactory.descriptor import Descriptor
from artifactory.index import build_index, index_preamble


def desc(name, replaces=("thing",), setup=()):
    return Descriptor(
        name=name, ecosystem="go", version="1", summary=f"{name} summary",
        replaces=list(replaces), install=f"go get x/{name}", setup=list(setup), entry=[],
        liveness="l", docs="d", example="e", test="t", path=Path("."),
    )


def test_index_starts_with_preamble():
    assert build_index([desc("a")], "PREAMBLE TEXT").startswith("PREAMBLE TEXT")


def test_index_lists_name_summary_replaces_install_for_each_module():
    out = build_index([desc("zed", ["z thing"]), desc("alpha", ["a thing"])], "P")
    assert out.index("## alpha") < out.index("## zed")
    for n, r in (("alpha", "a thing"), ("zed", "z thing")):
        assert f"{n} summary" in out and f"- {r}" in out and f"go get x/{n}" in out
    assert "Use instead of writing:" in out


def test_index_renders_setup_after_install_only_when_present():
    with_setup = desc("alpha", setup=["add the autoload", "bind a key"])
    out = build_index([with_setup, desc("zed")], "P")
    assert out.index("go get x/alpha") < out.index("Setup:") < out.index("- add the autoload")
    assert out.index("- bind a key") < out.index("## zed")
    assert out.count("Setup:") == 1


def test_index_for_eight_modules_under_2000_words():
    ds = [desc(f"mod{i}", ["a phrase here", "another phrase here", "third phrase"]) for i in range(8)]
    pre = (Path(__file__).resolve().parents[2] / "standard" / "preamble.md").read_text()
    assert len(build_index(ds, pre).split()) < 2000


def test_index_preamble_appends_ecosystem_notes(tmp_path):
    (tmp_path / "consumer").mkdir()
    (tmp_path / "preamble.md").write_text("RULES\n")
    (tmp_path / "consumer" / "go.md").write_text("### Before finishing\nrun it\n")
    out = index_preamble("go", tmp_path)
    assert out.startswith("RULES") and "## Project notes (go)" in out and "run it" in out
    assert index_preamble("godot-csharp", tmp_path) == "RULES"


def test_real_godot_index_under_2000_words():
    ds = [desc(f"mod{i}", ["a phrase here", "another phrase here", "third phrase"]) for i in range(8)]
    assert len(build_index(ds, index_preamble("godot-csharp")).split()) < 2000
