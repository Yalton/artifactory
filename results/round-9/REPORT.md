# Round 9 review

`godot-capsule-room` with the product CLI and arc (`--product --arc`): **2 of 5** passed, by the checker and by screenshot. Rounds 7 and 8 also scored 2 of 5. The bar is not met.

The setup is round 8's plus arc:
- the trial project carried arc's registry of the 8 installed kits, its opencode hook and the AGENTS.md guidance from `artifactory index --arc on`;
- the checker ran `arc_gate`.

The checker, the consumer notes (MoveCheck included), the prompt and the time limit (2 h) are unchanged from round 7.

## Lost trials

Two trials (original t2 and t3) lost their model connection about 12:03 and 12:25 PM CST. After 3 resumes each, the harness recorded them as infrastructure failures. The server answered its health check afterwards. As in round 7, they do not count. Two replacement trials ran afterwards (`--round 9 --trials 2`, same setup) and became t2 and t3.

- The originals are kept as `trial-2-infra` and `trial-3-infra`.
- The replacement run's `round.json` is kept as `round-rerun.json`.
- The replacement transcripts name their working directories `trial-1` and `trial-2`, because they were run under those names and renamed afterwards.

## Results

Screenshots: `results/round-9/trial-N.png`, 1600×900, main scene after 2 s, for the trials that build.

| Trial | Result | Resumes | Screenshot | Cause |
|---|---|---|---|---|
| t1 | timeout (2 h) | 0 | none (no build) | `Bootstrap.cs(19,69)`: called `SceneTree.IsNodeInGroup`, which does not exist (CS1061). |
| t2 (rerun) | timeout (2 h) | 0 | flat dark grey, nothing visible | A `NullReferenceException` at runtime, the camera blocked, and no floor or walls around the player. It ran `dotnet build` 31 times. |
| t3 (rerun) | pass | 0 | capsule in the middle of a walled room, seen from above | Pass. |
| t4 | timeout (2 h) | 1 | floor and walls, no capsule | Only `room_present` failed: no floor below the player and no wall on any side. The room exists, but the player is not in it. |
| t5 | pass | 0 | capsule in a walled room | Pass. |

Every trial installed all 8 kits with `artifactory install`; no trial used `git submodule add`. Every trial that finished building left the kits unmodified and had no duplication.

The original t2 broke on the same dropped `)` in MoveCheck's `RoomMissing` line (`MoveCheck.cs(76,80)`, CS1026) before its connection dropped.

## arc

| | t1 | t2 | t3 | t4 | t5 |
|---|---|---|---|---|---|
| hook live | yes | yes | yes | yes | yes |
| denials | 0 | 0 | 0 | 0 | 0 |
| `arc_gate` | pass | pass | pass | pass | pass |

arc ran in every trial and never had to step in: no write was denied and the gate found nothing. Some trials ran `arc brief` or `arc version` on their own after reading AGENTS.md.

## Findings

1. **arc neither helped nor hurt.** The pass rate matches rounds 7 and 8. The model never tried to write into a kit or copy one, so arc's denials and gate had nothing to catch. Rounds 1–8 already showed this model leaves installed kits alone when the index tells it to install them. On this task, arc is a safety net that was not needed.
2. **The CLI is now the install path.** All five trials used `artifactory install`, against four of five in round 8.
3. **Failures stay in game code, not modules.** Across rounds 7–9 (15 counted trials), no trial failed on module installation, liveness or modification. The 9 failures were build errors in the model's own code (including 4 MoveCheck copy errors across 3 rounds), scene mistakes (no room around the player, camera blocked) and time.
4. **Connection drops can still lose trials.** Two in a row exhausted 3 resumes each. The harness reported them correctly as infrastructure failures.

## Next

- Artifactory-ksz (copy-safe MoveCheck) is no longer held back for comparability.
- The roadmap experiment (Artifactory-5dx.2) runs Lantern Keep with this setup.
