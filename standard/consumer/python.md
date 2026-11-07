### Reading a module

After installing, read each module's README before coding. Its Wiring section is the snippet to follow:

```
.venv/bin/python -c "from importlib.resources import files; print(files('<import_name>').joinpath('README.md').read_text())"
```

When `PIP_FIND_LINKS` or `UV_FIND_LINKS` is set (offline use), install each module as `<name>==<version>` with `uv add` or `pip install`. They read the setting from the environment. Never use the git URL then.

Never write code a module already does, not even as a fallback or a default. If a module answers `/healthz`, add no `/healthz` route. If a module reads `os.environ` by default, do not pass it `os.environ`; pass a mapping only to give it other values, as a test does.

### Before finishing

Pin each module as `<name>==<version>` in `requirements.txt` (or `pyproject.toml` with a committed `uv.lock`). Build a clean environment from the pins, check it, and run the tests. Confirm none of them prints an error:

```
uv venv --clear && uv pip install -r requirements.txt pytest
uv pip check && .venv/bin/python -m pytest -q
```

Add `.` to the install only if the app has a `pyproject.toml`. Its `[build-system]` must name a backend the wheel directory carries, with both keys. `uv init --package` writes this block, with a version range on `uv_build`, which also works:

```toml
[build-system]
requires = ["uv_build"]
build-backend = "uv_build"
```

`hatchling` (with `build-backend = "hatchling.build"`) also works. Without `build-backend`, installers fall back to setuptools, which is not there; `backend-path` never works offline. Or give the app no `[build-system]`, keep only `requirements.txt`, and run `python -m <app>` from the project root. With pip: `python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest && .venv/bin/pip check`.

Run the app from `.venv/bin/python`, not `uv run`, so nothing re-locks over the network. Unbuffered output keeps the markers when the app is killed. A server never exits on its own, so start it in the background, wait for `/healthz` to answer 200, then stop it:

```
PYTHONUNBUFFERED=1 .venv/bin/python -m <app> > /tmp/app.log 2>&1 & pid=$!
for i in $(seq 20); do curl -sf -o /dev/null localhost:8080/healthz && echo healthy && break; sleep 0.5; done
kill $pid
```

A script or CLI exits on its own: run it with `PYTHONUNBUFFERED=1 .venv/bin/python -m <app> > /tmp/app.log 2>&1`.

Then check the log. The marker count must be 1 for each installed module, and there must be no traceback:

```
grep -cxF '[<name>] live' /tmp/app.log
! grep -q Traceback /tmp/app.log
```
