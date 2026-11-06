# Roadmap experiment design

Date: 2026-11-03. Bead: Artifactory-5dx. The user delegated approval of this design (2026-11-02). A fresh reviewer checks it in place of a user read.

## Intent

Rounds 1–9 give Ornith (the local model) one prompt and one session per game. Real work comes as a roadmap: a list of beads, each small enough for one session. This experiment asks who should write that roadmap when the builder is Ornith and the project consumes Artifactory modules:

- **frontier**: a frontier agent writes the beads;
- **ornith**: Ornith writes its own beads;
- **none**: no roadmap; one prompt, as in rounds 7–9.

Both writers stay allowed in the product. The experiment measures which one leads to a better game and better module use, so the docs can say when to use each.

## Goals

- One example project that needs most of the 8 Godot kits plus at least one capability no kit covers (a gap).
- The same build setup in all three conditions: `--product --arc` (round 9's setup), the same modules, the same total time budget.
- Roadmaps written under the same rules: use `artifactory search`, name the modules each bead uses, label needs with no module as gaps.
- Results comparable with rounds 7–9 where the checks overlap.

## Non-goals

- Tuning the writer prompt per condition. Both writers get the same prompt.
- Measuring roadmap writing cost or speed.
- Module-wanted requests from gaps (Artifactory-t7l, later).
- Python or Go projects.

## Anti-goals

- A frontier roadmap so detailed it is the code. Beads describe outcomes and contracts, not implementations; the writer prompt says so, and the reviewer of the frozen frontier roadmap rejects pasted code.
- Giving the bead conditions more total time than the none condition.

## Example project: Lantern Keep

A small top-down Godot 4.7 C# game, in 3D (a camera looking down on capsule-style characters), so the existing 3D probe applies. The brief (`tests/acceptance/godot-lantern-keep/brief.md`, given to the roadmap writers and, in the none condition, to the builder):

- A title screen with New Game, Continue, Settings and Quit.
- Three rooms (courtyard, hall, tower) joined by doors. Walking through a door changes room with a fade.
- A player that moves with WASD (rebindable) and is in group `player`.
- An NPC keeper in the hall. Walking up to the keeper and pressing interact opens a dialogue box that types out three lines, one per press. **This is the gap**: no kit covers dialogue.
- A pause menu (Escape) with Resume, Settings, Save and Quit to Title.
- Settings: master volume, fullscreen, vsync, and key rebinding.
- Save and Continue: the current room and the player position persist across runs.
- A custom cursor on menus, hidden during play.
- A developer console (backtick) with at least a `room <name>` command.
- Debug logging for room changes, and crash reports written on unhandled exceptions.

Kit coverage: TransitionKit (doors, menus), RunSaveKit (save/continue), SettingsKit (settings), InputRemapKit (rebinding), CursorKit (cursor), DevConsoleKit (console), DebugLogKit (logging), CrashKit (crash reports). All 8 kits apply, and dialogue is the gap.

Contracts for the checker (in the brief, all conditions):

- The player node is in group `player`; the keeper NPC is in group `keeper`.
- The main scene (`run/main_scene`) is the title screen; the room scenes are `res://rooms/courtyard.tscn`, `res://rooms/hall.tscn`, `res://rooms/tower.tscn`, and each has the player.
- The dialogue box is a node in group `dialogue` that becomes visible after interact near the keeper.
- An input action `interact` exists.
- `dotnet build` succeeds.

## Conditions

All three run `artifactory round tests/acceptance/godot-lantern-keep --product --arc` with a new `--roadmap frontier|ornith|none` option. The fixture, mirrors, modules in scope, arc registry, model server and sandbox are identical.

### Writer prompt (frontier and ornith)

One file, `tests/acceptance/godot-lantern-keep/roadmap-prompt.md`, used verbatim by both writers. It says:

- read the brief, which writers get as `BRIEF.md` in the project root; run `artifactory search` for each need, and `artifactory show` on candidates;
- write beads with `bd create`, each completable in one fresh session, each with a description that says what to build, which modules it uses (by name, or `none`), and how to check it is done;
- label a bead `gap` when no module covers its need;
- add dependencies with `bd dep add` so `bd ready` gives a sensible order;
- copy each checker contract verbatim into the bead that implements it, since bead sessions never see the brief;
- describe outcomes and contracts, not code;
- stop after writing the roadmap; do not build anything.

### frontier

A frontier agent writes the roadmap once: a subagent (claude-opus-5-5) of the controlling Claude Code session, run against a prepared writer workspace (a trial project with `artifactory`, `arc` and `bd` set up as in a frontier trial, actor `roadmap-writer`). The user chose this over a headless `claude -p` run (2026-11-03) so the roadmap uses no extra subscription allowance. The subagent sees the user's global CLAUDE.md, which Ornith does not; the report states this difference. The subagent is told to use only the writer prompt and `BRIEF.md`, to run commands from the workspace with its `bin` on PATH, and not to claim beads. Its beads are exported (`bd export`) to `tests/acceptance/godot-lantern-keep/roadmaps/frontier.jsonl` and committed. Every frontier trial imports that same file. A fresh reviewer reads it before the round and rejects it only if it contains code or violates the prompt.

Frozen once, so frontier trials share one roadmap. Its variance between writings is not measured; the report says so.

### ornith

Each ornith trial starts with a writing phase: one Ornith session in the sandbox on the prepared project, with the writer prompt, the brief and `bd` initialised. The phase gets 20 minutes of the trial's budget. Its beads are exported to the trial directory for the report. Ornith writing per trial is part of the condition, so its variance is measured.

### none

One Ornith session with the brief as the prompt, as in rounds 7–9, with the full time budget.

### Build phase (frontier and ornith)

The harness runs beads one at a time, the way `run-beads` does: while time remains and `bd ready` lists a bead, start a fresh Ornith session with a fixed prompt (`Work bead <id>. Run bd show <id> first, do only what it says, run its check, then bd close <id>.`). A bead whose session ends without closing it is retried once; a second failure marks it `blocked` with a note and moves on. The phase stops when no bead is ready or time is up.

### When the loop stalls

- Before each pick, the harness resets beads left `in_progress` by a finished session back to `open`.
- When `bd ready` is empty but beads remain open, in progress or blocked and time is left, the harness runs a stall session with the prompt `Some beads are unfinished. Run bd list --status open,blocked and work through them in any order, ignoring dependencies. Close each one you finish.` After it, the harness resets in-progress beads and goes back to `bd ready`. This repeats until every bead is closed or time is up, so no time is left unused.
- Three sessions in a row that each end in under 60 s with no bead status change stop the loop, and the trial records `loop_stalled: true` (it guards against a dead model server).
- A bead trial counts as a timeout, like none, only when the last session was killed at the deadline.
- If the ornith writing phase creates no beads, the trial's build phase is one session with the brief as the prompt, as in none, and the trial records `roadmap_failed: true`.
- If writing finishes before 20 minutes, the rest goes to building. The 4-hour total is fixed.

### Time and trials

Every trial gets 4 hours of wall clock in total (writing phase included for ornith). 3 trials per condition, 9 in all. If the two best conditions' pass counts differ by 1 or less, add 2 more trials per condition. This rule is fixed before any run.

## Measurement

Per trial, `checker.json` gets the existing Godot checks plus:

- `player_moves` and `player_visible` run in `courtyard.tscn` instead of the main scene: the probe loads the room directly, since the main scene is the title screen;
- `rooms`: the probe loads each room scene and reports whether it contains a node in group `player` at runtime (a group set in C# counts);
- `dialogue`: the probe loads `hall.tscn`, moves the player next to the node in group `keeper`, presses `interact`, and reports whether a node in group `dialogue` became visible;
- `title_scene`: the main scene is not a room scene (a `uid://` main scene is resolved against the room scenes' uids);
- the arc fields from round 9 (`arc_gate`, `arc_denials`, `arc_hook_live`).

Pass/fail stays as today's gating checks plus `rooms` and `dialogue`. `title_scene` is informational.

Per bead condition, the round report also records from the exported beads:

- bead count, closed, blocked;
- contracts: which of the brief's checker contracts appear in the roadmap's bead text;
- module naming, parsed from the `Modules:` line the writer prompt requires in every bead description (`Modules: A, B` or `Modules: none`): which of the 8 kits are named by at least one bead, names that are not real modules, and whether a bead labelled `gap` covers dialogue;
- beads that ask for a kit's job to be reimplemented, judged by hand at report time from the exported beads.

Screenshots of the title, a room and the dialogue box (godot-shot), viewed, for every trial that builds. The stitchability checker lesson stands: no pass without a screenshot.

## Harness changes

- `tests/acceptance/godot-lantern-keep/`: `test.yaml` (all 8 modules, `time_limit_s: 14400`), `brief.md`, `roadmap-prompt.md`, `duplication.yaml` (reuse capsule-room's patterns), `arc-registry.yaml` (used by the harness in place of capsule-room's), and `roadmaps/frontier.jsonl` once written.
- `round --roadmap frontier|ornith|none` (default none). frontier and ornith require `--product`.
- the real `bd` binary (`~/.local/lib/node_modules/@beads/bd/bin/bd`, not the `~/.local/bin/bd` Node wrapper, which loops when copied) is copied into `trial.bin`. Every `bd` call, in the sandbox and on the host, runs with metrics off, and the actor is set to `roadmap-writer` or `ornith` so exports carry no user identity; prepare_trial runs `bd init --stealth` in the trial project (no git hooks, nothing committed) and, for frontier, `bd import` of the frozen file.
- The bead loop runs on the host and calls `bd` against the trial project between sessions; each session is the existing sandboxed opencode run with a new prompt and the remaining time as its limit.
- Checker additions: a probe mode selected by an environment variable (capsule-room unchanged) that runs `player_moves`/`player_visible` in courtyard, then `rooms` and `dialogue`; plus the static `title_scene` check.
- Bead-condition rounds write to `round-<N>-<roadmap>` so the three conditions share a round number without colliding.
- `round.json` records `roadmap`. Trial JSON records the bead outcome counts.

## Decided by me (the user delegated these)

- The project (Lantern Keep), the gap (dialogue), the contracts, the time budget (4 hours), and 3 trials per condition.
- arc on in all conditions, so the only variable is the roadmap.
- The frontier roadmap is frozen once; Ornith's is written per trial.
- Same writer prompt for both writers.
- (User, 2026-11-03) The frontier writer is an in-session subagent, not headless `claude -p`.
- Stall handling and the fixed rule for adding trials.
- The writer prompt requires a `Modules:` line so naming is scored mechanically.

## Left to the builder

- The exact wording of the writer prompt and the bead-session prompt, within the rules above.
- How the dialogue probe drives the player to the keeper (teleporting the player next to the keeper is fine; the probe tests the dialogue, not navigation).

## Order

1. Harness changes and the test directory, with tests (a plan, subagent-driven).
2. Write and review the frozen frontier roadmap.
3. Run the 9 trials, after round 9.
4. Report: `results/roadmap/REPORT.md` and an update to the standard's results doc.

## Round 11: 12-hour trials

Round 10 (`results/roadmap/REPORT.md`) scored 0 of 9: every trial hit the 4-hour limit. A bead session took about an hour, so the bead conditions finished only 3–4 of their 11–16 beads. The preregistered extension (2 more 4-hour trials per condition) was not run, because it cannot break a tie at zero. The user chose longer trials instead (2026-11-06).

Round 11 repeats round 10 with one change: each trial gets 12 hours (`artifactory round --time-limit-s 43200`), recorded as `time_limit_s` in `round.json`. Everything else is unchanged:
- the frozen frontier roadmap;
- the writer prompt and the 20-minute ornith writing phase;
- the checks and the arc setup;
- 3 trials per condition, interleaved as in round 10.

A trial lost to infrastructure is re-run once. The extension rule is not applied; the round 11 report states the pass counts with the per-check comparison. The full round takes up to 108 hours of the local model.
