# Python profile (ecosystem `python`)

Applies Stitchability Standard Draft 0.2.

| Rule | In this profile |
|---|---|
| 1 Descriptor | `module.yaml` at the project root, next to `pyproject.toml`. |
| 2 Docs travel | README and `module.yaml` are in the sdist, so the git install brings them. |
| 3 Unmodified | The package is installed non-editable from a tag. The consumer has no copy of its source. |
| 4 Live | The module prints its liveness marker on import or app start. |
| 5 Example | An `example/` directory with a runnable `main.py`. |
| 6 Setup | Prefer zero steps. Any required step must print the liveness marker. |
| 7 Index | Generated from `module.yaml` files. |
| 8 Preamble | Prepended to the index. |

## Packaging

A module is a pip-installable package with a `pyproject.toml` (PEP 621 metadata, `src/` layout). The distribution name is the descriptor `name`, lowercase with hyphens. The import name is the package under `src/`, with underscores. The first released version is `0.1.0`, and `requires-python` is `>=3.11`.

Dependencies are bounded ranges in `pyproject.toml` (`httpx>=0.27,<1`). A module never pins its own dependencies exactly.

## Where modules live

Python modules live as repositories in the Forgejo org `artifactory`, one repo per module, with the version as the git tag `v<version>`. The tag matches `version` in `pyproject.toml` and `module.yaml`.

## Install

```
pip install "<name> @ git+ssh://git@repo.billbert.co/artifactory/<name>.git@v<version>"
```

With uv:

```
uv add "<name> @ git+ssh://git@repo.billbert.co/artifactory/<name>.git@v<version>"
```

The descriptor `install` is the pip line. A local index works too: `pip install --index-url <url> <name>==<version>`. Install into a virtual environment, never the system Python.

## Pinning

The consumer pins every module to an exact tag or `==` version. A branch, a bare commit or an unpinned name is not allowed. Commit `uv.lock` or a pinned `requirements.txt`.

## Descriptor fields

`name` is the distribution name, for example `rate-limiter`. The import name is not a separate field. Give it in `entry`, as `rate_limiter.Limiter`, so the consumer sees both names. `test` is `pytest`.

## Liveness

"Live" means the running app imported the module and started it through its real entry path. Importing it from tests only does not count.

The module prints exactly `[<name>] live`, once per process, with plain `print` to stdout, on import or on its start call (say which in `setup`). A skipped start shows up as a missing marker.

The descriptor `liveness` value is the marker line itself, with no other words.

## Unmodified

Run `pip show -f <name>` and `pip check`. Reject an editable install (`pip list --editable`) and any `file:` or path requirement for a module.

## Consumer notes

`standard/consumer/python.md` holds the consumer-facing project notes (verification commands). Every index for this ecosystem includes it after the preamble.
