# Python round 5: python-url-shortener

Run: `artifactory round tests/acceptance/python-url-shortener --round 5 --trials 5`, on Nov 7 from about 7:30 to 10:38 PM CST. Each trial had 45 minutes; the durations below come from each trial's `transcript.jsonl`. Kits: env-settings 0.1.0, json-kv 0.1.0 and http-runner 0.1.1. The standard was at 2b565b5 (PR #34); the `-dirty` mark in `round.json` comes from untracked files in the main checkout. Results: `results/python-url-shortener/round-5/`. Round 4: `results/python-round-4/REPORT.md`.

**5 of 5 passed. The bar of 4 of 5 is met.**

| Trial | All 10 checks | Ends |
|---|---|---|
| t1 | Y | pass, 42 min |
| t2 | Y | pass, 34 min |
| t3 | Y | pass, 41 min |
| t4 | Y | pass, 34 min |
| t5 | Y | pass, 36 min |

No trial needed a resume, and there were no infrastructure losses. Every trial finished on its own, 3 to 11 minutes before the limit. In round 4, three of five trials ran out of time.

## What changed across the five rounds

| Round | Passed | Changes made after it |
|---|---|---|
| 1 | 0/5 | The duplication check skips comments and docstrings; the notes name the offline build backends; http-runner 0.1.1 says it answers `/healthz` (PR #31) |
| 2 | 1/5 | The health probe reads the response body (a false traceback); the notes forbid copying kit code even as a fallback (PR #32) |
| 3 | 2/5 | The notes show the full `[build-system]` block (PR #33) |
| 4 | 2/5 | The notes say to stop once the checks pass and that `HTTPConnection` is not a context manager; the live check skips prose (PR #34) |
| 5 | 5/5 | none |

The kits never changed apart from http-runner's descriptor (0.1.0 to 0.1.1). Four of the changes fixed the checker:
- comments and docstrings flagged as duplication;
- the probe's connection reset;
- marker text in comments;
- the probe keeping its status when the read fails.

The rest changed the consumer notes. Round 5's gain over round 4 lines up with its main change: the trials stopped once their checks passed, and none timed out.

## Caveat

Five trials is a small sample. Rounds 3 and 4 passed 2 of 5 each with mostly the same notes, so part of round 5's result may be variance. The bar the design set is met, and the design's rule ends the rounds here.
