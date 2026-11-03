# Roadmap Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Lantern Keep acceptance test and a `--roadmap frontier|ornith|none` trial mode, so the three roadmap conditions can run.

**Architecture:** The new test directory holds the brief, the writer prompt and the frozen frontier roadmap. The Godot checker gains a probe mode for multi-room projects. The harness gains `bd` in the trial, an Ornith writing phase, a host-side bead loop with stall handling, and a command that prepares a writer workspace for the frontier subagent and exports its beads.

**Tech Stack:** Python harness (`tools/artifactory`, pytest via `uv run --project tools`), C# checker probe (Godot 4.7 .NET), bd 1.3.0.

**Spec:** `docs/superpowers/specs/2026-11-03-roadmap-experiment-design.md`

## Global Constraints

- `--roadmap` defaults to `none`; `frontier` and `ornith` require `--product` and `--arc`.
- Total wall clock per Lantern Keep trial: `time_limit_s: 14400`. The ornith writing phase gets at most 1200 s of it.
- The `bd` copied into a trial is the real binary `~/.local/lib/node_modules/@beads/bd/bin/bd`, resolved with `Path.resolve()` from `shutil.which("bd")`'s package dir or that fixed path. Never copy the `~/.local/bin/bd` Node wrapper: copied, it runs itself forever.
- bd environment: `DO_NOT_TRACK=1` (metrics off), `BEADS_ACTOR=<actor>`, `HOME=<trial home>`. The actor is `roadmap-writer` for the frontier writer workspace and `ornith` for trials. These go into `trial.env`, because `sandbox_command` uses `--clearenv` (sandbox.py:229). Host-side `bd` calls use the same env, so bd never writes `~/.beads` or `~/.config/bd` in the user's HOME.
- `bd init --stealth --non-interactive` in trial projects. `git status --porcelain` stays clean after it, and nothing beads-related is committed.
- Bead-session prompt, verbatim: `Work bead <id>. Run bd show <id> first, do only what it says, run its check, then bd close <id>.`
- Stall prompt, verbatim: `Some beads are unfinished. Run bd list --status open,blocked and work through them in any order, ignoring dependencies. Close each one you finish.`
- Bead-condition rounds write to `<results>/<test>/round-<N>-<roadmap>`. none keeps `round-<N>`.
- Timeout rule: a trial's `reason` is `"timeout"` only when its last session was killed at the deadline. This applies to all conditions.
- capsule-room behaviour, its checker output, its blank-fixture baseline, and existing tests stay unchanged.
- The `godot` pytest marker does not skip anything by itself (tools/pyproject.toml:24). Tests that need Godot, dotnet, mirrors, arc or bd also carry an explicit `pytest.mark.skipif` on the missing tool.

## Review Focus

1. A bead loop that ends early with time left: stall sessions must use the remaining time, including when only blocked beads remain.
2. A session that claims a bead and exits: the bead is reset to `open` (`bd update <id> --status open`) before the next pick, and retried once before `blocked`.
3. The lantern probe mode must not reach capsule-room runs or the blank-fixture baseline run.
4. Exports must carry the actor (`created_by`/`assignee` = `roadmap-writer` or `ornith`), never the user's identity.
5. A dead model server (sessions ending instantly) must not hot-loop until the deadline.

---

### Task 1: Lantern Keep test directory

**Files:** Create `tests/acceptance/godot-lantern-keep/{test.yaml,brief.md,roadmap-prompt.md,duplication.yaml,arc-registry.yaml}`. Modify `tools/artifactory/acceptance.py`. Test in `tools/tests/test_acceptance.py`.

**Produces:** `AcceptanceTest.roadmap_prompt: str | None`, `AcceptanceTest.probe: str | None`, `AcceptanceTest.dir: Path` (the test directory).

- [ ] `test.yaml`: name `godot-lantern-keep`, ecosystem `godot-csharp`, fixture `../../../fixtures/godot-blank`, `prompt: brief.md`, `roadmap_prompt: roadmap-prompt.md`, `probe: lantern`, `time_limit_s: 14400`, all 8 kits.
- [ ] `brief.md`: the spec's brief and contracts, written as the builder prompt (the none condition's prompt). Include "Use every module listed in `MODULES.md` for the job it does, instead of writing that functionality yourself." as capsule-room does. The game is 3D (a camera looking down).
- [ ] `roadmap-prompt.md`: the spec's writer rules. It refers to the brief as `BRIEF.md` in the project root. It also requires:
  - a `Modules: A, B` or `Modules: none` line in every bead description;
  - the `gap` label when no module covers a need;
  - each checker contract copied verbatim into the bead that implements it;
  - not claiming beads;
  - "Write the roadmap only. Do not build anything."
- [ ] `duplication.yaml`: copy capsule-room's. `arc-registry.yaml`: copy capsule-room's, with `system.name` changed to lantern-keep.
- [ ] Tests:
  - loading lantern-keep gives a `roadmap_prompt` and `probe == "lantern"`;
  - loading capsule-room gives None for both;
  - `dir` is the test directory.
