# Python round 3: python-url-shortener

Run: `artifactory round tests/acceptance/python-url-shortener --round 3 --trials 5`, on Nov 7 from about 12:14 to 3:43 PM CST. Each trial had 45 minutes; the durations below come from each trial's `transcript.jsonl`. Kits: env-settings 0.1.0, json-kv 0.1.0 and http-runner 0.1.1. The standard was at 0430af9 (PR #32); the `-dirty` mark in `round.json` comes from untracked files in the main checkout, as in round 2. Results: `results/python-url-shortener/round-3/`. Round 2: `results/python-round-2/REPORT.md`.

**2 of 5 passed** (round 1: 0, round 2: 1). The bar is 4 of 5. One trial was an infrastructure loss.

| Trial | install | pinned | pip check | tests | app starts | installed | live | unmodified | no traceback | no dup | Ends |
|---|---|---|---|---|---|---|---|---|---|---|---|
| t1 | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | **pass**, 45 min, 3 resumes |
| t2 | . | . | . | . | . | . | . | . | . | Y | **infrastructure** (connection dropped after 3 resumes), 34 min |
| t3 | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | **pass**, 44 min, 1 resume |
| t4 | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | timeout, 44 min |
| t5 | . | Y | . | . | . | . | . | . | . | Y | timeout (transcript ends at 40 min) |

No trial wrote code a kit owns, and no trial logged a traceback. Round 2's two failure causes are gone.

## Causes

1. **Time is now the main limit (t4, and nearly t1 and t3).** Every trial that got far used 44–45 minutes by its transcript. t5's transcript stops 5 minutes short of the limit, though the harness recorded a timeout; the last part of its session was not logged. t4 passed every check and was still running its before-finishing steps when the limit hit, the same as round 2's t4. Most of the time is the model writing, not commands running: tool calls took 4–13 minutes of each trial. t4 lost about 6 minutes to its own live-server tests hanging, then rewrote them. The limit is the same 45 minutes the Go rounds used, so it was not changed.
2. **An incomplete build-system block (t5).** t5's `pyproject.toml` had `requires = ["uv_build"]` but no `build-backend`, so the installer fell back to setuptools, which the wheel directory does not carry: `ModuleNotFoundError: No module named 'setuptools'`. It also carried a `[tool.hatch.build.targets.wheel]` table, a sign it mixed the two backends. The notes said to use `uv_build` "exactly as `uv init` writes it" but did not show the block.
3. **The model connection dropped (t2).** After 3 resumes the connection to the model server reset (`ECONNRESET`), with only `MODULES.md` written. It is counted as an infrastructure loss and was not re-run: one more trial under round 3's notes could not have lifted the round to 4 of 5.

## Changes for round 4

- The consumer notes show the full `[build-system]` block with both `requires` and `build-backend`, and say that without `build-backend` installers fall back to setuptools. The block was checked to install offline from the wheel directory.
