# arc Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make arc the optional enforcer of module rules (never edit, wire every module, use instead of rebuilding) for projects that install artifactory modules, and measure it in trials.

**Architecture:** arc gains a generic `modules:` registry section with a write command, a hook deny, a gate check and guidance in brief, find, render and triage. artifactory calls `arc module set|rm|list` when arc is present and trims the three module bullets from its preamble. The trial harness gains `--product` (the CLI runs inside trials) and `--arc` modes.

**Tech Stack:** Go (arc: stdlib + yaml.v3 + doublestar; artifactory: existing deps), Python harness (uv, pytest).

**Spec:** `docs/superpowers/specs/2026-11-02-arc-integration-design.md` (in the Artifactory repo). arc's own `SPEC.md` is updated in Task 1 and binds arc tasks 2–6.

**Repos:**
- arc: worktree `/home/yalt/Documents/Projects/Tech/AI/arc-wt-modules`, branch `modules`, target `main`. Remotes: `origin` (Forgejo, primary) and `github`.
- Artifactory: worktree `/data/fast/Projects/Tech/AI/Artifactory-wt-arc`, branch `arc-integration`, target `main`.

## Global Constraints

- arc: `SPEC.md` is the source of truth and is changed first (Task 1). No new packages. Dependencies stay stdlib, `gopkg.in/yaml.v3` and `github.com/bmatcuk/doublestar/v4`. arc never calls an LLM and never runs project code. The `go list` calls arc already makes for boundaries are allowed.
- arc: every command takes `--json`. Exit codes: 0 ok, 1 violations, 2 usage or config error. Hooks always exit 0, and any internal error allows the call with a warning.
- arc tests use real-git fixture repos in temp dirs. At least one fixture has a real submodule (`git -c protocol.file.allow=always submodule add <local bare repo> addons/Kit`).
- artifactory: the CLI conventions stay (`--json`, 0/1/2, logic in `internal/app` shared by the CLI and MCP). The standard text lives only in `standard/`.
- arc knows nothing about artifactory: no `artifactory.yaml`, ecosystem names or provider strings in arc code.
- Every commit ends with a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Verification: arc runs `go vet ./... && go test ./... && go run ./cmd/arc gate --all` (arc dogfoods its gate; new files must be owned in arc's own `.arch/registry.yaml`). Artifactory runs `go vet ./... && go test ./...` and `uv run --project tools pytest tools/tests -q -m "not godot"`.

## Review Focus

1. **A write inside a submodule.** A write to `addons/Kit/x.cs`, where `addons/Kit` is a submodule, must be denied: the hook resolves the superproject. Test: Task 4.
2. **A catch-all concept `**` alongside modules.** Files under module paths belong to the module, and new files elsewhere are owned by the concept and allowed. Test: Task 2 (Owner precedence) and Task 4 (no deny for a new `Player.cs`).
3. **A module wired only by an autoload line in `project.godot`.** The gate counts it as wired, because the leading identifier of an `entry` matches. Test: Task 5.
4. **Missing or old arc.** With a registry present but no `arc module list`, artifactory warns and keeps the full preamble. With arc present, registration failures are warnings and the install still succeeds. Test: Task 8.
5. **Registry comments and order survive `arc module set/rm`.** Edits are node-level. Test: Task 3 (golden comparison of a commented registry).

---

## arc tasks

### Task 1: SPEC.md for modules

**Files:** Modify `SPEC.md` (arc worktree). Update these sections: "Registry schema", "Commands" (new `arc module`), `arc brief`, `arc find`, `arc gate` (new check `modules`, approval rules), `arc render`, `arc hook`, `arc triage`, `arc validate`, the built-in ignore list (add `.gitmodules`), and "Code layout" if a file list is given.

- [ ] Write the `modules:` schema and validation rules from the design's "arc: a `modules:` registry section", "enforcement", "guidance" and "write command" sections. Restate them in SPEC's voice. Keep the field names exactly: `id summary paths covers entry import rules source`.
- [ ] State precedence: module paths win over concept paths. `Owner()` returns no concept for a module path. A new `ModuleOf(path)` returns the module.
- [ ] Gate check id: `modules`. Finding messages are fixed strings:
  - `module <id>: file changed under module path`
  - `module <id>: submodule has local changes`
  - `module <id>: go.mod replaces <import>`
  - `module <id>: not wired (no reference to <entries> outside module paths)`
- [ ] Hook deny reason, fixed prefix: `<path> is inside installed module <id>; do not edit it.` The rules and `Use its public surface: <entry list>.` follow.
- [ ] Commit `spec: modules section for installed third-party code`.

**Done when** SPEC covers every behaviour that Tasks 2–6 implement. A reviewer checks the SPEC against the design doc.

### Task 2: Registry schema, validation and ownership

**Files:** Modify `internal/registry/registry.go`, `internal/registry/validate.go`, `internal/registry/files.go` (gitlinks), and arc's `.arch/registry.yaml` if new files need owners. Tests go in `internal/registry/*_test.go` and `testdata/registry/`.

**Interfaces produced:**
- `type Module struct { ID, Summary string; Paths, Covers, Entry []string; Import string; Rules []string; Source string }`, with yaml tags matching the field names, and a `Registry.Modules []Module` field.
- `func (r *Registry) ModuleOf(path string) (*Module, bool)`.
- `Owner(path)` returns no concept for a path under a module.
- The built-in ignore list gains `.gitmodules`.

- [ ] Tests:
  - an unknown key in a module entry is still an error;
  - a duplicate id is an error;
  - a glob matching nothing is an error;
  - `addons/Kit/**` validates against a repo where `addons/Kit` is only a gitlink;
  - a module with neither `entry` nor `import` is an error;
  - `**` concept plus a module: `Owner("addons/Kit/a.cs")` is nil and `ModuleOf` finds Kit, while `Owner("Player.cs")` is the concept;
  - overlap validation does not fire between a concept and a module.
- [ ] Implement. RepoFiles, or the glob-matching helper validation uses, must expose gitlink paths, so that `dir/**` matches a gitlink `dir`. Confirm doublestar's behaviour for `dir/**` against `dir` in a test.
- [ ] Commit `feat(registry): modules section`.

### Task 3: `arc module set|rm|list`

**Files:** Create `cmd/arc/module.go` and `cmd/arc/module_test.go`, and register the command in `cmd/arc/main.go`. Put the node-editing helper in `internal/registry` (for example `internal/registry/edit.go`). Golden files go in `testdata/registry/`.

**Interfaces produced (CLI):**
- `arc module set <id> --summary S [--path G]... [--covers C]... [--entry E]... [--import P] [--rule R]... [--source S] [--json]`
- `arc module rm <id> [--json]`
- `arc module list [--json]`, which prints `{"modules":[Module...]}`.

After a successful set or rm the command validates. If validation fails it restores the previous file, prints the problems and exits 1. On success it runs render, as `arc render` does.

- [ ] Tests:
  - set adds an entry to a commented registry, and a golden file shows the comments kept;
  - set again replaces the entry in place;
  - rm removes it;
  - set with a glob that matches nothing exits 1 and leaves the file byte-identical;
  - list `--json` round-trips;
  - set creates the `modules:` key when it is absent;
  - ARCHITECTURE.md is re-rendered after set.
- [ ] Implement with `yaml.Node` edits. Never marshal the whole registry struct back to disk.
- [ ] Commit `feat(cli): arc module set, rm and list`.

### Task 4: Hook

**Files:** Modify `internal/hook/hook.go` (findRoot, preWrite, postShell, briefContext) and `internal/gitx/gitx.go` if a superproject helper belongs there. Tests go in `internal/hook/hook_test.go`, with recorded payloads under `testdata/hooks/` if new shapes are needed.

- [ ] Tests, on a fixture repo with a `**` concept, module Kit at `addons/Kit/**` as a real submodule, and a second vendored module `vendor/lib/**`:
  - a PreWrite to `addons/Kit/a.cs` is denied, with a reason starting `addons/Kit/a.cs is inside installed module Kit; do not edit it.`;
  - a PreWrite to `vendor/lib/x.go` is denied;
  - a PreWrite of a new `Player.cs` is allowed;
  - the first allowed write of a session carries `Installed modules (use, never edit): Kit, lib`, once per session;
  - a post-shell after `echo x >> addons/Kit/a.cs` gives feedback naming Kit (dirty submodule);
  - a post-shell after editing `vendor/lib/x.go` gives feedback;
  - a write whose cwd is inside the submodule still finds the superproject registry.
- [ ] Implement. findRoot tries `git rev-parse --show-superproject-working-tree`, then falls back to `--show-toplevel`. Do this for all three adapters; they share Decide.
- [ ] Commit `feat(hook): protect installed modules`.

### Task 5: Gate check `modules` and approval

**Files:** Create `internal/gate/modules.go` and `internal/gate/modules_test.go`, and append the check to `Checks` in `internal/gate/gate.go`. Modify `internal/gate/approval.go`.

- [ ] Tests:
  - a changed vendored file is a finding;
  - a dirty submodule is a finding;
  - a moved submodule pointer with clean content is not a finding;
  - `replace example.com/m => ../m` in go.mod for a module with `import: example.com/m` is a finding;
  - wiring:
    - an entry `InputModeManager.Instance` referenced in `Main.cs` is wired;
    - only `InputModeManager="*res://addons/Kit/InputModeManager.cs"` in `project.godot` is wired, through the leading identifier;
    - a reference only inside module paths is not wired;
    - a reference only in an ignored file is not wired;
    - a go module with `import` that a main package imports is wired, and one that is not imported is not wired. Skip this case if `go` is absent.
  - approval: removing a module entry, or narrowing its paths, in `--base` mode without ARC_APPROVED is a finding, and adding one is not.
- [ ] Implement. The word match uses `\b<ident>\b` over tracked, non-ignored text files outside module paths, and skips binary and large files the same way other checks do. For `go list -deps`, list the main packages with `go list -f '{{if eq .Name "main"}}{{.ImportPath}}{{end}}' ./...`, then `go list -deps <mains>`.
- [ ] Commit `feat(gate): modules check`.

### Task 6: Brief, find, render and triage

**Files:** Modify `internal/brief/brief.go`, `internal/symbols/find.go` (or wherever `arc find` ranks), `internal/registry/render.go`, and `internal/beads` (triage). Also update `cmd/arc/find.go` and the triage output if they format results. Tests and goldens go in `testdata/brief`, `testdata/render`, and the find and triage tests.

- [ ] Tests:
  - the bare brief has a Modules section listing `id — summary`, entry and rules, cut to a token cap with `(N more: arc brief --modules)`;
  - `arc brief --modules` prints all modules;
  - a path brief includes a module whose covers words appear in the concept summary or the bead text;
  - `arc find mouse cursor stack` ranks the module whose covers match first, tagged `module`, with the text `use this; do not reimplement`;
  - render adds a Modules table to ARCHITECTURE.md and these exact three snippet lines when the registry has modules:
    - `- Use an installed module (listed by \`arc brief\`) before writing your own version of what it covers.`
    - `- Never edit files inside an installed module; configure or wrap it through its public surface.`
    - `- Wire every installed module into the program's real entry point.`
  - with no modules, render output is byte-identical to today's (golden unchanged);
  - triage flags a bead whose text matches a module's covers with `module <id> covers this`.
- [ ] Implement.
- [ ] Commit `feat: modules in brief, find, render and triage`.

### Task 6b: Merge arc

- [ ] Run `go vet ./... && go test ./... && go run ./cmd/arc gate --all` in the arc worktree.
- [ ] Merge `modules` into `main`, using the same flow as previous arc merges (`git log --merges` shows "Merge imp-…"). Push `main` to `origin` and `github`, then delete the branch on both remotes if it was pushed.
- [ ] Do not tag a release. The harness builds arc from a checkout.

---

## Artifactory tasks

### Task 7: Preamble split, `--arc` and CLI install lines

**Files:**
- Modify `standard/preamble.md`, or split it into `standard/preamble.md` plus `standard/preamble-modules.md`, which holds the three module bullets.
- Modify `standard/standard.go`, `internal/index/index.go` (Render and AgentsBlock gain options), `internal/app` (Index takes an arc mode), `cmd/artifactory/project.go` (`index --arc auto|on|off`), and `internal/mcpserver` if the index tool takes options.
- Test goldens go in `internal/index/testdata`.

**Interfaces produced:** `index.Options{Arc bool; CLIInstall bool}`. Render and AgentsBlock honour it. With `Arc`, the three module bullets are left out. With `CLIInstall`, each module's install line reads `artifactory install <Name>`, followed by `(runs: <raw install line>)`.

- [ ] Tests:
  - the existing goldens (`--modules-only`, no arc) are byte-identical;
  - with `Arc`, the three bullets are absent and the others present, in both MODULES.md and the AGENTS.md block;
  - a full `index` in a project gives CLI install lines;
  - `--modules-only` gives raw install lines;
  - `--arc on` with no arc on PATH exits 2;
  - `--json` reports `"arc"`.
- [ ] Commit `feat(index): arc-aware preamble and CLI install lines`.

### Task 8: Register modules with arc

**Files:** Create `internal/arcreg/arcreg.go` and its test. The package wraps `arc module list|set|rm` through `exec`. Modify `internal/app` (Install and Index call it), `skill/SKILL.md` (one line: `With arc present, run \`arc find <words>\` before writing a new piece.`), and `cmd/artifactory` for warnings in text and JSON.

**Interfaces produced:**
- `arcreg.Detect(projectDir) (present bool, warn string)`
- `arcreg.Sync(projectDir string, mods []Entry) (warnings []string)`, where `Entry` mirrors the arc module fields. It sets every installed module and removes `source: artifactory` entries that are not listed.

- [ ] Tests use a fake `arc` script on PATH that logs its argv and serves `module list --json`:
  - `install` of a godot fixture kit calls `arc module set CursorKit --summary … --path addons/CursorKit/** --covers … --entry … --rule … --source artifactory`;
  - a go module gets `--import <path>` and no `--path`;
  - a module listed with no version is not set;
  - a stale `source: artifactory` entry is removed;
  - a fake arc that fails `module set` gives a warning and exit 0;
  - a registry with no arc on PATH warns and keeps the full preamble;
  - with no registry nothing is called.
- [ ] Build `rules` from the descriptor: `Print \`<liveness>\` at startup.` then, if setup is non-empty, `Setup: <setup joined with "; ">.`
- [ ] Commit `feat: register installed modules with arc`.

### Task 9: Harness `--product` and `--arc`

**Files:**
- Modify `tools/artifactory/harness.py` (prepare_trial, run_round, the sandbox bin, building arc), `tools/artifactory/cli.py` (`round --product --arc --arc-src`), and `tools/artifactory/checks/godot.py` (the `arc_gate` check, reported but not a pass condition).
- Create `tests/acceptance/godot-capsule-room/arc-registry.yaml`.
- Tests go in `tools/tests/test_harness.py`.

- [ ] `--product`:
  - put the built `artifactory` binary into the trial's `bin`;
  - write `artifactory.yaml` with `ecosystem`, `provider: dir:<mirrors path as seen inside the sandbox>` and the test's modules, unversioned;
  - run `artifactory index --project <trial project>` before the model starts, with `--arc off` unless `--arc` is given;
  - commit the fixture.
- [ ] `--arc`, which requires `--product`:
  - build arc from `--arc-src` (default `$ARC_SRC`, else `/home/yalt/Documents/Projects/Tech/AI/arc`) into the round's `bin`;
  - copy `arc-registry.yaml` to `.arch/registry.yaml`;
  - run `arc init --opencode --no-detect --ci none`, then `arc render`;
  - delete `.git/hooks/pre-commit`;
  - run `artifactory index --arc on`;
  - commit.

  `arc-registry.yaml` has one concept, `game`, with `paths: ["**"]`, a summary and `reason`. It ignores `.godot/**`, `bin/**`, `obj/**`, `*.uid` and `.gitmodules` (`.gitmodules` is ignored by default after Task 2).
- [ ] The checker adds `arc_gate`, the parsed result of `arc gate --all --json`, run with the round's arc. `round.json` records `"product"` and `"arc"` per round. A small helper counts `do not edit it.` denials in `opencode.log` into `arc_denials`.
- [ ] Tests, with no model:
  - prepare_trial in product mode writes `artifactory.yaml` and a MODULES.md with CLI install lines;
  - in arc mode it adds `.arch/registry.yaml`, the opencode plugin and no pre-commit hook;
  - the arc registry validates against a fixture project with one kit installed as a submodule from the mirrors (skip when the mirrors are absent);
  - a fake trial, where the harness installs CursorKit through `artifactory install` inside prepare_trial's project, results in `arc module list` showing CursorKit.
- [ ] Commit `harness: product and arc trial modes`.

### Task 10: Update the standard and docs

**Files:** `standard/STANDARD.md` (rule 8 mentions that the module bullets may be carried by an enforcing tool) and `README.md` or the docs where the CLI usage is described (arc section).

- [ ] Commit `docs: arc as the optional enforcer`.

After the Artifactory tasks: merge `arc-integration` into Artifactory `main` through a Forgejo PR, then run rounds 8 (`--product`) and 9 (`--product --arc`). Those rounds are tracked as beads, not as plan tasks.