- [ ] Commit `test: lantern keep acceptance test`.

### Task 2: Lantern probe mode

**Files:** Modify `tools/artifactory/godot_probe/CheckerProbe.cs` and `tools/artifactory/checks/godot.py`. Tests in `tools/tests/test_check_godot.py`.

- [ ] Probe mode `lantern`, selected by env `ARTIFACTORY_PROBE_MODE=lantern`. The checker sets it only on the trial copy's `godot` run when `test.probe == "lantern"`, never on the `_blank_errors` baseline run (godot.py:313-330). In this mode the probe does the following.
  - Check `ResourceLoader.Exists` before loading any room. A missing room prints a probe failure, not an engine ERROR.
  - Wait for a scene change with `ChangeSceneToFile`, then wait until `GetTree().CurrentScene.SceneFilePath` equals the target, then one more frame.
  - Change to `res://rooms/courtyard.tscn` and run the existing move/visible logic there.
  - Load `courtyard`, `hall` and `tower` in turn. Print `PROBE rooms=true|false missing=<comma names or none>`. A room passes when a node in group `player` exists after the change.
  - Load `hall.tscn` and put the player 1 m from the node in group `keeper`. Wait 2 physics frames, then send `InputEventAction{Action="interact", Pressed=true}` followed by a release. Wait up to 2 s.
  - Print `PROBE dialogue=true|false problem=<why>`. It is true when a node in group `dialogue` is visible in the tree. The problem values are `no_room`, `no_player`, `no_keeper`, `no_action` and `not_shown`.
- [ ] `godot.py`, only when `test.probe == "lantern"`:
  - append gating `rooms` and `dialogue` checks, with "not run: build failed" results when the build fails, as godot.py:56-59 does;
  - append an informational `title_scene` check that passes when `run/main_scene` is not a room. Resolve a `uid://` main scene against each room `.tscn`'s `[gd_scene … uid="…"]` header.
- [ ] Tests:
  - capsule-room's checker check list is unchanged (names and order);
  - the blank baseline run gets no `ARTIFACTORY_PROBE_MODE`;
  - `_check_probe` parses the new lines;
  - `title_scene` passes, fails, and resolves a uid main scene;
  - a skipif-guarded `godot` test builds a tiny 3D lantern fixture (three rooms, a keeper, a dialogue node shown on `interact`) and gets `rooms` and `dialogue` true.
- [ ] Commit `checker: lantern probe mode`.

### Task 3: bd in the trial

**Files:** Modify `tools/artifactory/harness.py`. Tests in `tools/tests/test_harness.py`.

**Produces:**
- `bd_binary() -> Path`;
- `bd_env(actor: str, home: Path) -> dict[str, str]`;
- `bd_run(project: Path, env: dict, *args) -> subprocess.CompletedProcess`;
- `prepare_trial(..., roadmap: str = "none", test_dir: Path | None = ...)`.

- [ ] `bd_binary()` resolves the real binary per Global Constraints, with a clear error if it is missing.
- [ ] `bd_env` returns `DO_NOT_TRACK=1`, `BEADS_ACTOR=actor` and `HOME=home`.
- [ ] Read the arc registry from `<test.dir>/arc-registry.yaml` instead of the hard-coded `ARC_REGISTRY` (harness.py:45, 227). capsule-room is unaffected because its file is the same one.
- [ ] prepare_trial, when `roadmap != "none"`:
  - copy `bd` into `trial.bin`;
  - merge `bd_env("ornith", trial.home)` into `trial.env`;
  - run `bd init --stealth --non-interactive` in the trial project;
  - for `frontier`, also run `bd import <test.dir>/roadmaps/frontier.jsonl`.
- [ ] Tests (skipif without bd):
  - after init, `git status --porcelain` is empty;
  - import of a sample JSONL keeps ids and deps;
  - `bd_env` values are correct;
  - the user's real `~/.beads` mtime is unchanged by a host-side call (use a temp HOME, check nothing appears outside it);
  - `trial.env` contains `DO_NOT_TRACK`.
- [ ] Commit `harness: bd in roadmap trials`.

### Task 4: Writing phase, bead loop and `--roadmap`

**Files:** Modify `tools/artifactory/harness.py`, `tools/artifactory/cli.py`, `tools/artifactory/result.py`. Tests in `tools/tests/test_harness.py`.

**Consumes:** Task 3's `bd_env`, `bd_run` and `prepare_trial(roadmap=…)`.

- [ ] Session runner. Each session runs `opencode_argv + [prompt]` when `opencode_argv` is given (test fakes use `["/bin/sh", "-c", script, "sh"]`, so the prompt arrives as `$1`), else `opencode_command(prompt)`. Its limit is the time remaining, and it writes `transcript-<n>.jsonl`. none keeps its single `transcript.jsonl`. `arc_denials` sums over all transcripts.
- [ ] `round --roadmap frontier|ornith|none` (default none), validated per Global Constraints. The round dir name follows Global Constraints. `round.json` records `roadmap`.
- [ ] ornith writing phase:
  - copy `brief.md` into the project as `BRIEF.md` (excluded via `.git/info/exclude`);
  - run one session with `roadmap_prompt` and limit `min(1200, remaining)`;
  - export beads to `<trial>/roadmap.jsonl`;
  - if it created zero beads, run one session with the brief and set `roadmap_failed: true`.
