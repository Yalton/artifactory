from pathlib import Path

from artifactory.descriptor import Descriptor
from artifactory.index import build_index


def desc(name, replaces=("thing",)):
    return Descriptor(
        name=name, ecosystem="go", version="1", summary=f"{name} summary",
        replaces=list(replaces), install=f"go get x/{name}", setup=[], entry=[],
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


def test_index_for_eight_modules_under_2000_words():
    ds = [desc(f"mod{i}", ["a phrase here", "another phrase here", "third phrase"]) for i in range(8)]
    pre = (Path(__file__).resolve().parents[2] / "standard" / "preamble.md").read_text()
    assert len(build_index(ds, pre).split()) < 2000
