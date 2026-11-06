### Reading a module

After installing, read each module's README before coding. Its Wiring section is the snippet to follow:

```
python -c "import importlib.metadata as m; print(m.distribution('<name>').read_text('README.md'))"
```

### Before finishing

Install in a clean virtual environment, check the dependencies, and run the tests. Confirm none of them prints an error:

```
uv venv && uv pip install -e . pytest
uv pip check && uv run pytest -q
```

The same with pip: `python -m venv .venv && .venv/bin/pip install -e . pytest && .venv/bin/pip check && .venv/bin/pytest -q`.

Start the app and capture its output. A server never exits on its own, so start it in the background, wait for `/healthz` to answer 200, then stop it:

```
uv run python -m <app> > /tmp/app.log 2>&1 & pid=$!
for i in $(seq 20); do curl -sf -o /dev/null localhost:8080/healthz && echo healthy && break; sleep 0.5; done
kill $pid
```

A script or CLI exits on its own: run it with `uv run python -m <app> > /tmp/app.log 2>&1`.

Then check the log:

```
grep -x '\[<name>\] live' /tmp/app.log
grep -c Traceback /tmp/app.log
```

Each installed module's marker must appear once. The traceback count must be 0.
