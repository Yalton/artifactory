# Stitchability standard: results of sub-project 1

Date: 2026-11-01. Standard: `standard/STANDARD.md`, now **Draft 0.2**. It is not locked at 1.0, for the reasons under Verdict.

## Question

Can a weak local model (Ornith 35B on llama.cpp, run through opencode in a sandbox with a private filesystem; network egress was not blocked, see caveat 5) build a working program mostly by installing and wiring existing modules, if those modules follow a written standard? The model should handle the plumbing; the kits supply the sink and the toilet.

Two acceptance tests, 5 trials per round, pass bar 4 of 5. Time limit per trial: 45 min for Go, 2 h for Godot.

- `go-url-shortener`: a Go HTTP service using 4 sample modules (config, httpserver, kvstore, shortid).
- `godot-capsule-room`: a Godot 4.7 C# room with a capsule player that moves with WASD, wired to 8 foundation kits (InputRemap, Settings, Cursor, DebugLog, DevConsole, Crash, Transition, RunSave).

## Results by round

| Round | Go | Godot | Main change before the round |
|---|---|---|---|
| Baseline | not run | 0/5 | Old kits, full 34-kit catalog, no standard |
| 1 | 3/5 | 0/5 | Descriptors, MODULES.md index, preamble, liveness markers, unmodified/duplication checks |
| 2 | 2/5 | 1/5 | Exact `[<Kit>] live` markers; complete README Wiring classes; RunSaveKit `.uid` fix |
| 3 | 5/5 | 1/5 | httpserver v0.2.0 (`Run` handles signals); consumer notes per ecosystem shown in MODULES.md; stop rule |
| 4 | 5/5 | 5/5 | MoveCheck self-check; Godot pitfalls list; DevConsoleKit sets up its own input action; `Setup:` lines in the index |
| 5 | (5/5 stands) | 1/5 | Checker requires a camera that sees the player (`player_visible`) |
| 6 | (5/5 stands) | 5/5 by checker, 3/5 by screenshot | `player_visible` counts first person, needs a drawn mesh, tests a 16:9 frustum; MoveCheck reports the reason |
| 7 | (5/5 stands) | 2/5 (checker and screenshot agree) | Drawn walls block sight; `room_present` requires a floor and walls; the harness resumes after a dropped model connection |
| 8 | (5/5 stands) | 2/5 (checker and screenshot agree) | Product CLI in the trial: `artifactory.yaml`, `artifactory install`, product MODULES.md (arc off) |
| 9 | (5/5 stands) | 2/5 (checker and screenshot agree; 2 infrastructure losses re-run) | Round 8 plus arc (registry, hook, gate): 0 denials, gate clean in all 5 |

Per-round analyses: `results/godot-capsule-room/baseline/REPORT.md`, `results/round-{1..9}/REPORT.md`.

## Verdict

- **Go: met.** The bar was met in rounds 3 and 4 (5/5 both times). Every failure in rounds 1–2 traced to a module or its docs, and each was fixed in the module. This is the standard working as designed.
- **Godot: not met by eye.** Round 4 passed 5/5, but a screenshot audit showed all five games as a plain grey window: none of them added a camera. Once a camera check was added, round 5 passed 1/5, with four trials at the 2 h limit. Round 6 reworked that check (first person, drawn mesh, 16:9) and passed 5/5 by the checker, all within 28–87 min. The screenshots show 3/5: t2's player is hidden by a wall that is drawn but has no physics body, which the checker's ray cannot see, and t3 has no room at all, which nothing checks. Bar is 4/5.
- **No kit-caused Godot failures after round 3.** In round 3, t2 failed on a skipped DevConsoleKit setup step, which round 4 removed. From round 4 onward, no Godot failure traced to a kit. Every trial installed all 8 kits as submodules, left them unmodified, and printed all 8 liveness markers. The remaining failures are the model's own game code: walls, movement, camera.

So the standard is not marked 1.0. In the plan's terms, both tests met the bar by the checker in rounds 4 and 6, but neither round's Godot "pass" met the bar by screenshot, so I ruled that they do not count.

## What the gains are made of (caveats)

