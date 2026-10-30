# Stitchability Standard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Draft the stitchability standard, build two scripted acceptance tests (Godot capsule room, Go URL shortener) that run Ornith in opencode, and iterate the standard and modules until both tests pass 4 of 5 trials on the same revision.

**Architecture:** This repo holds the standard (markdown), a small Python tool (`tools/`) that validates descriptors, builds the module index, runs sandboxed trials and checks their results, plus fixtures, acceptance-test definitions and the Go sample modules. Godot kit changes happen in the existing kit repos on a `stitchability` branch. Trials run in bubblewrap with a throwaway HOME; git `insteadOf` and a file `GOPROXY` point module fetches at local mirrors, so the model sees real install commands but needs no credentials.

**Tech Stack:** Python 3.12+ via `uv` (PyYAML, pytest), bubblewrap, opencode v2.1.4, Godot 4.7 mono, .NET 10 SDK, Go 1.26.

**Spec:** `docs/specs/2026-10-30-stitchability-standard-design.md` (read it first; this plan argues from it).

## Global Constraints

- Consumer: opencode `--model agentbox/ornith-1.5-q4`, server `http://192.168.50.174:8080/v1`, 128K context. No other model is a consumer.
- The model gets only the fixed prompt and `MODULES.md` (index with preamble). No AGENTS.md, skills or extra opencode config in a trial.
- Five trials per test per round; a test passes at 4 of 5. Stop after 5 rounds even if not passed.
- Descriptor file: `module.yaml` at each module root (my call; YAML per the spec's default).
- Godot install command: `git submodule add -b stitchability git@repo.billbert.co:yalt/<Name>Kit.git addons/<Name>Kit`.
- Godot liveness marker: exactly `[<Name>Kit] live`, printed once per process with `GD.Print`, from initialisation or the required setup step.
- Go module paths: `repo.billbert.co/artifactory/<name>`, version `v0.1.0` first, `go 1.24` in `go.mod`.
- Foundation kits (final list, my call; PerfKit and BuildIdKit dropped to keep the index short): InputRemapKit, SettingsKit, CursorKit, DebugLogKit, DevConsoleKit, CrashKit, TransitionKit, RunSaveKit.
- Kit repos: local clones at `/data/fast/Projects/Tech/Games/Godot/Modules/<Name>Kit`, remote `git@repo.billbert.co:yalt/<Name>Kit.git`. Push only the `stitchability` branch. Never push `main` in this plan.
- Paid Claude work in this plan is pre-approved. Running a trial must never call a paid model.
- Git policy: commit steps in this repo run only if the operator approved commits for this execution (ask at handoff); otherwise leave changes staged and say so.

## Review Focus

1. **Model writes outside its trial directory** (InNetwork deleted ~42 GB of caches). Expect the sandbox to make every path except the project and trial HOME read-only or absent. Test: `test_sandbox_blocks_write_outside_project` (Task 5).
2. **Model or opencode never finishes.** Expect the harness to kill at the time limit, record `timeout`, and still run the checker. Test: `test_trial_timeout_still_checks` (Task 5).
3. **Godot hangs on a missing game assembly** (kit README warns runs hang, not fail). Expect the checker to build first and wrap every `godot` call in a timeout so a hang is a failed check. Test: `test_godot_run_timeout_is_failure` (Task 3).
4. **Model edits a kit and commits inside the submodule**, leaving a clean tree at an unpublished commit. Expect `modules_unmodified` to require the submodule HEAD to be reachable from the mirror's `stitchability` branch. Test: `test_unpublished_submodule_commit_fails` (Task 3).
5. **Model copies a kit folder instead of `git submodule add`**, or vendors/`replace`s a Go module. Expect "not installed" or "modified" with a detail naming the cause. Tests: `test_copied_kit_counts_as_not_installed` (Task 3), `test_replace_directive_fails` (Task 4).

---

### Task 1: Standard draft, descriptor loader and index builder

**Files:**
- Create: `standard/STANDARD.md`, `standard/profiles/godot-csharp.md`, `standard/profiles/go.md`, `standard/preamble.md`
- Create: `tools/pyproject.toml`, `tools/artifactory/__init__.py`, `tools/artifactory/descriptor.py`, `tools/artifactory/index.py`, `tools/artifactory/cli.py`
- Test: `tools/tests/test_descriptor.py`, `tools/tests/test_index.py`

**Interfaces:**
- Produces:
  - `Descriptor` (frozen dataclass): `name: str, ecosystem: Literal["godot-csharp","go"], version: str, summary: str, replaces: list[str], install: str, setup: list[str], entry: list[str], liveness: str, docs: str, example: str, test: str, path: Path`
  - `load_descriptor(module_dir: Path) -> Descriptor` — raises `DescriptorError(problems: list[str])` listing every problem at once
  - `build_index(descriptors: list[Descriptor], preamble: str) -> str`
  - CLI: `uv run --project tools artifactory index <module_dir>... -o <MODULES.md>` and `artifactory validate <module_dir>...` (exit 1 on any problem)

- [ ] **Step 1: Write the standard documents.** `STANDARD.md` holds the eight core rules from the spec's "core rules" section, ecosystem-neutral (no mention of Godot, C#, Go or any tool), under 600 words, versioned `Draft 0.1`. Each profile maps every rule to its concrete file, command or check, copied from the spec's profile sections and Global Constraints above. `preamble.md` is the consumer preamble, under 120 words: read this index before writing code; install only with each module's `install` command; never edit files inside an installed module; wire every module you install into the program's real entry point; if a module does what you need, use it instead of writing your own.

- [ ] **Step 2: Write failing tests** in `test_descriptor.py`:
  - `test_valid_descriptor_loads` — a fixture `module.yaml` with all fields loads; `replaces` is a list.
  - `test_missing_fields_all_reported` — omit `install` and `liveness`; `DescriptorError.problems` names both.
  - `test_summary_must_be_one_line_under_100_chars`
  - `test_replaces_needs_1_to_5_items_each_under_80_chars`
  - `test_godot_name_matches_folder` — `ecosystem: godot-csharp` in folder `FooKit` with `name: BarKit` fails.

  and in `test_index.py`:
  - `test_index_starts_with_preamble`
  - `test_index_lists_name_summary_replaces_install_for_each_module`, sorted by name
  - `test_index_for_eight_modules_under_2000_words`

- [ ] **Step 3: Run** `uv run --project tools pytest tools/tests -q`. Expected: FAIL (modules not defined).

- [ ] **Step 4: Implement `descriptor.py`, `index.py`, `cli.py`.** The index renders one `## <name>` section per module with summary, a "Use instead of writing:" bullet list from `replaces`, and the install command in a code block.

- [ ] **Step 5: Run tests.** Expected: all pass.

- [ ] **Step 6: Commit** `standard/ tools/` with message `feat: draft stitchability standard, descriptor and index tools`.

### Task 2: Fixtures and acceptance-test definitions

**Files:**
- Create: `fixtures/godot-blank/` (`project.godot`, `GodotBlank.csproj`, `.gitignore`), `fixtures/go-blank/` (`go.mod` with `module shortener`, `go 1.24`)
- Create: `tests/acceptance/godot-capsule-room/{prompt.md,test.yaml,duplication.yaml}`, `tests/acceptance/go-url-shortener/{prompt.md,test.yaml,duplication.yaml}`
- Create: `tools/artifactory/acceptance.py`
- Test: `tools/tests/test_acceptance.py`

**Interfaces:**
- Produces: `AcceptanceTest` dataclass `name, ecosystem, fixture: Path, prompt: str, modules: list[str], time_limit_s: int, duplication: dict[str, list[str]]` (module name → regex list); `load_acceptance(dir: Path) -> AcceptanceTest`.

- [ ] **Step 1: Create the Godot fixture** with Godot 4.7 mono: a C# project with no scenes and no main scene, `Godot.NET.Sdk` matching the installed editor. Verify: `cd fixtures/godot-blank && dotnet build` succeeds.

- [ ] **Step 2: Write the prompts.** Godot prompt (fixed from here on): build a room with a capsule player moved by WASD, wire up the foundation a bigger game would need using every module in `MODULES.md`; contracts: the player node is in group `player`, the main scene is set in `project.godot`, project builds with `dotnet build`. Go prompt: build a URL shortener using every module in `MODULES.md`; main package at `./cmd/shortener`; config from env `SHORTENER_ADDR` (default `:8080`) and `SHORTENER_DATA` (data file path); `POST /links` with JSON `{"url": "<url>"}` returns 201 and `{"code": "<code>"}`; `GET /<code>` returns 302 with `Location` set; unknown code returns 404; `GET /healthz` returns 200.

- [ ] **Step 3: Write `test.yaml`** — Godot: `modules` = the eight foundation kits, `time_limit_s: 7200`. Go: `modules: [config, kvstore, shortid, httpserver]`, `time_limit_s: 2700`. Write `duplication.yaml` regexes per module (for example SettingsKit: `ConfigFile\(\)`, `settings\.cfg`; RunSaveKit: `user://.*save`; Go config: `os\.Getenv\(`; Go kvstore: `os\.WriteFile|json\.NewEncoder\(f`). Patterns match project code outside installed modules only.

- [ ] **Step 4: Write failing test** `test_load_both_acceptance_tests` — loads both dirs; Godot has 8 modules, Go has 4; every regex compiles.

- [ ] **Step 5: Implement `acceptance.py`; run** `uv run --project tools pytest tools/tests -q`. Expected: pass.

- [ ] **Step 6: Commit** `fixtures/ tests/ tools/` — `feat: add acceptance test definitions and fixtures`.

### Task 3: Godot checker

**Files:**
- Create: `tools/artifactory/result.py`, `tools/artifactory/checks/godot.py`, `tools/artifactory/godot_probe/CheckerProbe.cs`
- Test: `tools/tests/test_check_godot.py`, test projects under `tools/tests/data/godot/`

**Interfaces:**
- Consumes: `AcceptanceTest`, `Descriptor`.
- Produces:
  - `CheckResult(name: str, passed: bool, detail: str)`, `TrialResult(test: str, trial: str, checks: list[CheckResult], reason: str | None)` with property `passed` (all checks pass and `reason is None`), `to_json() -> str`
  - `check_godot(project: Path, test: AcceptanceTest, mirrors: Path, branch: str, baseline: bool = False) -> TrialResult`
  - Check names, in order: `build`, `runs`, `player_moves`, `modules_installed`, `modules_live`, `modules_unmodified`, `no_duplication`.

- [ ] **Step 1: Write failing tests** using small hand-made projects in `tools/tests/data/godot/` (mark the slow ones `@pytest.mark.godot`):
  - `test_good_project_passes_all` — capsule moves on W, two stub kits installed as submodules from a temp bare mirror, each printing its marker.
  - `test_player_not_moving_fails_player_moves`
  - `test_missing_marker_fails_modules_live` — detail names the kit.
  - `test_copied_kit_counts_as_not_installed` — kit folder present, no `.gitmodules` entry; detail contains `copied, not submodule`.
  - `test_dirty_submodule_fails_unmodified`
  - `test_unpublished_submodule_commit_fails` — commit inside the submodule; HEAD not reachable from `<mirror>/<Kit>.git` branch `stitchability`.
  - `test_duplication_regex_hit_fails` — detail gives file:line.
  - `test_godot_run_timeout_is_failure` — a project whose autoload loops forever; `runs` fails within the timeout.
  - `test_baseline_mode_skips_live_and_marks_manual` — `modules_live` and `modules_unmodified` are reported with `detail` starting `manual:` and `passed=False`.

- [ ] **Step 2: Run** `uv run --project tools pytest tools/tests/test_check_godot.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement `CheckerProbe.cs`** (namespace `ArtifactoryChecker`): an autoload that at 1.0 s finds exactly one `Node3D` in group `player`, records its global position, injects `InputEventKey` press for `Key.W` (both `Keycode` and `PhysicalKeycode`) via `Input.ParseInputEvent`, releases at 2.0 s, repeats for `Key.D` from 2.0 to 3.0 s, prints `PROBE player_moves=<true|false> w=<dist> d=<dist>`, and quits at 3.5 s. Moves means each distance > 0.1 and the two direction vectors differ.

- [ ] **Step 4: Implement `check_godot`.** Work on a copy of the project. Build with `dotnet build` (timeout 600 s). Add the probe to the copy's `[autoload]`, then run `godot --headless --path <copy>` under a 60 s timeout. `runs` fails on non-zero exit, timeout, or any `ERROR:` / `Unhandled exception` line not present in a run of the blank fixture. Live = every module's marker appears in that run's stdout. Unmodified = clean `git status --porcelain` in the submodule and `git -C <mirror>/<Kit>.git merge-base --is-ancestor <HEAD> <branch>`. Duplication = the module's regexes over `*.cs`, `*.gd`, `project.godot` outside `addons/<Name>Kit/`.

- [ ] **Step 5: Run tests.** Expected: pass.

- [ ] **Step 6: Commit** — `feat: add Godot trial checker`.

### Task 4: Go sample modules, local proxy, Go checker

**Files:**
- Create: `samples/go/{config,kvstore,shortid,httpserver}/` each with `go.mod`, source, `*_test.go`, `README.md`, `module.yaml`, `example/main.go`
- Create: `tools/artifactory/goproxy.py`, `tools/artifactory/checks/go.py`
- Test: `tools/tests/test_goproxy.py`, `tools/tests/test_check_go.py`

**Interfaces:**
- Produces (Go APIs, all module paths `repo.billbert.co/artifactory/<name>`):
  - `config.Load(prefix string, dst any, file string) error` — struct tags `env:"ADDR" default:":8080"`; env `<PREFIX>_<TAG>` overrides the optional key=value file, which overrides the default.
  - `kvstore.Open(path string) (*Store, error)`; `(*Store) Get(key string) (string, bool, error)`; `(*Store) PutIfAbsent(key, val string) (bool, error)`; `(*Store) Close() error`. File-backed, atomic rewrite on write, safe for concurrent use.
  - `shortid.New(n int) (string, error)` — crypto-random base62.
  - `httpserver.Run(ctx context.Context, addr string, h http.Handler, opts ...Option) error` — mounts `GET /healthz`, shuts down gracefully on ctx cancel or SIGINT/SIGTERM; `httpserver.WithHealthCheck(func(context.Context) error) Option`.
  - `build_goproxy(module_dirs: list[Path], out: Path) -> None` (writes `@v/list`, `.info`, `.mod`, `.zip` per module version)
  - `check_go(project: Path, test: AcceptanceTest, proxy: Path) -> TrialResult`; check names: `build`, `tests`, `service_works`, `modules_installed`, `modules_live`, `modules_unmodified`, `no_duplication`.

- [ ] **Step 1: Write the four modules TDD-style** (failing `go test ./...` first, then code), each with a `module.yaml` that `artifactory validate` accepts, a README under 300 words with a "Wiring" snippet, and a runnable `example/main.go`. `replaces` must name the thing a model would hand-roll (for example kvstore: "storing key-value data in a JSON file").

- [ ] **Step 2: Verify modules.** Run `go test ./...` in each module dir and `uv run --project tools artifactory validate samples/go/*`. Expected: all pass.

- [ ] **Step 3: Write failing Python tests:**
  - `test_proxy_serves_modules` — `build_goproxy` into tmp; a temp module runs `go get repo.billbert.co/artifactory/kvstore@v0.1.0` with `GOPROXY=file://<tmp>`, `GONOSUMDB=repo.billbert.co/artifactory`, `GOFLAGS=-mod=mod`; exit 0.
  - `test_reference_solution_passes_all` — a reference shortener in `tools/tests/data/go/good/` passes every check.
  - `test_replace_directive_fails` — `modules_unmodified` fails, detail names `replace`.
  - `test_unused_module_fails_live` — module in `go.mod` but not in `go list -deps ./cmd/shortener`.
  - `test_wrong_status_code_fails_service_works` — `POST /links` returns 200 instead of 201.
  - `test_hand_rolled_store_fails_duplication`

- [ ] **Step 4: Implement `goproxy.py` and `checks/go.py`.** The service check starts `./cmd/shortener` with `SHORTENER_ADDR=127.0.0.1:<free port>` and `SHORTENER_DATA=<tmp file>`, waits up to 10 s for `/healthz`, then runs the create, redirect, 404 and health requests. Unmodified = `go mod verify` passes and `go.mod` has no `replace`. Live = every module path appears in `go list -deps ./cmd/shortener`.

- [ ] **Step 5: Run** `uv run --project tools pytest tools/tests -q`. Expected: pass.

- [ ] **Step 6: Commit** — `feat: add Go sample modules, local proxy and Go checker`.

### Task 5: Sandboxed trial harness

**Files:**
- Create: `tools/artifactory/sandbox.py`, `tools/artifactory/harness.py`; extend `cli.py`
- Test: `tools/tests/test_harness.py`

**Interfaces:**
- Consumes: `load_acceptance`, `build_index`, `check_godot`, `check_go`, `build_goproxy`.
- Produces:
  - `sandbox_command(project: Path, home: Path, ro_binds: list[Path], argv: list[str], env: dict[str, str]) -> list[str]` (bwrap argv)
  - `run_trial(test: AcceptanceTest, index_md: str, trial_dir: Path, mirrors: Path | None, proxy: Path | None, opencode_argv: list[str] | None = None) -> TrialResult`
  - `run_round(test_dir: Path, round_no: int, trials: int = 5, baseline: bool = False) -> RoundResult` where `RoundResult(test: str, round: int, results: list[TrialResult])` with `passes: int` and `met_bar: bool` (`passes >= 4`)
  - CLI: `artifactory mirror` (refresh bare mirrors of the eight kits into `results/mirrors/`), `artifactory round <test_dir> --round N [--trials 5] [--baseline]`
  - Layout: `results/<test>/round-<N>/trial-<K>/{project/,home/,transcript.jsonl,checker.json}` and `results/<test>/round-<N>/round.json`. `results/` is gitignored except `REPORT.md` files.

- [ ] **Step 1: Write failing tests** (`opencode_argv` lets tests substitute a shell script for the model):
  - `test_sandbox_blocks_write_outside_project` — a fake agent tries to write to `$REAL_HOME/x` and `/tmp/x`; both fail; writing in the project succeeds.
  - `test_trial_home_has_only_minimal_opencode_config` — `home/.config/opencode/opencode.jsonc` defines only the `agentbox` provider with `ornith-1.5-q4`; no `AGENTS.md`, skills or plugins.
  - `test_git_insteadof_points_at_mirror` — inside the sandbox, `git ls-remote git@repo.billbert.co:yalt/CrashKit.git` resolves to the mirror.
  - `test_trial_timeout_still_checks` — a fake agent that sleeps past `time_limit_s` is killed; `reason == "timeout"` and checks still ran.
  - `test_round_bar_is_four_of_five`

- [ ] **Step 2: Run tests.** Expected: FAIL.

- [ ] **Step 3: Implement.** Each trial copies the fixture to `trial-K/project`, runs `git init` and commits it, and writes `MODULES.md` at the project root. The sandbox:
  - read-only binds: `/usr`, `/etc`, `/lib*`, the godot binary and its real path, the dotnet install, `~/.nuget/packages`, the mirrors and the proxy
  - read-write: the project and the trial HOME
  - shares the network, needed to reach the llama server
  - HOME gitconfig: `url.file://<mirrors>/.insteadOf=git@repo.billbert.co:yalt/` and `protocol.file.allow=always`
  - Go env: `GOPROXY=file://<proxy>`, `GONOSUMDB=repo.billbert.co/artifactory`, `GOFLAGS=-mod=mod`

  Run `opencode run --model agentbox/ornith-1.5-q4 --auto --format json "<prompt>"` in the project dir, kill the process group at the time limit, then run the matching checker.

- [ ] **Step 4: Run tests.** Expected: pass. Then check against the real model: run `artifactory round tests/acceptance/go-url-shortener --round 0 --trials 1` once against the real model, to confirm opencode talks to ornith inside the sandbox and `dotnet`/`go` work there. Round 0 is a smoke run and is not scored.

- [ ] **Step 5: Commit** — `feat: add sandboxed trial harness`.

### Task 6: Godot baseline

**Files:**
- Create: `results/godot-capsule-room/baseline/REPORT.md`

- [ ] **Step 1: Mirror the kits at `main`** with `artifactory mirror`.
- [ ] **Step 2: Run** `artifactory round tests/acceptance/godot-capsule-room --round 0 --baseline --trials 5`. In baseline mode, the index is `/data/fast/Projects/Tech/Games/Godot/Modules/README.md` copied in as `MODULES.md`, and the unmodified check compares against `main`.
- [ ] **Step 3: Write the baseline report.** For each trial, record the scripted check results, then judge by reading the tree: which kits it installed, how it installed them, whether it wired them, and whether it edited them. Note where its failures match InNetwork's. Keep it under 500 words.
- [ ] **Step 4: Commit** `REPORT.md` — `docs: record Godot baseline`.

### Task 7: Bring the foundation kits to the standard

Repeat for each of the eight kits, in its local clone:

**Files (per kit, on branch `stitchability`):**
- Create: `module.yaml`
- Modify: the initialisation point, adding the marker:
  - autoload kits: `_Ready()` of the autoload script (InputRemapManager, SettingsManager, InputModeManager, DebugLogger, DevConsoleManager, TransitionManager)
  - CrashKit: `CrashHandler.Initialize()`
  - RunSaveKit: the `SaveSlot` constructor, guarded by a static flag
- Modify: `README.md`:
  - Install section becomes only the submodule command from Global Constraints.
  - Delete every "copy the folder" and "edit in place" instruction.
  - Add a `## Wiring` section with a complete minimal snippet that triggers the marker.

- [ ] **Step 1:** `git -C <kit> switch -c stitchability main`.
- [ ] **Step 2: Add the marker** `GD.Print("[<Name>Kit] live");`, once per process.
- [ ] **Step 3: Write `module.yaml`** with `liveness: "prints [<Name>Kit] live at startup"`, and the README changes. `setup` lists the exact `project.godot` autoload line, or the init call. Keep it as short as the kit allows.
- [ ] **Step 4: Verify.**
  - `uv run --project tools artifactory validate <kit>` passes.
  - `cd /data/fast/Projects/Tech/Games/Godot/Modules/<Name>Kit.demo && dotnet build && godot --headless --path . -- --smoke` exits 0, and the output contains the marker.
  - After all eight kits are done, run `/data/fast/Projects/Tech/Games/Godot/Modules/tools/verify-library.sh` with the eight kits on `stitchability`. Expected: clean.
- [ ] **Step 5:** Commit in the kit repo with message `feat: stitchability descriptor, liveness marker, submodule-only install`, then `git push -u origin stitchability`.

### Task 8: Revision rounds (repeat for N = 1..5)

**Files:**
- Create: `results/round-<N>/REPORT.md`
- Modify as findings dictate:
  - `standard/*`
  - kit `stitchability` branches
  - `samples/go/*`: bump the version, `v0.1.N`, on any change, and rebuild the proxy

- [ ] **Step 1:** Refresh the mirrors. Build `MODULES.md` from the current descriptors for each test.
- [ ] **Step 2: Run both tests.** `artifactory round tests/acceptance/godot-capsule-room --round N` and `artifactory round tests/acceptance/go-url-shortener --round N`.
- [ ] **Step 3: Review.** Dispatch a reviewer subagent per test with the round's `checker.json` files, transcripts and project trees. It should report, per failed check, where in the transcript the model went wrong and which rule, doc or module surface could have prevented it. It should also flag any hand-rolled duplication the regex missed, and add those patterns to `duplication.yaml`.
- [ ] **Step 4: Write `REPORT.md`** (under 600 words): the pass counts, the top failure modes with evidence, and the changes made for the next round, each tied to a failure.
- [ ] **Step 5: Make the changes.** Never change the prompts, the fixtures or the pass bar. If a kit API change is needed beyond docs, descriptor or marker, make it on `stitchability` and rerun that kit's demo smoke test.
- [ ] **Step 6: Decide whether to stop.** Stop if both tests have `met_bar` in this round, or if N = 5. Otherwise go to round N+1.

### Task 9: Lock the standard and hand back

**Files:**
- Modify: `standard/STANDARD.md` (version `1.0`), `standard/profiles/*`
- Create: `docs/specs/<date>-stitchability-standard-results.md`

- [ ] **Step 1:** If both tests met the bar in the same round, mark the standard `1.0`. List any rule the rounds never exercised as unproven.
- [ ] **Step 2: Write the results doc.** Cover the baseline against the final round, what changed each round and why, the final descriptor fields, the open conflicts (the kit catalog's `Log.cs` retargeting, the 26 kits not yet converted), and what sub-project 2 should build around.
- [ ] **Step 3: Hand back to the operator.**
  - Point them at the best passing Godot trial, which the spec says they play by hand.
  - If the bar was met: ask before merging the eight `stitchability` branches to `main`, and before changing the GodotKits catalog README.
  - If the bar was not met after round 5: present the results doc, and do not merge.
