from pathlib import Path

import pytest
import yaml

from artifactory.descriptor import DescriptorError, load_descriptor

VALID = {
    "name": "FooKit", "ecosystem": "godot-csharp", "version": "1.0.0",
    "summary": "Does foo things.", "replaces": ["foo handling"],
    "install": "git submodule add git@repo.billbert.co:artifactory/FooKit.git addons/FooKit",
    "setup": [], "entry": ["Foo.Run"], "liveness": "[FooKit] live",
    "docs": "README.md", "example": "README.md", "test": "dotnet test",
}


def make(tmp_path: Path, folder="FooKit", **over) -> Path:
    d = tmp_path / folder
    d.mkdir()
    data = {**VALID, **over}
    data = {k: v for k, v in data.items() if v is not None}
    (d / "module.yaml").write_text(yaml.safe_dump(data))
    return d


def problems(d):
    with pytest.raises(DescriptorError) as e:
        load_descriptor(d)
    return e.value.problems


def test_valid_descriptor_loads(tmp_path):
    d = load_descriptor(make(tmp_path))
    assert d.name == "FooKit"
    assert d.replaces == ["foo handling"]


def test_missing_fields_all_reported(tmp_path):
    p = "\n".join(problems(make(tmp_path, install=None, liveness=None)))
    assert "install" in p and "liveness" in p


def test_summary_must_be_one_line_under_100_chars(tmp_path):
    assert problems(make(tmp_path, summary="x" * 100))
    assert problems(make(tmp_path, folder="FooKit2", name="FooKit2", summary="a\nb"))


def test_replaces_needs_1_to_5_items_each_under_80_chars(tmp_path):
    assert problems(make(tmp_path, folder="A", name="A", replaces=[]))
    assert problems(make(tmp_path, folder="B", name="B", replaces=list("abcdef")))
    assert problems(make(tmp_path, folder="C", name="C", replaces=["x" * 80]))
    assert load_descriptor(make(tmp_path, folder="D", name="D", replaces=list("abcde")))


def test_godot_name_matches_folder(tmp_path):
    assert any("BarKit" in p for p in problems(make(tmp_path, name="BarKit")))


def test_godot_liveness_must_be_marker_line(tmp_path):
    assert any("liveness" in p for p in problems(make(tmp_path, liveness="prints [FooKit] live at startup")))
