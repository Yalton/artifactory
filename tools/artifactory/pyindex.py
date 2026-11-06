"""Build a local Python package source: a flat directory of wheels.

Trial sandboxes have no internet, so pip and uv inside them install only from
this directory. Kit wheels are built on the host with `uv build --wheel` (the
build backend comes from the host's uv cache or PyPI; the sandbox never builds
kits). Third-party wheels come in two ways: wheel files copied as they are, and
requirement specs (a test's `python_wheels`, plus standard_wheels(): pytest, and
the build backends so a project the model writes with uv_build or hatchling
builds offline) that
`download_wheels` resolves with pip on the host, for the sandbox interpreter.

The directory is a pip/uv "find-links" location: wheel files at the top
level, nothing else. `index_env` gives the variables that point both tools at
it and away from PyPI.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


SANDBOX_PYTHON = "/usr/bin/python3"  # the interpreter trials see; downloaded wheels must suit it


def uv_binary() -> Path:
    found = shutil.which("uv")
    if not found:
        raise RuntimeError("uv not found on PATH; it builds Python kit wheels")
    return Path(found).resolve()


def build_pyindex(kit_dirs: list[Path], out: Path, wheels: list[Path] = ()) -> list[Path]:
    """Build each kit's wheel into `out` and copy `wheels` there; return the wheel paths in `out`."""
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    built: list[Path] = []
    for d in kit_dirs:
        d = Path(d).resolve()
        if not (d / "pyproject.toml").is_file():
            raise ValueError(f"{d} has no pyproject.toml")
        with tempfile.TemporaryDirectory(prefix="pyindex-") as tmp:
            r = subprocess.run([str(uv_binary()), "build", "--wheel", "--no-progress", "--out-dir", tmp, str(d)],
                               capture_output=True, text=True,
                               env={**os.environ, "UV_NO_CONFIG": "1"})  # no stray uv.toml from the kit's parents
            if r.returncode != 0:
                raise RuntimeError(f"uv build {d} failed ({r.returncode}): {r.stderr.strip() or r.stdout.strip()}")
            made = sorted(Path(tmp).glob("*.whl"))
            if not made:
                raise RuntimeError(f"uv build {d} produced no wheel")
            built += [_place(w, out) for w in made]
    for w in wheels:
        w = Path(w)
        if w.suffix != ".whl" or not w.is_file():
            raise ValueError(f"{w} is not a wheel file")
        built.append(_place(w, out))
    return built


def standard_wheels() -> list[str]:
    """What every Python trial's index carries (each with its dependencies): pytest, which trials run
    offline, and the build backends, uv_build in the range `uv init` (this uv) pins and hatchling."""
    major, minor = _uv_version()[:2]
    return ["pytest", f"uv_build>={major}.{minor}.0,<{major}.{minor + 1}", "hatchling"]


def _uv_version() -> tuple[int, ...]:
    r = subprocess.run([str(uv_binary()), "--version"], capture_output=True, text=True, check=True)
    return tuple(int(x) for x in r.stdout.split()[1].split(".")[:3])


def download_wheels(specs: list[str], out: Path) -> list[Path]:
    """Resolve `specs` and their dependencies to wheels in `out`; return the wheels it added.

    Host side only (needs PyPI or the pip cache). pip runs on SANDBOX_PYTHON in a throwaway uv
    environment, so platform and Python tags fit the sandbox. Only wheels are taken: the sandbox
    cannot fetch an sdist's build requirements.
    """
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not specs:
        return []
    before = set(out.glob("*.whl"))
    with tempfile.TemporaryDirectory(prefix="pywheels-") as tmp:
        argv = [str(uv_binary()), "run", "--no-project", "--isolated", "--python", SANDBOX_PYTHON, "--with", "pip",
                "--", "python", "-m", "pip", "download", "--quiet", "--disable-pip-version-check",
                "--only-binary=:all:", "--dest", tmp, *specs]
        r = subprocess.run(argv, capture_output=True, text=True, env={**os.environ, "UV_NO_CONFIG": "1"})
        if r.returncode != 0:
            raise RuntimeError(f"pip download {' '.join(specs)} failed ({r.returncode}): "
                               f"{r.stderr.strip() or r.stdout.strip()}")
        for w in sorted(Path(tmp).glob("*.whl")):
            _place(w, out)
    return sorted(set(out.glob("*.whl")) - before)


def _place(wheel: Path, out: Path) -> Path:
    dest = out / wheel.name
    if dest.exists() and dest.read_bytes() != wheel.read_bytes():
        raise ValueError(f"two different wheels named {wheel.name}")
    shutil.copyfile(wheel, dest)
    return dest


def index_env(index: Path) -> dict[str, str]:
    """The minimal set, each checked inside the sandbox:

    PIP_NO_INDEX    pip skips PyPI (and its self version check); without it pip retries PyPI for ~10 s first.
    PIP_FIND_LINKS  pip's only package source.
    UV_FIND_LINKS   uv's package source. uv has no environment form of --no-index, so:
    UV_OFFLINE      uv skips PyPI (and Python downloads); without it uv fails on PyPI. Find-links still serve.
    """
    index = str(Path(index).resolve())
    return {"PIP_NO_INDEX": "1", "PIP_FIND_LINKS": index, "UV_FIND_LINKS": index, "UV_OFFLINE": "1"}
