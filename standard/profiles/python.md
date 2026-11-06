# Python profile (ecosystem `python`)

Applies Stitchability Standard Draft 0.1.

| Rule | In this profile |
|---|---|
| 1 Descriptor | `module.yaml` at the project root, next to `pyproject.toml`. |
| 2 Docs travel | README and `module.yaml` are package data inside the import package, so every install brings them. |
| 3 Unmodified | Each module's installed files match the hashes in its dist-info `RECORD`. No module is an editable or local-path install. |
| 4 Live | The module prints its liveness marker on import or app start. |
| 5 Example | An `example/` directory with a runnable `main.py`. |
| 6 Setup | Prefer zero steps. Any required step must print the liveness marker. |
| 7 Index | Generated from `module.yaml` files. |
| 8 Preamble | Prepended to the index. |

## Packaging

A module is a pip-installable package with a `pyproject.toml` (PEP 621 metadata, `src/` layout). The distribution name is the descriptor `name`: lowercase letters, digits and single hyphens. The import name is the package under `src/`, with underscores. The first released version is `0.1.0`, and `requires-python` is `>=3.11`.

The build backend is `uv_build` (the `uv init` default). It packs everything under `src/<import_name>/`, so `module.yaml` and `README.md` stay real files at the project root and the package holds relative symlinks to them:

```
ln -s ../../module.yaml src/<import_name>/module.yaml
ln -s ../../README.md src/<import_name>/README.md
```

```toml
[build-system]
requires = ["uv_build>=0.12,<0.13"]
build-backend = "uv_build"
```

With hatchling instead, use `[tool.hatch.build.targets.wheel.force-include]` mapping `"module.yaml" = "<import_name>/module.yaml"` and the same for `README.md`.

A consumer reads them with `importlib.resources.files("<import_name>") / "module.yaml"`.

The import package is a regular top-level package (with `__init__.py`). Namespace packages are not supported.

Dependencies are bounded ranges in `pyproject.toml` (`httpx>=0.27,<1`). A module never pins its own dependencies exactly.

## Where modules live

Python modules live as repositories in the Forgejo org `artifactory`, one repo per module, with the version as the git tag `v<version>`. The tag matches `version` in `pyproject.toml` and `module.yaml`. Publish with `artifactory publish <folder> --provider forgejo:repo.billbert.co/artifactory`.

## Install

```
pip install "<name> @ git+ssh://git@repo.billbert.co/artifactory/<name>.git@v<version>"
```

With uv:

```
uv add "<name> @ git+ssh://git@repo.billbert.co/artifactory/<name>.git@v<version>"
```

The descriptor `install` is this git line, for online use. Install into a virtual environment, never the system Python.

When `PIP_FIND_LINKS` or `UV_FIND_LINKS` is set (offline use), install `<name>==<version>` and never use the git URL. Plain `pip install` and `uv add` read the setting from the environment:

```
pip install "<name>==<version>"
uv add "<name>==<version>"
```

## Pinning

The consumer pins every module to an exact tag or `==` version. A branch, a bare commit or an unpinned name is not allowed. Commit `uv.lock` or a pinned `requirements.txt`.

## Descriptor fields

`name` is the distribution name, for example `rate-limiter`. The import name is not a separate field. Give it in `entry`, as `rate_limiter.Limiter`, so the consumer sees both names. `test` installs the module into a throwaway environment and runs its tests, since `artifactory publish` runs it in the source folder: `uv run --isolated --no-project --with . --with pytest pytest -q -p no:cacheprovider`.

## Liveness

"Live" means the running app imported the module and started it through its real entry path. Importing it from tests only does not count.

The module prints exactly `[<name>] live`, once per process, with `print(..., flush=True)` to stdout, on import or on its start call (say which in `setup`). A skipped start shows up as a missing marker.

The descriptor `liveness` value is the marker line itself, with no other words.

## Unmodified

For each module, compare its installed files with the hashes in its dist-info `RECORD`, and reject an editable or local-directory install of it (`direct_url.json` with `dir_info`). The checker does this with `importlib.metadata`. Other distributions, including the project itself, may be editable.

## Consumer notes

`standard/consumer/python.md` holds the consumer-facing project notes (verification commands). Every index for this ecosystem includes it after the preamble.
