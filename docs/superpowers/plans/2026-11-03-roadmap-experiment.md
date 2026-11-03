# Roadmap Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Lantern Keep acceptance test and a `--roadmap frontier|ornith|none` trial mode, so the three roadmap conditions can run.

**Architecture:** The new test directory holds the brief, the writer prompt and the frozen frontier roadmap. The Godot checker gains a probe mode for multi-room projects. The harness gains `bd` in the trial, an Ornith writing phase, a host-side bead loop with stall handling, and a one-off frontier writer command.

**Tech Stack:** Python harness (`tools/artifactory`, pytest via `uv run --project tools`), C# checker probe (Godot 4.7 .NET), bd 1.3.0.

**Spec:** `docs/superpowers/specs/2026-11-03-roadmap-experiment-design.md`

## Global Constraints

- `--roadmap` defaults to `none`; `frontier` and `ornith` require `--product` and `--arc`.
- Total wall clock per Lantern Keep trial: `time_limit_s: 14400`. The ornith writing phase gets at most 1200 s of it.
- The `bd` copied into a trial is `~/.local/lib/node_modules/@beads/bd/bin/bd` (resolve the real binary; never copy the `~/.local/bin/bd` wrapper).
- Every `bd` call (sandbox and host) runs with metrics off and a fixed actor: `roadmap-writer` for the frontier writer, `ornith` for trials.
- `bd init --stealth --non-interactive` in trial projects; nothing beads-related is committed.
- Bead-session prompt, verbatim: `Work bead <id>. Run bd show <id> first, do only what it says, run its check, then bd close <id>.`
- Stall prompt, verbatim: `Some beads are unfinished. Run bd list --status open,blocked and work through them in any order, ignoring dependencies. Close each one you finish.`
- capsule-room behaviour, its checker output, and existing tests stay unchanged.
- Python tests that need Godot, mirrors, arc or bd are marked `godot` and skip when those are missing.

## Review Focus

1. A bead loop that ends early with time left: the stall session must use the remaining time.
2. A session that claims a bead and exits: the bead must be reset to `open` before the next pick, and retried once before `blocked`.
3. The probe mode must not change capsule-room's checker output (the env var is unset there).
4. Exports must not contain the user's identity (`created_by`).
5. The frontier writer must not see the user's CLAUDE.md, hooks, skills, plugins or MCP config.

---

### Task 1: Lantern Keep test directory

**Files:** Create `tests/acceptance/godot-lantern-keep/{test.yaml,brief.md,roadmap-prompt.md,duplication.yaml,arc-registry.yaml}`. Modify `tools/artifactory/acceptance.py` (optional `roadmap_prompt` and `probe` fields). Test in `tools/tests/test_acceptance.py`.

- [ ] `test.yaml`: name `godot-lantern-keep`, ecosystem `godot-csharp`, fixture `../../../fixtures/godot-blank`, `prompt: brief.md`, `roadmap_prompt: roadmap-prompt.md`, `probe: lantern`, `time_limit_s: 14400`, all 8 kits.
- [ ] `brief.md`: the spec's brief and contracts, written as the builder prompt (it is the none condition's prompt). Include "Use every module listed in `MODULES.md` for the job it does, instead of writing that functionality yourself." as capsule-room does.
- [ ] `roadmap-prompt.md`: the spec's writer rules, including the required `Modules: A, B` / `Modules: none` line in every bead description, the `gap` label, and "write the roadmap only; build nothing".
- [ ] `duplication.yaml`: copy capsule-room's. `arc-registry.yaml`: copy capsule-room's.
- [ ] `AcceptanceTest` gets `roadmap_prompt: str | None` and `probe: str | None` (default None). Test: loading lantern-keep gives both; loading capsule-room gives None for both.
- [ ] Commit `test: lantern keep acceptance test`.

### Task 2: Lantern probe mode

**Files:** Modify `tools/artifactory/godot_probe/CheckerProbe.cs` and `tools/artifactory/checks/godot.py`. Tests in `tools/tests/test_check_godot.py`.

- [ ] Probe mode `lantern`, selected by env `ARTIFACTORY_PROBE_MODE=lantern` (the checker sets it when `test.probe == "lantern"`). In this mode the probe:
  - changes to `res://rooms/courtyard.tscn` and runs the existing move/visible logic there;
  - loads each of `courtyard`, `hall`, `tower` and prints `PROBE rooms=true|false missing=<names>` (a room passes when a node in group `player` exists in it after one frame);
  - loads `hall.tscn`, puts the player next to the node in group `keeper`, sends the `interact` action, waits up to 2 s, and prints `PROBE dialogue=true|false problem=<why>` (true when a node in group `dialogue` is visible).
