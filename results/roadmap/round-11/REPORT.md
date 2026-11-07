# Roadmap experiment: Lantern Keep, round 11

Design: `docs/superpowers/specs/2026-11-03-roadmap-experiment-design.md`. Bead: Artifactory-5dx.2. Round 10 report: `results/roadmap/REPORT.md`.

**0 of 3 passed.** Round 11 repeated round 10 with 12-hour trials instead of 4. The user cut it to one trial per condition (frontier, ornith, none), so this is a directional read, not a comparison with any statistical weight. The longer limit did not help, because no trial needed it:
- frontier spent 10 of its 11 hours stuck on one bead;
- ornith's and none's single build sessions stopped on their own after about 3 h 40 min and 3 h.

## Setup

- Each condition ran `artifactory round tests/acceptance/godot-lantern-keep --round 11 --trials 1 --product --arc --roadmap <condition> --time-limit-s 43200` once, in the order frontier, ornith, none.
- The round was planned as 3 trials per condition. On Nov 6 the user chose one per condition to finish sooner. A watcher stopped the driver when the second cycle began; that just-started trial was discarded.
- Everything else matches round 10: the frozen 16-bead frontier roadmap, a writing phase of at most 20 minutes for ornith, and the same kits, checker and arc gate.

Results: `results/godot-lantern-keep/round-11-{frontier,ornith,none}/trial-1/`, with `round-trial-1.json` beside each.

## Results

Y = check passed. `title_scene` and `arc gate` are informational (`gating: false` in `checker.json`); the other 10 checks gate a pass. Round 10's report counted the arc gate in its "of 11" column; by this rule its counts are one lower wherever the arc gate passed.

| Trial | build | runs | moves | visible | rooms | dialogue | installed | live | unmodified | no dup | arc gate | title | gating passed (of 10) | Ends |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| frontier | Y | Y | Y | Y | Y | . | . | . | . | . | Y | . | 5 | **infrastructure** (connection lost after about 11 h, 6 resumes) |
| ornith | Y | . | Y | Y | . | . | Y | Y | Y | . | Y | Y | 6 | build session stopped on its own after about 3 h 40 min |
| none | . | . | . | . | . | . | Y | . | Y | Y | Y | Y | 3 | session stopped on its own after about 3 h |

What each trial did:
- **frontier.** It closed 3 of 16 beads (the skeleton, the player and courtyard, the hall and tower) in the first hour. It then spent two sessions, 3½ hours and 6½ hours, on the doors-with-fade bead (TransitionKit) and left it blocked. The model connection dropped near the end of the second. The 12 later beads, which install the other kits, never started. Its room manager calls `ChangeSceneToPacked`, which TransitionKit covers, so `no_duplication` failed. The main scene is the courtyard, not a title screen.
- **ornith.** The roadmap writer spent its 20 minutes searching kits and test-installing CrashKit, and wrote no beads. The harness then fell back to one build session with the brief. That session installed all 8 kits, and **for the first time in the roadmap rounds (10 and 11) every kit printed its liveness marker**. It also built a proper title screen. But the hall scene fails to load (a parse error), so `runs` and `rooms` fail, and its own menu code sets the mouse mode that CursorKit owns.
- **none.** One session wrote the whole game and left it unbuildable: `SettingsScreen.cs(100,43): error CS1010: Newline in constant`. It did install the kits unmodified.

### Screenshots

`montage.png`, rendered at 1600×900 after 2 s (none does not build):
- top row, frontier: the main scene is the courtyard itself, a brown walled room with the player (a sphere) and a door; the courtyard scene loaded directly looks the same;
- bottom left, ornith main scene: a "Lantern Keep" title with New Game, Continue, Settings and Quit;
- bottom right, ornith courtyard: a grey floor with the player.

## Findings

1. **Time was not the constraint in this round.** Round 10's diagnosis was one bead per hour. Here frontier closed 3 beads in an hour, as before, and then stalled for 10 hours on one bead. The other two conditions quit well before their limit. Longer trials alone will not finish this game.
2. **A single stuck bead stops a roadmap.** Both long sessions worked the doors bead (`project-yo0`) instead of moving past it. Through the roadmap's dependencies, 9 of the 12 open beads waited on it, directly or through the title screen and pause menu. Only 3 did not: the keeper NPC, the dialogue box and crash reports. So a per-bead time limit alone would have bought little here. The roadmap also routes most kits through one risky bead; failing or skipping that bead should not hold back unrelated kit work.
3. **Ornith's writing phase is fragile.** It spent its whole budget exploring and installing, and wrote nothing. In round 10 it wrote a roadmap 3 times out of 3. One trial cannot say how often this happens.
4. **Kit adoption is not the problem when the model installs up front.** The ornith fallback session installed and started all 8 kits. What it lacked was working rooms. That is the mirror image of frontier, which built rooms but never reached the kits.

## Not done

- The frontier trial lost its connection after about 11 of its 12 hours. The design says to re-run an infrastructure loss once. That would cost another 12 hours for at most one more hour of work, against the user's wish to finish sooner, so it was not re-run. Its result is reported as it stands.
- The remaining 6 planned trials were not run, by the user's choice.
