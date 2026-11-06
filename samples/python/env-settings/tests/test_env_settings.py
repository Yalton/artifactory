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