- [ ] `godot.py` adds `rooms` and `dialogue` checks (gating) and a static, informational `title_scene` check (main scene is not one of the room paths) only when `test.probe == "lantern"`.
- [ ] Tests:
  - capsule-room's checker check list is unchanged (names and order);
  - `_check_probe` parses the new lines;
  - `title_scene` passes and fails on fixture project.godot files;
  - a test marked `godot` builds a tiny 3D lantern-shaped fixture (three rooms, a keeper, a dialogue node shown on `interact`) and gets `rooms` and `dialogue` true.
- [ ] Commit `checker: lantern probe mode`.

### Task 3: bd in the trial

**Files:** Modify `tools/artifactory/harness.py`. Tests in `tools/tests/test_harness.py`.

- [ ] `bd_binary() -> Path` resolves the real binary per the Global Constraints; a clear error if missing.
- [ ] `bd_env(actor) -> dict` sets the metrics-off and actor variables (check `bd --help` / `bd config` for the exact names; prefer env over writing config).
- [ ] prepare_trial, when `roadmap != "none"`: copy `bd` into `trial.bin`, run `bd init --stealth --non-interactive` in the trial project with `bd_env("ornith")` and the trial HOME, and for `frontier` run `bd import <test_dir>/roadmaps/frontier.jsonl`.
- [ ] Tests (marked `godot` where they need bd): init leaves no tracked beads files (`git status --porcelain` clean after the fixture commit); import keeps ids and deps; `bd_env` output disables metrics.
- [ ] Commit `harness: bd in roadmap trials`.

### Task 4: Writing phase, bead loop and `--roadmap`

**Files:** Modify `tools/artifactory/harness.py`, `tools/artifactory/cli.py`, `tools/artifactory/result.py`. Tests in `tools/tests/test_harness.py`.

- [ ] `round --roadmap frontier|ornith|none` (default none), validated per the Global Constraints. `round.json` records `roadmap`.
- [ ] ornith: a writing session (prompt = `roadmap_prompt` + the brief) with limit `min(1200, remaining)`; export beads to `<trial>/roadmap.jsonl`. No beads created → one session with the brief, `roadmap_failed: true`.
- [ ] frontier and ornith build loop on the host, `bd` with `bd_env("ornith")`:
  - before each pick, reset `in_progress` beads to `open`;
  - pick the first `bd ready --json` bead; run a session with the bead-session prompt and the remaining time;
  - a bead not closed after its session is retried once, then set `blocked` with a note;
  - when nothing is ready but open/blocked beads remain and time is left, run stall sessions until none remain open or time is up.
- [ ] Trial JSON gains `roadmap` (`beads`, `closed`, `blocked`, `sessions`, `stall_sessions`, `roadmap_failed`). Export final bead state to `<trial>/beads-final.jsonl`.
- [ ] Tests (fake opencode via `opencode_argv`, a fake or real bd): loop order follows deps; an unclosed bead is retried once then blocked; a stall session runs when only blocked beads remain; time is never exceeded; ornith with zero beads falls back; none mode is unchanged.
- [ ] Commit `harness: roadmap conditions and bead loop`.

### Task 5: Frontier writer command

**Files:** Modify `tools/artifactory/cli.py`, `tools/artifactory/harness.py`. Create `tests/acceptance/godot-lantern-keep/roadmaps/.gitkeep`. Test in `tools/tests/test_harness.py`.

- [ ] `artifactory write-roadmap <test_dir> --writer claude [--model claude-opus-5-5]`: prepare a trial project as a frontier trial would (product, arc, bd, actor `roadmap-writer`), then run `claude -p --model <model>` in the sandbox with the writer prompt + brief. HOME is a fresh dir holding only a copy of the Claude credentials file; no CLAUDE.md, settings, hooks, skills, plugins or MCP config. Export to `<test_dir>/roadmaps/frontier.jsonl`.
- [ ] `--writer-argv` override for tests. Test: the fake writer sees a HOME with only the credentials file; the export lands at the path; exported records carry actor `roadmap-writer`, not the git user.
- [ ] Commit `harness: frontier roadmap writer`.

### Task 6: Roadmap scoring and docs

**Files:** Create `tools/artifactory/roadmap.py`; modify the CLI design spec and `docs/specs/2026-11-01-stitchability-standard-results.md` (a short "roadmap experiment" pointer). Test `tools/tests/test_roadmap.py`.

- [ ] `score_roadmap(jsonl_path, kits) -> dict`: parse each bead's `Modules:` line; report kits named, unknown names, beads without a `Modules:` line, whether a `gap`-labelled bead mentions dialogue, and bead counts.
- [ ] `artifactory roadmap-score <file>` prints it (text and `--json`).
- [ ] Tests on hand-written JSONL samples.
- [ ] Commit `feat: roadmap scoring`.

After the tasks: write the frontier roadmap with `write-roadmap`, have a fresh reviewer check it for code and prompt violations, commit it, then run the three conditions after round 9 (beads track the runs).