1. **Baseline confound.** The baseline listed the full 34-kit catalog. Rounds 1+ list only the 8 foundation kits. The baseline's 0/5 is partly scope blowup (trials installed 33–34 kits), so baseline-to-round-1 is not a clean measure of the standard.
2. **Engine tutoring is not stitchability.** The Godot jump from 1/5 to 5/5 in round 4 came mostly from `standard/consumer/godot-csharp.md`: the MoveCheck self-check, a pitfalls list (key codes, `_PhysicsProcess(double)`, velocity in the XZ plane, collider placement) and project-file rules. These teach Godot itself. They belong with the standard as consumer notes, but they say nothing about module design.
3. **Checker gaps found late.** The camera gap was found in round 4 by looking at screenshots. Round 5 found two more: a frustum test passes even when no mesh is drawn, and a headless viewport is 64×64, which skews the test for wide cameras. Both were fixed for round 6, along with accepting a first-person camera. Round 6 found two more, filed as beads: occlusion only counts physics bodies (`Artifactory-2pd`), and nothing checks that a room exists (`Artifactory-3y3`). Each round of checker fixes has exposed the next gap; only a person looking at a screenshot has caught them.
4. **One model, small samples.** Every result is Ornith 35B, at 5 trials per round. A 5/5 versus 4/5 difference is within noise.
5. **Web access was open.** The sandbox did not block outbound traffic. Trial transcripts hold 51 `webfetch` calls across all rounds, mostly 404s from GitHub and godotengine.org; at least one fetched Godot source. The model's outside input was light but uncontrolled.

## Rules: what the rounds exercised

| Rule | Exercised? | Evidence |
|---|---|---|
| 1 Descriptor | yes | `artifactory validate` on all kits; the liveness format is validated |
| 2 Docs travel with code | yes | Go trials found READMEs via `go list -m -f '{{.Dir}}'`; Godot via submodules |
| 3 Never edit modules | yes | `modules_unmodified` passed in every trial from round 3 on |
| 4 Every module live | yes | liveness markers; all present in every round 4–6 Godot trial |
| 5 Worked example | partly | Trials that read the README Wiring section wired modules correctly. For Go, completing the Wiring text alone did not fix round 2; the round-3 API change did |
| 6 Minimise setup | yes | DevConsoleKit's input-action step was skipped in round 3; making it automatic removed the failure |
| 7 Index lists setup | weakly | Added in round 4; no setup-step failures after |
| 8 Consumer preamble | yes, but it grew | It now includes a stop rule and per-ecosystem "before finishing" notes |

Unproven:
- Whether any of this holds for another model.
- Whether it holds for a third ecosystem. Python is filed as epic `Artifactory-ht7`, blocked on this sub-project.
- Whether the 26 kits not yet converted to the standard behave like the 8 that were.

## Final descriptor fields

`name`, `ecosystem`, `version`, `summary`, `replaces`, `install`, `setup`, `entry`, `liveness`, `docs`, `example`, `test`. For godot-csharp, `liveness` must be exactly `[<Kit>] live`.

## Open conflicts

- **Kit catalog `Log.cs` retargeting.** The GodotKits catalog README tells consumers to retarget logging by editing a kit's `Log.cs`, which rule 3 forbids. This needs a public logging hook in the kits. It is not resolved.
- **26 kits not converted.** Only the 8 foundation kits have `stitchability` branches.
- **Kits moved.** All 34 kits and the GodotKits catalog now live in the Forgejo org `artifactory`, and the 8 `stitchability` branches are merged to `main`.
- **InputRemapKit.** Its README mentions an optional `InputDeviceTracker` autoload that its `setup:` does not list.

## For sub-project 2 (the artifactory itself)

- The index (MODULES.md) is the model's main entry point. Keep it generated from descriptors, and scope it to the modules a task needs, because a 34-kit index caused scope blowup.
- Ship each ecosystem's consumer notes with the index. They are what made Godot work.
- Treat the checker as part of the product: every "pass" should be backed by an artifact a person can look at, such as a screenshot or a request log.
- Kit fixes that worked became module changes (httpserver v0.2.0, DevConsoleKit self-setup). The artifactory needs a path for consumer failures to turn into module PRs.

## Best Godot trial to play

`results/godot-capsule-room/round-6/trial-1/project`. It passed every check in 58 min, its screenshot (`results/round-6/trial-1.png`) shows the capsule in a room, and it is the only round-6 trial whose walls are physics bodies, so they stop the player. To play it:

```
cd results/godot-capsule-room/round-6/trial-1/project && dotnet build && godot --path .
```

## Roadmap experiment

Planned, no results yet. It tests whether a roadmap of beads written by a frontier model, or by the local model, changes what the build session does with the kits. Design: `docs/superpowers/specs/2026-11-03-roadmap-experiment-design.md`. Harness commands are in `docs/superpowers/specs/2026-11-02-artifactory-cli-design.md` under "The harness".
