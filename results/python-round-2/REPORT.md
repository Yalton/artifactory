# Python round 2: python-url-shortener

Run: `artifactory round tests/acceptance/python-url-shortener --round 2 --trials 5`, on Nov 7 from about 9:13 to 11:56 AM CST. Each trial had 45 minutes; the durations below come from each trial's `transcript.jsonl`. Kits: env-settings 0.1.0, json-kv 0.1.0 and http-runner 0.1.1. The standard was at 901be48 (PR #31); the `-dirty` mark in `round.json` comes from untracked files in the main checkout, not from changes to the standard. Results: `results/python-url-shortener/round-2/`. Round 1: `results/python-round-1/REPORT.md`.

**1 of 5 passed** (round 1: 0 of 5). The bar is 4 of 5.

| Trial | install | pinned | pip check | tests | app starts | installed | live | unmodified | no traceback | no dup | Ends |
|---|---|---|---|---|---|---|---|---|---|---|---|
| t1 | Y | Y | Y | Y | Y | Y | Y | Y | Y | . | finished, 33 min |
| t2 | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | **pass**, 18 min |
| t3 | Y | Y | Y | . | Y | Y | Y | Y | (.) | Y | timeout, 1 resume |
| t4 | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | timeout |
| t5 | Y | Y | Y | Y | Y | Y | Y | Y | (.) | . | finished, 20 min, 1 resume |

(.) marks a failure the checker caused (cause 2). Every trial installed, and in every trial the kits were pinned, installed, unmodified and live. The round 1 build-backend failures are gone, and no trial was flagged for prose.

## Causes

1. **The app still wrote code a kit owns (t1, t5, real failures).** t1 routed `/healthz` in `shortener/server.py:28` with the comment "http_runner already answers /healthz; answer as a fallback". It knew and did it anyway. t5's `load_settings` passed `environ or os.environ` to `env_settings.load` (`shortener/config.py:38`), though the kit already defaults to `os.environ`. t1 failed on this alone; t5 also hit cause 2.
2. **The checker's health probe caused a traceback (t3, t5, checker bug).** The probe closed its connection without reading the response body. Against a server with `protocol_version = "HTTP/1.1"` (keep-alive), that close resets the connection, and `socketserver` logs `ConnectionResetError: [Errno 104] Connection reset by peer` with a traceback. Reproduced by hand against t5's app: 5 probes gave 3 tracebacks; reading the body first gave 0 in 20. The bug decided no result, since t3 also failed its tests and t5 also failed `no_duplication`.
3. **t3's own test fixture was broken.** `tests/conftest.py` calls `make_handler` without importing it, so the server thread dies and every test errors with "shortener server did not come up". The trial spent its 45 minutes and did not find it.
4. **t4 passed every check but did not stop in time.** It worked for the full 45 minutes and was still re-running its tests when the limit hit. A timeout fails the trial, as in the Go rounds.

## Changes for round 3

- The health probe reads the response body before closing (`tools/artifactory/checks/python.py`), and still returns the status if that read fails or times out. Tests probe a keep-alive server 30 times and a reply whose body never ends.
- The consumer notes say never to write code a module already does, not even as a fallback or a default, and name both round 2 cases: no `/healthz` route beside http-runner, and no `os.environ` passed to a module that reads it by default.
