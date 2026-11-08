# Python round 4: python-url-shortener

Run: `artifactory round tests/acceptance/python-url-shortener --round 4 --trials 5`, on Nov 7 from about 3:52 to 7:11 PM CST. Each trial had 45 minutes; the durations below come from each trial's `transcript.jsonl`. Kits: env-settings 0.1.0, json-kv 0.1.0 and http-runner 0.1.1. The standard was at f5e7ab4 (PR #33); the `-dirty` mark in `round.json` comes from untracked files in the main checkout. Results: `results/python-url-shortener/round-4/`. Round 3: `results/python-round-3/REPORT.md`.

**2 of 5 passed** (rounds 1–3: 0, 1, 2). The bar is 4 of 5.

| Trial | install | pinned | pip check | tests | app starts | installed | live | unmodified | no traceback | no dup | Ends |
|---|---|---|---|---|---|---|---|---|---|---|---|
| t1 | Y | Y | Y | . | Y | Y | (.) | Y | Y | Y | timeout, 45 min |
| t2 | Y | Y | Y | . | Y | Y | Y | Y | Y | . | timeout, 39 min, 1 resume |
| t3 | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | **pass**, 29 min |
| t4 | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | **pass**, 37 min |
| t5 | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | timeout, 42 min |

(.) marks a failure the checker caused (cause 3). Every trial installed; the round 3 build-system failure did not recur.

## Causes

1. **Trials that were done kept working (t5).** t5 passed every check and timed out anyway. Its last minutes went to running the before-finishing steps again in a fresh environment, cleaning `/tmp` and chasing a marker count from its own grep. This is the third all-green timeout (round 2 t4, round 3 t4, round 4 t5). The notes never said to stop once the checks pass.
2. **Tests used `HTTPConnection` as a context manager (t1).** `with http.client.HTTPConnection(...)` raises `TypeError: ... does not support the context manager protocol`, so t1's server tests failed. Round 3's t4 lost about 6 minutes to the same mistake before rewriting its tests.
3. **The live check matched marker text in comments (t1, checker bug).** t1's tests import each kit with a comment naming its marker, for example `from shortener.store import LinkStore  # noqa: E402  (prints [json-kv] live once)` in `tests/conftest.py`. The check found 5 such comments across `tests/conftest.py`, `tests/test_settings.py`, `tests/test_store.py` and `tests/test_server.py`. The check that no project file prints a marker on a kit's behalf searched comments and docstrings too. t1 would still have failed on cause 2.
4. **t2 wrote no tests and wrapped the runner in its own `serve_forever`.** `pytest collected no tests`: there is no `tests/` directory. Its `ShortenerServer.serve_forever` method only calls `http_runner.run`, but both the method (`src/shortener/server.py:67`) and its call (`src/shortener/app.py:12`) match http-runner's duplication pattern `serve_forever\(`.

## Changes for round 5

- The consumer notes say to stop once the before-finishing checks pass, and that `HTTPConnection` is not a context manager: close it in a `finally`, with a `timeout=` on every connection.
- The live check searches only code for marker text, blanking comments and docstrings as the duplication check does (`python_code_lines` in `tools/artifactory/checks/duplication.py`). A marker in a string assigned to a name is still caught, and so is a docstring in any file whose code reads `__doc__`.
