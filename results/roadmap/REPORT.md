# Roadmap experiment: Lantern Keep, round 10

Round 11 (12-hour trials, one per condition): `results/roadmap/round-11/REPORT.md`.

Design: `docs/superpowers/specs/2026-11-03-roadmap-experiment-design.md`. Bead: Artifactory-5dx.2.

**0 of 9 passed.** No condition finished the game in 4 hours. By pass count the three conditions are tied at zero, a floor that pass counts cannot separate. The checks each trial did pass do separate them:
- frontier built the playable part of the game every time and never got to most kits;
- ornith installed the kits every time and never built the game;
- none never produced a build.

## Setup

- All three conditions ran `artifactory round tests/acceptance/godot-lantern-keep --round 10 --trials 1 --product --arc --roadmap <condition>`, 3 times each.
- Trials were interleaved: frontier, ornith, none in the first cycle, then rotated each cycle. A bad hour on the model server therefore lands on more than one condition.
- Each trial had 4 hours.
- The copy-safe MoveCheck (PR #9) was merged before this round, so the consumer notes differ slightly from rounds 7–9. The ruling is noted on Artifactory-5dx.2.
- The frontier roadmap is the frozen `tests/acceptance/godot-lantern-keep/roadmaps/frontier.jsonl`: 16 beads, all 8 kits named, 7 of 7 contracts. An Opus subagent of the controlling session wrote it. Unlike Ornith, that subagent could see the user's global CLAUDE.md.
- The ornith roadmaps were written per trial during a writing phase of at most 20 minutes.

Results: `results/godot-lantern-keep/round-10-{frontier,ornith,none}/trial-N/`. Each has `checker.json` and the transcripts. The bead conditions also have `beads-final.jsonl`, and the ornith trials have `roadmap.jsonl`. Each trial's `round.json` is kept as `round-trial-N.json`, because the trials ran as separate one-trial rounds.

## Results

Y = check passed. `title_scene` is informational; the other checks gate a pass.

| Trial | build | runs | moves | visible | rooms | dialogue | installed | live | unmodified | no dup | arc gate | title | gating passed (of 11) | Ends |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| frontier t1 | Y | . | Y | Y | Y | . | . | . | . | Y | Y | Y | 6 | timeout |
| frontier t2 | Y | Y | Y | Y | Y | . | . | . | . | Y | . | Y | 6 | timeout, 2 resumes |
| frontier t3 | Y | Y | . | Y | Y | . | . | . | . | Y | Y | . | 6 | timeout, 3 resumes |
| ornith t1 | Y | . | . | . | . | . | Y | . | Y | . | Y | Y | 4 | timeout |
| ornith t2 | Y | Y | . | . | . | . | Y | . | Y | . | Y | Y | 5 | **infrastructure** (connection lost after about 1 h 47 min) |
| ornith t3 | . | . | . | . | . | . | Y | . | Y | . | Y | Y | 3 | timeout |
| none t1 | . | . | . | . | . | . | Y | . | Y | . | . | Y | 2 | timeout |
| none t2 | . | . | . | . | . | . | Y | . | Y | Y | Y | Y | 4 | **infrastructure** (connection lost after about 1 h 10 min) |
| none t3 | . | . | . | . | . | . | Y | . | Y | . | Y | Y | 3 | timeout |

No trial got the dialogue (the gap) working; the probe found no keeper in any trial that built. No trial printed every kit's liveness marker.

### Beads

| Trial | Roadmap | Closed | Sessions | Closed beads |
|---|---|---|---|---|
| frontier t1 | 16 (frozen) | 3 | 4 | skeleton, player, hall and tower |
| frontier t2 | 16 (frozen) | 4 | 5 | skeleton, player, hall and tower, doors with fade |
| frontier t3 | 16 (frozen) | 3 | 4 | skeleton, player, hall and tower |
| ornith t1 | 14 | 1 | 3 | scaffold and bootstrap |
| ornith t2 | 11 | 1 | 3 | bootstrap |
| ornith t3 | 11 | 1 | 3 | foundation / scaffold |

Each bead session took about an hour. Ornith's first bead always installed all 8 kits up front. Its scaffold bead named every kit, and the model then spent its sessions wiring kits into a project that had no rooms. The frontier roadmap starts with the skeleton, player and rooms and installs each kit in the bead that uses it, so the kits that later beads would have installed never arrived.

Every bead in the ornith exports was created by `ornith`, and every bead in the frontier exports by `roadmap-writer`. No user identity appears.

### Roadmap quality (`roadmap-score`)

| Roadmap | Beads | Kits named | Modules line | Dialogue as gap | Contracts |
|---|---|---|---|---|---|
| frontier (frozen) | 16 | 8/8 | all | yes | 7/7 |
| ornith t1 | 14 | 0/8 | none | yes | 7/7 |
| ornith t2 | 11 | 8/8 | all | yes | 7/7 |
| ornith t3 | 11 | 8/8 | all; lists `gap` as a module | yes | 7/7 |

Ornith copied every contract into every roadmap. One of its three roadmaps left out the required `Modules:` line entirely. Like the frontier roadmap, Ornith's roadmaps labelled more than dialogue as a gap (movement, rooms). Ornith t1 also labelled the pause menu as a gap, though TransitionKit and CursorKit cover parts of it.

### Screenshots

`results/roadmap/montage.png` has the main scene and the courtyard for every trial that builds, rendered at 1600×900 after 2 s:
- **frontier t1:** a title label with an empty panel; the courtyard is a walled room with the capsule player.
- **frontier t2:** a "Lantern Keep" label only; a walled green courtyard with the player.
- **frontier t3:** the main scene is the courtyard itself (`title_scene` fails), a brown room with the player and a cyan door.
- **ornith t1:** a title screen with one "Quit" button drawn over another label in the corner.
- **ornith t2:** a proper title screen with New Game, Continue, Settings and Quit. It has no rooms to start.

The none trials and ornith t3 do not build.

Failure details:
- none's build errors were in its own code: a wrong anchor API, a syntax error and a nonexistent enum. Each trial was one 4-hour session that tried to write the whole game.
- ornith t3 broke its build with its own `TitleCheck.cs` (top-level statements after a type).
- arc's gate failed twice, both times because the model edited arc's registry. In frontier t2 it added a `door` concept that needs approval; in none t1 it left 20 registry errors.

## Findings

1. **4 hours is too short for a 16-bead game at this model's speed.** About one bead per hour means a roadmap condition finishes a quarter of its roadmap. The pass-count comparison the design planned for cannot separate the conditions, because all are at zero.
2. **Roadmaps beat one prompt on what gets built.** Both bead conditions produced a build in 5 of 6 trials; none produced 0 of 3. Small beads with their own checks kept the build working. One long session never did.
3. **The roadmap's order decides what gets built.** frontier puts the playable core first and gets rooms, movement and a visible player every time. ornith installs all kits first, then runs out of time before any room exists. Frontier passes 6 gating checks per trial against ornith's 3–5. Frontier's misses are the kits that later beads would have installed.
4. **Ornith writes usable roadmaps, mostly.** It copied every contract and kept beads small. It also skipped the `Modules:` line once and once called a partly kit-covered need a gap.
5. **The model sometimes edits arc's registry** (2 of 9 trials). That fails arc's gate. No trial modified a kit.

## The extension rule

The design fixed one rule before any run: if the two best conditions' pass counts differ by 1 or less, add 2 trials per condition. Here they differ by 0, so the rule calls for 6 more trials. Re-running the 2 infrastructure losses would add 2 more, about 32 hours in all. They have not been run. At 0 of 9, two more 4-hour trials per condition would almost certainly also score zero, and could not break a tie at the floor. Whether to run them anyway, or change the design (more time per trial, or a smaller game), is the user's call. This report does not decide it.
