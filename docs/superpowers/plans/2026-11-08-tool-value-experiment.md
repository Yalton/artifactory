# Tool-value experiment implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the same 4-bead Go link service under four conditions (control, artifactory, arc, both), 3 trials each, and score every finished project the same way.

**Architecture:** Extend the existing trial harness (`tools/artifactory/harness.py`) with a Go "experiment" runner. It prepares each condition's project, runs the existing bead loop on a frozen 4-bead roadmap, and checks with an extended Go checker. Kits stay offline: the per-test file GOPROXY for `go get`, plus a `dir:` catalog for the CLI.

**Tech Stack:** Python 3 (harness, pytest via `cd tools && uv run pytest -q`), Go 1.26 (kits, CLI), arc (built by `build_arc`), bd, opencode with local Ornith.

**Spec:** `docs/superpowers/specs/2026-11-08-tool-value-experiments-design.md`

## Global Constraints

- Godot and Python rounds behave exactly as before. The existing tests in `tools/tests/` must keep passing unchanged, except `test_harness.py`'s no-`mcp` assertion, which may allow the one artifactory MCP entry when asked for.
- The session prompt is the existing `BEAD_PROMPT` in every condition. No condition gets prompt text the others lack.
- Bead text never names a module, library, tool, `AGENTS.md`, `MODULES.md` or a package layout.
- The agent sandbox keeps its network rules: egress only to the llama endpoint.
- The checker scores every condition the same way. arc must be available to the checker in every condition, but on the agent's PATH only in `arc` and `both`.
- Local model only (`agentbox/ornith-1.5-q4`).
- Run bd in tests only with `DO_NOT_TRACK=1` and a non-user HOME, as the harness already does.

## Review Focus

1. **An MCP server that dies or hangs at opencode start.** opencode must still run the session, and the transcript must show it. Test: the generated config names `artifactory mcp`, and the command resolves on the sandbox PATH.
2. **A project that never builds.** Every check must report "not run: build failed" or a finding, never crash the checker. Test with an empty project.
3. **The arc gate in a project without `.arch`** (control, artifactory). The checker installs the held registry into its copy and still reports boundary findings. Test with a fixture that violates one boundary.
4. **A transcript with an `artifactory` command in a file path or quoted prose.** It must not count as tool use. Count only shell command fields and MCP tool calls. Test with both.
5. **Interleaved runs.** One trial's failure (an exception in prepare or check) must not stop the remaining trials. It is recorded as that trial's result. Test with a fake runner that raises once.

---

### Task 1: kvstore 0.2.0 (Put, Delete)

**Files:**
- Modify: `samples/go/kvstore/kvstore.go`, `samples/go/kvstore/kvstore_test.go`, `samples/go/kvstore/module.yaml` (version 0.2.0; entry adds `Store.Put`, `Store.Delete`), `samples/go/kvstore/README.md` (the Wiring section mentions both)

**Interfaces:** Produces `func (s *Store) Put(key, val string) error` (insert or replace, flushed like PutIfAbsent) and `func (s *Store) Delete(key string) (bool, error)` (true if the key existed; flushed only if it did).

- [ ] Tests first: `TestPutReplacesAndPersists` (Put twice, reopen, get the second value) and `TestDeleteRemovesAndPersists` (Delete an existing key gives true; reopen, the key is gone; Delete a missing key gives false).
- [ ] Implement.
- [ ] `cd samples/go/kvstore && go test ./...` passes; `go run ./cmd/artifactory validate samples/go/kvstore` exits 0.
- [ ] Commit.

### Task 2: the go-link-service test