- [ ] Build loop (frontier and ornith), host-side, with bd using `trial.env`:
  1. Reset any `in_progress` bead to `open`.
  2. If `bd ready --json` is non-empty, pick its first bead and run a bead session.
     - If the bead is not closed afterwards, it gets one more session.
     - After a second failure, set it `blocked` and add `bd note <id> "<why>"`. Do not use `--notes`, which replaces.
  3. Else, if any bead is open, in_progress or blocked, run a stall session.
  4. Else, stop: all closed.
  5. Stop when time is up.
  6. Stop when 3 consecutive sessions each end in under 60 s with no bead status change, and set `loop_stalled: true`.
- [ ] Timeout reason per Global Constraints.
- [ ] Trial JSON gains `roadmap` (`beads`, `closed`, `blocked`, `sessions`, `stall_sessions`, `roadmap_failed`, `loop_stalled`). Export final bead state to `<trial>/beads-final.jsonl`.
- [ ] Tests, using a fake agent and real bd (skipif without bd):
  - order follows deps;
  - an unclosed bead is retried once, then blocked with a note;
  - only blocked beads remaining triggers stall sessions until time is up;
  - a stall session that closes a blocker returns to the ready loop;
  - time is never exceeded;
  - an instant-exit agent triggers `loop_stalled`;
  - ornith with zero beads falls back;
  - the timeout reason only when the last session was killed;
  - none mode is unchanged.
- [ ] Commit `harness: roadmap conditions and bead loop`.

### Task 5: Frontier writer workspace

**Files:** Modify `tools/artifactory/cli.py`, `tools/artifactory/harness.py`. Create `tests/acceptance/godot-lantern-keep/roadmaps/.gitkeep`. Test in `tools/tests/test_harness.py`.

The user chose (2026-11-03) that a subagent of the controlling Claude Code session writes the frontier roadmap. The harness only prepares the workspace and exports the result.

- [ ] `artifactory roadmap-workspace <test_dir> <out_dir>` prepares `<out_dir>` as a frontier trial would, but without importing a roadmap:
  - product CLI, arc and bd in `<out_dir>/bin`;
  - bd init with actor `roadmap-writer`;
  - `BRIEF.md` and `ROADMAP-PROMPT.md` in the project.
  - It prints the project path and a one-line `env` prefix (PATH with the workspace bin, `DO_NOT_TRACK=1`, `BEADS_ACTOR=roadmap-writer`, `HOME=<workspace home>`) for the subagent to put before every command.
- [ ] `artifactory roadmap-export <project> <out.jsonl>`:
  - runs `bd export` with that env;
  - fails if any bead is `in_progress` or has an assignee other than empty or `roadmap-writer`;
  - fails if any `created_by` is not `roadmap-writer`.
- [ ] Tests (skipif without bd):
  - the workspace has bin, BRIEF.md and ROADMAP-PROMPT.md;
  - beads created with the printed env export with `created_by == "roadmap-writer"`;
  - export refuses an `in_progress` bead.
- [ ] Commit `harness: frontier roadmap workspace and export`.

### Task 6: Roadmap scoring and docs

**Files:** Create `tools/artifactory/roadmap.py`. Modify the CLI design spec (`docs/superpowers/specs/2026-11-01-artifactory-cli-design.md`, or wherever `round` options are documented) and `docs/specs/2026-11-01-stitchability-standard-results.md` (a short "roadmap experiment" pointer). Test `tools/tests/test_roadmap.py`.

- [ ] `score_roadmap(jsonl_path: Path, kits: list[str], contracts: list[str]) -> dict` reports:
  - kits named in `Modules:` lines;
  - unknown module names;
  - beads with no `Modules:` line;
  - whether a `gap`-labelled bead mentions dialogue;
  - which contracts appear in bead text;
  - bead counts by status.
  - Contracts are the strings `player`, `keeper`, `dialogue`, `res://rooms/courtyard.tscn`, `res://rooms/hall.tscn`, `res://rooms/tower.tscn` and `interact`. Each is checked as a whole word in descriptions.
- [ ] `artifactory roadmap-score <file> [--test <dir>]` prints the score as text and with `--json`. Kits come from the test's modules.
- [ ] Tests on hand-written JSONL samples.
- [ ] Commit `feat: roadmap scoring`.

After the tasks:
1. Prepare a workspace with `roadmap-workspace`.
2. Dispatch an opus subagent with the writer prompt, the workspace path and the env prefix; it builds nothing.
3. Export with `roadmap-export`.
4. Have a fresh reviewer check the roadmap for code and prompt violations, then commit it.
5. Run the three conditions after round 9; beads track the runs.
