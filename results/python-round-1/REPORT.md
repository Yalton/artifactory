# Python round 1: python-url-shortener

Run: `artifactory round tests/acceptance/python-url-shortener --round 1 --trials 5`, on Nov 7 from about 5:20 to 8:57 AM CST. Each trial had 45 minutes. Kits: env-settings, json-kv and http-runner, all 0.1.0. Results: `results/python-url-shortener/round-1/`.

**0 of 5 passed.**

| Trial | install | pinned | pip check | tests | app starts | installed | live | unmodified | no traceback | no dup | Ends |
|---|---|---|---|---|---|---|---|---|---|---|---|
| t1 | . | Y | . | . | . | . | . | . | . | . | finished |
| t2 | Y | Y | Y | Y | Y | Y | Y | Y | Y | . | timeout |
| t3 | Y | Y | Y | . | Y | Y | Y | Y | Y | . | timeout |
| t4 | Y | Y | Y | . | Y | Y | Y | Y | Y | . | timeout |
| t5 | . | Y | . | . | . | . | . | . | . | . | finished |

When the app installed, the kits were used as intended: pinned, installed, unmodified and live in all three trials that installed.

## Causes, ranked by trials sunk

1. **The app handled `/healthz` itself (4 trials, a real failure).** http-runner answers `GET /healthz` before the handler sees the request, and its index entry lists "a /healthz endpoint" under "Use instead of writing". Four trials still routed it, for example `if path == "/healthz":` in t2's `shortener/handler.py:54`. t3 used `health_check=` correctly; its hit was a docstring (cause 2). t2 failed only on this.
2. **The duplication check matched prose (checker bug, every trial).** `os.environ` and `/healthz` in comments and docstrings were flagged, for example t2's `config.py` docstring "instead of us touching os.environ ourselves". With prose ignored, t3 has no duplication left. It still fails on tests.
3. **The build backend did not exist offline (t1, t5).** t1 declared hatchling with `backend-path = ["_vendor"]`. t5 used setuptools, which the wheel directory does not carry. Both installs failed.
4. **Tests failed or hung (t3, t4).** t3's server test errored, and t4's pytest run timed out after 300 s. Both trials, and t2, used the full 45 minutes.

## Changes for round 2 (PR #31)

- The duplication check skips Python comments and docstrings, with lines split as the tokenizer splits them.
- The consumer notes name the backends the wheel directory carries (uv_build, hatchling) and rule out setuptools and `backend-path`.
- http-runner 0.1.1 says in its summary that it answers `GET /healthz` for the handler, and lists "a /healthz endpoint or health route in your handler" under replaces.

Round 2: `results/python-round-2/REPORT.md`.
