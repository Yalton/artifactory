"""Fill a dataclass from environment variables, an optional KEY=value file and field defaults."""
from __future__ import annotations

import dataclasses
import os
import re
import types
import typing
from collections.abc import Mapping
from pathlib import Path
from typing import TypeVar

print("[env-settings] live", flush=True)

__all__ = ["SettingsError", "load"]

T = TypeVar("T")

_INT = re.compile(r"[+-]?[0-9]+")
_FLOAT = re.compile(r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?")
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class SettingsError(ValueError):
    """A setting is missing, does not convert to its field type, or the file is malformed."""


def load(cls: type[T], prefix: str, file: str | os.PathLike | None = None,
         environ: Mapping[str, str] | None = None) -> T:
    """Return `cls(...)` with each field from `<PREFIX>_<FIELD>`, else `<FIELD>=` in `file`, else its default.

    `cls` is a dataclass. Field names are upper-cased to form the variable names. `file` may be None or
    missing. `environ` defaults to `os.environ`."""
    if not (isinstance(cls, type) and dataclasses.is_dataclass(cls)):
        raise TypeError("env_settings.load: cls must be a dataclass type")
    env = os.environ if environ is None else environ
    from_file = _read_file(file)
    hints = typing.get_type_hints(cls)
    values = {}
    for f in dataclasses.fields(cls):
        if not f.init:
            continue
        key = f.name.upper()
        var = f"{prefix}_{key}" if prefix else key
        if var in env:
            raw = env[var]
        elif key in from_file:
            raw = from_file[key]
        elif f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING:
            continue  # the dataclass applies its own default
        else:
            raise SettingsError(f"{var} is not set and {cls.__name__}.{f.name} has no default")
        values[f.name] = _convert(raw, hints.get(f.name, str), var)
    return cls(**values)


def _read_file(file: str | os.PathLike | None) -> dict[str, str]:
    if file is None or str(file) == "":
        return {}
    try:
        text = Path(file).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as e:
        raise SettingsError(f"{file}: cannot read: {e}") from e
    out = {}
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep or not key.strip():
            raise SettingsError(f"{file}:{n}: want KEY=value, got {line!r}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip().upper()] = value
    return out


def _optional(typ: object) -> tuple[object, bool]:
    """(inner type, True) for `X | None` or Optional[X]; (typ, False) otherwise."""
    if typing.get_origin(typ) in (typing.Union, types.UnionType):
        args = typing.get_args(typ)
        rest = [a for a in args if a is not type(None)]
        if len(rest) == 1 and len(rest) < len(args):
            return rest[0], True
    return typ, False


def _convert(raw: str, typ: object, var: str) -> object:
    typ, optional = _optional(typ)
    if optional and raw.strip() == "":
        return None
    try:
        if typ is str:
            return raw
        if typ is bool:
            low = raw.strip().lower()
            if low in _TRUE:
                return True
            if low in _FALSE:
                return False
            raise ValueError(f"not a boolean: {raw!r}")
        if typ is int:
            if not _INT.fullmatch(raw.strip()):
                raise ValueError(f"not an integer: {raw!r}")
            return int(raw.strip())
        if typ is float:
            if not _FLOAT.fullmatch(raw.strip()):
                raise ValueError(f"not a finite decimal number: {raw!r}")
            return float(raw.strip())
        if typ is Path:
            return Path(raw)
    except ValueError as e:
        raise SettingsError(f"{var}: {e}") from None
    raise SettingsError(f"{var}: unsupported field type {typ!r}")