**Files:**
- Create:
  - `fixtures/go-links-blank/go.mod` (`module links`, `go 1.24`)
  - `fixtures/go-links-arc/` (only the arc overlay: one-line `doc.go` in `cmd/links` (`package main`), `internal/httpapi`, `internal/links` and `internal/store`)
  - `tests/acceptance/go-link-service/test.yaml`
  - `tests/acceptance/go-link-service/prompt.md` (the four beads' contracts in one page, for reference; not sent to the model)
  - `tests/acceptance/go-link-service/duplication.yaml` (copy of `go-url-shortener`'s)
  - `tests/acceptance/go-link-service/arc-registry.yaml`
  - `tests/acceptance/go-link-service/roadmaps/frontier.jsonl`
- Modify: `tools/artifactory/acceptance.py`, `tools/tests/test_acceptance.py`

**Interfaces:** `AcceptanceTest` gains:
- `main_pkg: str = "./cmd/shortener"`;
- `kit_checks: str = "gate"` (or `"report"`);
- `service: str = "shortener"` (or `"links"`);
- `arc_overlay: Path | None = None`;
- `conditions: tuple[str, ...] = ()`.

They are read from test.yaml keys of the same names; `arc_overlay` is resolved relative to the test dir.

`test.yaml` values:
- `ecosystem: go`, `fixture: ../../../fixtures/go-links-blank`, `arc_overlay: ../../../fixtures/go-links-arc`;
- `modules: [config, httpserver, shortid, kvstore]`;
- `main_pkg: ./cmd/links`, `kit_checks: report`, `service: links`;
- `time_limit_s: 7200`, `conditions: [control, artifactory, arc, both]`.

The roadmap: 4 issues in bd's export format (copy the field set from `tests/acceptance/godot-lantern-keep/roadmaps/frontier.jsonl`), with ids `links-1` to `links-4`, each depending on the one before it ("blocks" dependencies).
- Titles and descriptions follow the spec's four beads word for word in substance.
- Each description ends with a "Check:" paragraph giving the commands that prove it (curl lines against the running binary, `go test ./...`).
- No description names a module, library, tool, `AGENTS.md`, `MODULES.md`, package or directory, except `./cmd/links`, the build target.

The arc registry: the four concepts from the spec, with paths `cmd/links/**`, `internal/httpapi/**`, `internal/links/**` and `internal/store/**`. Boundaries:
- `internal/httpapi` may not import `internal/store`;
- `internal/store` may not import `internal/httpapi`;
- `internal/links` may not import `internal/httpapi`.

Follow `tests/acceptance/godot-lantern-keep/arc-registry.yaml`'s format and arc's `SPEC.md`. It must pass `arc validate` against the fixture plus overlay (check with the built arc).

- [ ] Test first: `test_load_link_service` loads the new test and asserts each new field's value. `test_defaults_unchanged` loads `go-url-shortener` and asserts the defaults.
- [ ] Implement the loader fields and write the files.
- [ ] Prove the roadmap imports: a test that runs `bd init --stealth --non-interactive` and `bd import` on a temp git repo (`DO_NOT_TRACK=1`, temp HOME) and `bd ready` lists `links-1` only. Skip the test if bd is missing.
- [ ] Prove the registry validates: a test that copies fixture plus overlay plus registry to a temp dir and runs `arc validate`. Skip if arc cannot be built.
- [ ] Prove no bead text names a forbidden word: a test that scans `frontier.jsonl` descriptions for `module`, `kit`, `artifactory`, `arc`, `AGENTS`, `MODULES`, `internal/` and package names, case-insensitive, and fails on a hit.
- [ ] `cd tools && uv run pytest -q` passes. Commit.

### Task 3: conditions and the experiment runner (harness)

**Files:** Modify `tools/artifactory/harness.py`, `tools/artifactory/cli.py`, `tools/tests/test_harness.py`.

**Interfaces:**
- Consumes the Task 2 fields.
- Produces `run_experiment(test_dir: Path, round_no: int, trials: int = 3, conditions: list[str] | None = None, *, results_root: Path | None = None, opencode_argv: list[str] | None = None, arc_src: Path | None = None) -> dict[str, RoundResult]`, and CLI `artifactory experiment TEST_DIR --round N [--trials 3] [--conditions a,b]`.

Behaviour:
- **Conditions:** `CONDITIONS = ("control", "artifactory", "arc", "both")`. `run_experiment` only accepts Go tests whose `conditions` is non-empty. Every condition uses the frozen roadmap (`roadmap="frontier"` loop semantics).
- **Order:** trials run interleaved: for k in 1..trials, for c in conditions. Output goes to `results/<test>/round-<N>-<condition>/trial-<k>/`. Each condition's `round.json` is written after each of its trials, and gains `"condition": c`. `RoundResult` gets an optional `condition: str | None = None`, emitted only when set, so old round.json shapes are unchanged.
- **Failures:** an exception while preparing or checking one trial is recorded as that trial's result, with `reason="infrastructure: <exc>"`, and the run continues.
- **Catalog:** built once per run at `results/go-catalog/<test>/`, a fresh copy of every `samples/go/*` and `samples/python/*` kit dir, bound read-only in agent sandboxes. The file GOPROXY is built as today (`build_goproxy(_go_sample_dirs(), …)`).
- **Project setup per condition**, on fixture copy plus `git init`:
  - `arc` and `both`: copy the overlay files in, copy `arc` into the trial bin, copy `arc-registry.yaml` to `.arch/registry.yaml`, run `arc init --opencode --no-detect --ci none`, and delete `.git/hooks/pre-commit`. This is the same as `_product_setup`'s arc part; factor it into `_arc_setup` and call it from both places.
  - `artifactory` and `both`: copy the CLI into the trial bin, `mkdir .opencode`, then run `artifactory init --ecosystem go --provider dir:<catalog> --project <p>` (arc auto, so `both` registers kits once installed).
  - `control`: neither.
  - All conditions: initial commit, record `base_commit` (always, not only arc), and bd init plus import of `roadmaps/frontier.jsonl`.
- **opencode config:** `opencode_config(mcp: bool = False)`; with `mcp=True` it adds `"mcp": {"artifactory": {"type": "local", "command": ["artifactory", "mcp"], "enabled": true}}`. Only `artifactory` and `both` pass `True`. Adjust `test_harness.py:112` so the no-`mcp` assertion holds for the default and a new test checks the `True` shape.
- **The arc binary for the checker:** `build_arc` output is copied to `<trial>/checker-bin/arc` in every condition, and the checker's PATH puts `checker-bin` after `trial.bin`. The agent never sees `checker-bin`.
- **Loop:** the bead loop runs exactly as for Godot frontier rounds (`bead_loop`), with `test.time_limit_s` as the shared deadline.
- **checker_command for Go:** also passes `--main-pkg`, `--arc-registry <test.dir/arc-registry.yaml>` and `--arc-base <base_commit>`.

Steps:
- [ ] Tests first, with the fake-opencode pattern `test_harness.py` already uses for the bead loop:
  - `test_experiment_conditions_setup`: per condition, assert bin contents (artifactory, arc), `.arch`, `.opencode/skills/artifactory/SKILL.md`, `artifactory.yaml` with no modules, the opencode config mcp key, the overlay files only in the arc conditions, and bd ready = `links-1`.
  - `test_experiment_interleaves_and_survives_failure`: a fake runner records order and raises once; the run continues and the failure is recorded.
  - `test_round_json_condition_field`: present when set, absent otherwise.
- [ ] Implement.
- [ ] `cd tools && uv run pytest -q` passes. Commit.

### Task 4: Go checker for the link service

**Files:** Modify `tools/artifactory/checks/go.py`, `tools/artifactory/cli.py` (check: `--main-pkg`, `--arc-registry`, `--arc-base` for Go), `tools/tests/test_check_go.py`. Create `tools/artifactory/checks/consistency.py`, `tools/tests/test_consistency.py`.

**Interfaces:** `check_go(project, test, proxy, *, arc_registry: Path | None = None, arc_base: str | None = None) -> TrialResult`. The main package comes from `test.main_pkg`. The order of check names is unchanged for `service == "shortener"`.

Behaviour:
- **Kit checks** (`modules_installed`, `modules_live`, `no_duplication`) are non-gating when `test.kit_checks == "report"`, using the `gating` flag `CheckResult` already has. `modules_unmodified` stays gating.
  - `modules_live` detail names which kits are live, as `live: a, b; not live: c`.
  - `no_duplication` counts hits only for kits that are not live.
- **`service_works` for `service == "links"`:** start the binary with `LINKS_ADDR=127.0.0.1:<free port>`, `LINKS_DATA=<tmp>/links.json`, `LINKS_ADMIN_TOKEN=secret-token`. Assert:
  - `GET /healthz` returns 200.
  - Create gives 201 and a code; redirect gives 302 and the right Location; an unknown code gives 404.
  - `ttl_s: 1`, wait 2 s, gives 410.
  - Two redirects then `GET /links/<code>/stats` give 200 and `clicks == 2` with the url.
  - `DELETE` without a token gives 401, with a wrong token 401, with the right token 204; then 404.
  - SIGTERM, the process exits within 5 s; restart, an earlier link still redirects.

  The detail names the first failing step. Split this into one CheckResult per bead (`bead1_skeleton`, `bead2_links`, `bead3_expiry_stats`, `bead4_delete`), all gating, so the report shows which beads work.
- **Consistency** (`consistency.py`, all non-gating; each takes the project copy, reads non-test `.go` files outside `vendor/` and dot-dirs, and returns a CheckResult):
  - `config_one_place`: the set of directories (packages) containing `os.Getenv(`, `os.LookupEnv(`, `os.Environ(` or `config.Load(` has at most 1 member.
  - `storage_one_place`: the set of packages containing `os.Open(`, `os.OpenFile(`, `os.ReadFile(`, `os.WriteFile(`, `os.Create(` or `kvstore.Open(`, excluding `_test.go`, has at most 1 member.
  - `handlers_no_file_io`: no file that contains `http.HandleFunc`, `.HandleFunc(`, `.Handle(` or a `func(w http.ResponseWriter` also contains one of the file calls above.
  - `no_duplicate_funcs`: no two function bodies, whitespace-normalized and at least 3 lines, are identical across the project. Use `go/ast` through a small Go helper run with `go run`, or a brace-matching scan; your choice, but test it.

  Each detail lists the offending packages or files.
- **`arc_gate`** (non-gating), when `arc_registry` and `arc_base` are given: in the copy, put `arc_registry` at `.arch/registry.yaml` (replacing any), commit `--allow-empty --no-verify`, run `arc gate --base <arc_base> --json`, and keep only boundary findings. Find the finding group field from arc's gate JSON and `checks/godot.py` `_check_arc_gate`. Passed means 0 boundary errors; the detail is the count and up to 2000 characters of findings.
  - Base-commit caveat: the arc conditions' base commit already has a registry and overlay, and the control's has neither. The gate diffs against the base, so boundary findings must be computed over all Go files, not only changed ones. If `arc gate` only checks changed files, base it on the empty tree (`git hash-object -t tree /dev/null`) instead, and note it in a code comment.

Steps:
- [ ] Tests first:
  - consistency checks on small temp trees: pass and fail for each, plus the Review Focus case of an empty project;
  - the links service against a tiny Go server written in the test (one correct, one that fails bead 3);
  - `arc_gate` on a temp project with one boundary violation, without `.arch` in the input. Skip if arc cannot be built.
  - `test_check_go.py`'s existing url-shortener cases keep passing.
- [ ] Implement.
- [ ] `cd tools && uv run pytest -q` passes. Commit.

### Task 5: tool-use counting and blind export

**Files:** Create `tools/artifactory/tooluse.py`, `tools/tests/test_tooluse.py`, `tools/artifactory/blind.py`, `tools/tests/test_blind.py`. Modify `tools/artifactory/harness.py` (record `tool_use` per trial in checker.json, like `arc_denials`), `tools/artifactory/result.py` (an optional `tool_use: dict | None` field, emitted only when set), `tools/artifactory/cli.py` (`blind-export`).

**Interfaces:**
- `count_tool_use(transcripts: list[Path], proxy: Path | None) -> dict` returns `{"artifactory": {subcommand: n}, "mcp": {tool: n}, "arc": {subcommand: n}, "proxy_snoop": n}`.
  - Read the opencode JSON event shape from an existing transcript under `results/` (tool name and input fields).
  - Shell commands are the `command` input of shell or bash tool calls. Count `artifactory X` and `arc X` only at a command-word position: start of line, or after `&&`, `;`, `|` or `$(`.
  - MCP calls are tool names prefixed `artifactory_`; check the real prefix opencode uses for MCP tools in its source or docs, and pin it in a test.
  - `proxy_snoop` counts shell commands mentioning the proxy path, `GOPROXY` or `go env`.
- `blind_export(results_test_dir: Path, round_no: int, conditions: list[str], out: Path, seed: int) -> Path` copies each `round-<N>-<c>/trial-<k>/project` to `out/<label>/`, where labels are `P01`… in a seeded shuffle.
  - It removes `.arch`, `.beads`, `.opencode`, `.claude`, `.agents`, `.git`, `artifactory.yaml`, `MODULES.md`, `AGENTS.md` and `ARCHITECTURE.md`, and the overlay's `doc.go` files only when they are still exactly one line.
  - It writes `out/../key.json` (label to condition and trial) outside `out`, and returns the key path.
  - CLI: `artifactory blind-export results/go-link-service --round N --out DIR [--seed S]`.

Steps:
- [ ] Tests first:
  - command-word counting, including the Review Focus case of an `artifactory` path in prose, and MCP prefix counting;
  - blind export removes every listed path, keeps code, and puts the key outside `out`.
- [ ] Implement.
- [ ] `cd tools && uv run pytest -q` passes. Commit.

### After the tasks (controller, not a subagent task)

1. Merge, then run the smoke round: `uv run --project tools artifactory experiment tests/acceptance/go-link-service --round 0 --trials 1`, with all four conditions, one trial each. Check by hand:
   - each condition's setup;
   - transcripts show the session ran;
   - `artifactory` and `both` show the MCP server started;
   - the checker produced every check.

   Fix harness bugs only. Then delete `results/go-link-service/round-0-*`.
2. Freeze: commit, record the commit, and start the real run in the background: `--round 1 --trials 3`. From then on, no intervention (bd memory `experiment-no-intervention`).
3. When it finishes: blind export, blind review by a fresh reviewer subagent, the report `results/go-link-service/REPORT.md`, and beads for every tool problem found.
