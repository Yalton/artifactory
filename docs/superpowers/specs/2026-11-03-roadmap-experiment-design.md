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

- read the brief; run `artifactory search` for each need, and `artifactory show` on candidates;
- write beads with `bd create`, each completable in one fresh session, each with a description that says what to build, which modules it uses (by name, or `none`), and how to check it is done;
- label a bead `gap` when no module covers its need;
- add dependencies with `bd dep add` so `bd ready` gives a sensible order;
- describe outcomes and contracts, not code;
- stop after writing the roadmap; do not build anything.

### frontier

A frontier agent writes the roadmap once: headless `claude -p --model claude-opus-5-5` run in the trial sandbox on a prepared trial project (with `artifactory`, `arc` and `bd` on PATH and the dir: provider on the mirrors). Its HOME holds only the Claude credentials, with no CLAUDE.md, hooks, skills, plugins or MCP servers, so it gets the same instructions Ornith gets and nothing else. The mirrors are local paths, so it needs no network beyond the model API. This uses the user's Claude subscription once; the user asked for a frontier condition. Its beads are exported (`bd export`) to `tests/acceptance/godot-lantern-keep/roadmaps/frontier.jsonl` and committed. Every frontier trial imports that same file. A fresh reviewer reads it before the round and rejects it only if it contains code or violates the prompt.

Frozen once, so frontier trials share one roadmap. Its variance between writings is not measured; the report says so.

### ornith

Each ornith trial starts with a writing phase: one Ornith session in the sandbox on the prepared project, with the writer prompt, the brief and `bd` initialised. The phase gets 20 minutes of the trial's budget. Its beads are exported to the trial directory for the report. Ornith writing per trial is part of the condition, so its variance is measured.

### none

One Ornith session with the brief as the prompt, as in rounds 7–9, with the full time budget.

### Build phase (frontier and ornith)

The harness runs beads one at a time, the way `run-beads` does: while time remains and `bd ready` lists a bead, start a fresh Ornith session with a fixed prompt (`Work bead <id>. Run bd show <id> first, do only what it says, run its check, then bd close <id>.`). A bead whose session ends without closing it is retried once; a second failure marks it `blocked` with a note and moves on. The phase stops when no bead is ready or time is up.

### When the loop stalls

- Before each pick, the harness resets beads left `in_progress` by a finished session back to `open`.
- When `bd ready` is empty but open or blocked beads remain and time is left, the harness runs one more session with the prompt `Some beads are unfinished. Run bd list --status open,blocked and work through them in any order, ignoring dependencies. Close each one you finish.` It repeats this until no open beads remain or time is up. The roadmap stays the source of work, and no time is left unused.
- If the ornith writing phase creates no beads, the trial's build phase is one session with the brief as the prompt, as in none, and the trial records `roadmap_failed: true`.
- If writing finishes before 20 minutes, the rest goes to building. The 4-hour total is fixed.

### Time and trials

Every trial gets 4 hours of wall clock in total (writing phase included for ornith). 3 trials per condition, 9 in all. If the two best conditions' pass counts differ by 1 or less, add 2 more trials per condition. This rule is fixed before any run.

## Measurement

Per trial, `checker.json` gets the existing Godot checks plus:

- `player_moves` and `player_visible` run in `courtyard.tscn` instead of the main scene: the probe loads the room directly, since the main scene is the title screen;
- `rooms`: the probe loads each room scene and reports whether it contains a node in group `player` at runtime (a group set in C# counts);
- `dialogue`: the probe loads `hall.tscn`, moves the player next to the node in group `keeper`, presses `interact`, and reports whether a node in group `dialogue` became visible;
- `title_scene`: the main scene is not a room scene;
- the arc fields from round 9 (`arc_gate`, `arc_denials`, `arc_hook_live`).

Pass/fail stays as today's gating checks plus `rooms` and `dialogue`. `title_scene` is informational.

Per bead condition, the round report also records from the exported beads:

- bead count, closed, blocked;
- module naming, parsed from the `Modules:` line the writer prompt requires in every bead description (`Modules: A, B` or `Modules: none`): which of the 8 kits are named by at least one bead, names that are not real modules, and whether a bead labelled `gap` covers dialogue;
- beads that ask for a kit's job to be reimplemented, judged by hand at report time from the exported beads.

Screenshots of the title, a room and the dialogue box (godot-shot), viewed, for every trial that builds. The stitchability checker lesson stands: no pass without a screenshot.

## Harness changes

- `tests/acceptance/godot-lantern-keep/`: `test.yaml` (all 8 modules, `time_limit_s: 14400`), `brief.md`, `roadmap-prompt.md`, `duplication.yaml` (reuse capsule-room's patterns), `arc-registry.yaml`, `module-key.yaml`, and `roadmaps/frontier.jsonl` once written.
- `round --roadmap frontier|ornith|none` (default none). frontier and ornith require `--product`.
- the real `bd` binary (`~/.local/lib/node_modules/@beads/bd/bin/bd`, not the `~/.local/bin/bd` Node wrapper, which loops when copied) is copied into `trial.bin`. Every `bd` call, in the sandbox and on the host, runs with metrics off, and the actor is set to `roadmap-writer` or `ornith` so exports carry no user identity; prepare_trial runs `bd init --stealth` in the trial project (no git hooks, nothing committed) and, for frontier, `bd import` of the frozen file.
- The bead loop runs on the host and calls `bd` against the trial project between sessions; each session is the existing sandboxed opencode run with a new prompt and the remaining time as its limit.
- Checker additions: a probe mode selected by an environment variable (capsule-room unchanged) that runs `player_moves`/`player_visible` in courtyard, then `rooms` and `dialogue`; plus the static `title_scene` check.
- `round.json` records `roadmap`. Trial JSON records the bead outcome counts.

## Decided by me (the user delegated these)

- The project (Lantern Keep), the gap (dialogue), the contracts, the time budget (4 hours), and 3 trials per condition.
- arc on in all conditions, so the only variable is the roadmap.
- The frontier roadmap is frozen once; Ornith's is written per trial.
- Same writer prompt for both writers, and a clean HOME for the frontier writer.
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
