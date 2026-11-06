from dataclasses import dataclass, field
from pathlib import Path

import pytest

import env_settings
from env_settings import SettingsError, load


@dataclass
class Settings:
    port: int = 8080
    name: str = "app"
    debug: bool = False
    ratio: float = 0.5
    data: Path = Path("data.json")
    tags: list = field(default_factory=list)


def test_defaults_when_nothing_is_set():
    assert load(Settings, "APP", environ={}) == Settings()


def test_env_beats_file_beats_default(tmp_path):
    f = tmp_path / "app.env"
    f.write_text("# comment\n\nPORT = 9000\nNAME=from-file\n")
    s = load(Settings, "APP", file=f, environ={"APP_NAME": "from-env", "APP_DEBUG": "yes"})
    assert (s.port, s.name, s.debug) == (9000, "from-env", True)


def test_types_convert():
    s = load(Settings, "APP", environ={"APP_RATIO": "1.25", "APP_DATA": "/tmp/x.json", "APP_DEBUG": "off"})
    assert s.ratio == 1.25 and s.data == Path("/tmp/x.json") and s.debug is False


def test_missing_file_is_ignored(tmp_path):
    assert load(Settings, "APP", file=tmp_path / "nope.env", environ={}) == Settings()


def test_reads_os_environ_by_default(monkeypatch):
    monkeypatch.setenv("APP_PORT", "1234")
    assert load(Settings, "APP").port == 1234


def test_required_field_without_value_raises():
    @dataclass
    class Need:
        token: str

    with pytest.raises(SettingsError, match="APP_TOKEN is not set"):
        load(Need, "APP", environ={})
    assert load(Need, "APP", environ={"APP_TOKEN": "t"}).token == "t"


@pytest.mark.parametrize("var,value", [("APP_PORT", "eighty"), ("APP_DEBUG", "maybe"), ("APP_RATIO", "x")])
def test_bad_value_names_the_variable(var, value):
    with pytest.raises(SettingsError, match=var):
        load(Settings, "APP", environ={var: value})


def test_malformed_file_line_raises(tmp_path):
    f = tmp_path / "bad.env"
    f.write_text("PORT 9000\n")
    with pytest.raises(SettingsError, match="want KEY=value"):
        load(Settings, "APP", file=f, environ={})


def test_unsupported_type_raises():
    with pytest.raises(SettingsError, match="unsupported field type"):
        load(Settings, "APP", environ={"APP_TAGS": "a,b"})


def test_rejects_non_dataclass():
    with pytest.raises(TypeError):
        load(dict, "APP", environ={})


def test_docs_travel_as_package_data():
    from importlib.resources import files
    pkg = files("env_settings")
    assert "name: env-settings" in (pkg / "module.yaml").read_text()
    assert "# env-settings" in (pkg / "README.md").read_text()
    assert env_settings.__name__ == "env_settings"


@dataclass
class Opt:
    port: int | None = 8080
    name: "str | None" = "x"
    ratio: float | None = None


def test_optional_fields_unwrap_and_empty_is_none():
    from typing import Optional

    @dataclass
    class Old:
        port: Optional[int] = None

    s = load(Opt, "APP", environ={"APP_PORT": "", "APP_NAME": "  ", "APP_RATIO": "2.5"})
    assert (s.port, s.name, s.ratio) == (None, None, 2.5)
    assert load(Opt, "APP", environ={"APP_PORT": "81"}).port == 81
    assert load(Old, "APP", environ={"APP_PORT": "7"}).port == 7
    assert load(Old, "APP", environ={"APP_PORT": ""}).port is None


def test_empty_value_for_a_non_optional_int_raises():
    with pytest.raises(SettingsError, match="APP_PORT"):
        load(Settings, "APP", environ={"APP_PORT": ""})


@pytest.mark.parametrize("var,value", [("APP_PORT", "1_000"), ("APP_PORT", "1.0"), ("APP_RATIO", "nan"),
                                       ("APP_RATIO", "inf"), ("APP_RATIO", "-Infinity"), ("APP_RATIO", "1_0.5")])
def test_numbers_are_strict(var, value):
    with pytest.raises(SettingsError, match=var):
        load(Settings, "APP", environ={var: value})


def test_numbers_accept_plain_forms():
    s = load(Settings, "APP", environ={"APP_PORT": "+90", "APP_RATIO": "-1.5e3"})
    assert s.port == 90 and s.ratio == -1500.0
    assert load(Settings, "APP", environ={"APP_RATIO": ".5"}).ratio == 0.5


def test_file_export_prefix_quotes_and_no_inline_comments(tmp_path):
    f = tmp_path / "app.env"
    f.write_text("export PORT=9001\nNAME=\"quoted name\"\nDATA='/x/y.json'\n")
    s = load(Settings, "APP", file=f, environ={})
    assert (s.port, s.name, s.data) == (9001, "quoted name", Path("/x/y.json"))
    f.write_text("NAME=\"half'\n")
    assert load(Settings, "APP", file=f, environ={}).name == "\"half'"  # mismatched quotes stay
    f.write_text("NAME=web # comment\n")
    assert load(Settings, "APP", file=f, environ={}).name == "web # comment"


def test_unreadable_file_raises_settings_error(tmp_path):
    bad = tmp_path / "bad.env"
    bad.write_bytes(b"NAME=\xff\xfe\n")
    with pytest.raises(SettingsError, match="cannot read"):
        load(Settings, "APP", file=bad, environ={})
    with pytest.raises(SettingsError, match="cannot read"):
        load(Settings, "APP", file=tmp_path, environ={})  # a directory
