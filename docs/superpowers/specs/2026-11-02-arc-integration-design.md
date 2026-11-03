# arc integration: design

Date: 2026-11-02. Bead: `Artifactory-3rm` (sub-project 3). Builds on the Artifactory CLI (`docs/superpowers/specs/2026-11-02-artifactory-cli-design.md`, merged in PR #2) and arc (`github.com/Yalton/arc`, v0.1.0, `SPEC.md`). The user delegated design and plan approval for this work (2026-11-02): fresh reviewers check each document in place of the user's approval.

## Intent

The Artifactory CLI gives a model the parts and the instructions. The instructions are prose: the consumer preamble in `standard/preamble.md`, rendered into the `AGENTS.md` block, tells the model to use modules, never edit them, and wire every one. A weak model follows prose unevenly. arc already keeps agent-built code inside a declared architecture, using a registry, harness hooks that run before a write, and a gate for commits and CI. This work makes arc the optional enforcer for module rules. When arc is present, the rules a model would otherwise only read become things arc checks or refuses.

There are three tools. artifactory supplies the pieces. arc makes the model assemble them correctly. beads is the roadmap. arc stays optional: a project without arc works exactly as it does today.

## Goals

1. **Never edit a module.** With arc present, a write to an installed module's files is refused before it happens, through the harness hook. A shell edit is reported straight after it runs. A commit that changes module files fails `arc gate`.
2. **Every module is wired.** `arc gate` fails when an installed module is not referenced from the project's own code. The check is static, so arc still never runs project code.
3. **Use the module, don't rebuild it.** `arc brief`, `arc find`, the first-touch hook context and `arc triage` all name the installed modules and what each one covers. A model about to write a parallel version is pointed at the module first.
4. **Guidance moves into arc.** With arc present, the module rules in the preamble come from arc: its rendered `AGENTS.md` snippet, the brief and hook messages. The `AGENTS.md` block that artifactory writes keeps only what arc does not cover: the pointer to `MODULES.md` and the ecosystem's project notes (build, run, verify, stop).
5. **One direction of dependency.** artifactory calls arc. arc knows nothing about artifactory's formats, ecosystems or provider. It stores generic "module" entries that any tool, or a person, could write.
6. **Measured.** Two trial rounds separate the effect of the CLI from the effect of arc (see Evaluation).

## Non-goals

- Running project code from arc, for example checking liveness markers at runtime. The harness checker already does that for trials. arc's principle "never runs project code / no custom analysis" stays.
- Protecting Go modules on disk. `go get` modules live in `GOMODCACHE`, outside the repo and read-only. arc only guards against redirecting them: a `replace` directive in `go.mod` for a module path is a finding.
- Detecting that a model is reimplementing a module, beyond what the brief, find and triage already do through word matching. Clone detection across module boundaries is out.
- New harnesses. Claude Code, Codex and opencode only, as arc supports today.
- Upgrades. A submodule pointer that moves is allowed; that is how `artifactory install` upgrades later.

## Anti-goals

- **arc depending on artifactory.** No `artifactory.yaml` parsing in arc, no ecosystem names in arc code, and no artifactory binary required for arc's own checks.
- **A broken arc blocking work.** Hooks keep arc's rule that any internal error allows the call with a warning.
- **Hand-edited registry drift.** artifactory never writes `.arch/registry.yaml` text itself. It calls an arc command, so validation and rendering stay in one place.

## Design

### arc: a `modules:` registry section

A new optional top-level list in `.arch/registry.yaml`:

```yaml
modules:
  - id: CursorKit                 # unique among modules; same charset as concept ids plus upper case
    summary: "Push/pop stack that owns the mouse cursor mode so overlapping UI layers never fight."
    paths: ["addons/CursorKit/**"] # installed files in the repo; may be empty (go modules)
    covers:                        # what it replaces, for find/brief/triage word matching
      - "a stack of mouse-mode owners for menus and overlays"
    entry: ["InputModeManager.Instance", "InputModeManager.Push"]  # symbols project code must reference
    import: ""                     # optional import path (go): wired if `go list -deps` of the main packages includes it; a go.mod replace of it is a finding
    rules: ["Configure it through its autoload; never edit files under addons/CursorKit."]
    source: artifactory            # free text: who manages this entry
```

Validation:
- `id` is required and unique.
- Every `paths` glob must match at least one tracked path, and a git submodule's gitlink path counts as a match for `<dir>/**`.
- At least one of `entry` and `import` is required.

Module paths take precedence over concept paths. A concept glob such as `**` may cover a module's folder, but a file under a module path belongs to the module, not the concept. This lets a project keep one catch-all concept. Module paths are exempt from placement. `.gitmodules` joins arc's built-in ignore list, because `git submodule add` writes it.

### arc: enforcement

- **Hook, before a write.** A write to a path under a module's `paths` is denied. The reason names the module and gives its rules plus "use its public surface (entry: …) instead". This is the only new deny. Writes elsewhere behave as before, including today's refusal of a new file that no concept owns. The hook resolves the superproject (`git rev-parse --show-superproject-working-tree`, falling back to `--show-toplevel`), so a write inside a submodule's folder still finds the project's registry.
- **Hook, after a shell command.** The post-shell snapshot gains two checks. A changed file under a module path gets feedback. So does a submodule that has `modified content`, read from `git status --porcelain` and `git -C <dir> status --porcelain`.
- **Gate check `modules`**, which runs in every mode. It reports:
  - changed tracked files under module paths, which catches vendored copies;
  - a submodule module whose own work tree is dirty, which catches submodule kits, since the superproject tracks only their gitlink;
  - a `go.mod` `replace` of a module's `import`;
  - an unwired module. A module is wired when `import` is set and `go list -deps` of the repo's main packages includes it. Otherwise it is wired when at least one `entry` symbol, or that symbol's leading identifier (the text before its first `.`), appears as a whole word in a tracked, non-ignored file outside every module path. The leading identifier counts because some modules are wired only through configuration, with no call in code. An autoload line in `project.godot`, `InputModeManager="*res://addons/CursorKit/InputModeManager.cs"`, names `InputModeManager`, the leading identifier of the entry `InputModeManager.Instance`. The match is plain text, with no language parsing, so it works for C#, GDScript, Go and others.
- **Approval.** Removing a module entry, or narrowing its `paths`, counts as loosening and needs `arch-approved` in CI, like a removed rule. Adding a module does not, because it adds a guardrail.

### arc: guidance

- **Brief.** A bare `arc brief` lists every module as `id — summary`, then its `entry` and `rules`. A path brief does the same for modules whose `covers` or `entry` words appear in the path's concept summary or the bead text. The section has a token cap, so a long list is cut with "(N more: arc brief --modules)".
- **find.** `arc find` matches modules on `id`, `summary`, `covers` and `entry`, ranked with concepts. A module hit prints first, tagged `module`, with "use this; do not reimplement".
- **Hook context.** On the first write of a session, the hook's context names the installed modules once (`Installed modules (use, never edit): A, B, C — arc brief for details`). This is the session-start channel: arc has no SessionStart hook, and opencode, which trials use, has none either.
- **Rendered snippet.** `arc render` adds a "Modules" table to the `ARCHITECTURE.md` block. It also adds three lines to the `AGENTS.md`/`CLAUDE.md` snippet that carry the preamble's module rules: use an installed module before writing your own, never edit module files, wire every module from the program's entry point. That text is fixed in arc and generic.
- **Triage.** `arc triage` flags a bead whose text matches a module's `covers` with "module X covers this".

### arc: a write command

`arc module set <id> --summary S [--path G]... [--covers C]... [--entry E]... [--import P] [--rule R]... [--source S]` creates or replaces one entry. `arc module rm <id>` removes one. `arc module list` prints the entries; artifactory uses it to detect support. Both write commands run `validate` and then `render`. They edit the YAML with comment-preserving node edits, through `yaml.Node`, not by rewriting the whole file. Both accept `--json`. Exit codes: 0 ok, 1 validation failed (nothing written), 2 usage.

### artifactory: write to arc when present

- **Detection.** arc is present when the project has `.arch/registry.yaml` and `arc module list --json` succeeds. When the registry exists but arc is missing or too old, artifactory warns `arc registry found but arc with module support is not on PATH; module rules not registered` and treats arc as absent, so the preamble stays complete. `index --arc auto|on|off` overrides this. The default is `auto`, and `on` with no working arc is exit 2.
- **`install` and `index`.** After a successful install, and on every `index`, artifactory runs `arc module set` for each installed module in `artifactory.yaml`, meaning one with a recorded version. It also runs `arc module rm` for any `source: artifactory` entry whose module is no longer listed. A removal is a loosening and needs `arch-approved` in CI, which is right for a deliberate removal. The descriptor maps onto the entry as follows:

  | Entry field | Taken from |
  |---|---|
  | `summary` | descriptor `summary` |
  | `paths` | the installed copy's folder, relative to the repo (godot: `addons/<Name>/**`); none for go |
  | `covers` | descriptor `replaces` |
  | `entry` | descriptor `entry` |
  | `import` | go only: the module path from the install line |
  | `rules` | a short line built from `setup` and `liveness` (for example "Print `[CursorKit] live` at startup; setup: …") |
  | `source` | `artifactory` |

  An `arc module set` failure becomes a warning. The install still succeeds.
- **The preamble with arc.** When arc is present, `index` leaves three bullets out of the preamble, in both `MODULES.md` and the `AGENTS.md` block, because arc's rendered snippet and hooks now carry them:
  - use a module instead of writing your own;
  - never edit files inside an installed module;
  - wire every module into the real entry point.

  The other bullets stay: read the index first, install only with the `install` command, check liveness before finishing, merge the README's Wiring section into your existing class, and stop once the checks pass. The project notes stay too. The preamble file splits into a module-rules part and the rest, so `standard/preamble.md` stays the one source of the text. `--json` reports `"arc": true|false`.
- **Gaps.** When `init` finds arc, the skill file gets one line: "with arc present, `arc find` before writing a new piece."

### Harness: arc on/off

With arc on, module entries can only exist once kits are installed, and the model installs them. So the model must install through `artifactory install`. That puts the CLI itself into trials, which is the real product path in any case.

- **New mode, `--product`.** Trials get the `artifactory` binary in the sandbox `bin`, and an `artifactory.yaml` that lists the test's modules unversioned. Its provider is `dir:` pointing at the read-only kit mirrors already bound into the sandbox. `MODULES.md`'s install lines read `artifactory install <Name>`: a full `index` (not `--modules-only`) renders each module's install line as `artifactory install <Name>` and puts the raw line beside it, for reference. This also applies to real projects, and it matches the skill file. `--modules-only`, which the harness uses for the non-product rounds, keeps the raw line, so those rounds see the same text as round 7. In product mode the harness runs `artifactory index` in the trial project before the model starts. The `AGENTS.md` block is written as `artifactory index` writes it.
- **`--arc`,** which requires `--product`, adds the following:
  - `arc` is built from a pinned checkout (an `--arc-src` flag, defaulting to `$ARC_SRC`) and placed in the sandbox `bin`.
  - The harness writes a fixed trial registry (`tests/acceptance/<test>/arc-registry.yaml`). It has one catch-all concept, `game`, with paths `**`. Module paths take precedence over it, and it ignores `.godot/**` and build output, so ordinary new files are owned and allowed.
  - The harness runs `arc init --opencode --no-detect --ci none` for the opencode plugin and the rendered snippet, then deletes `.git/hooks/pre-commit`. Trials get no pre-commit gate, and the checker runs the gate at the end.
  - The harness commits the fixture before the model starts.
- The trial prompt does not change.
- The checker adds `arc_gate`: the result of `arc gate --base <fixture commit> --json` run in the finished project (`--all` skips the vendored changed-file check). It is reported, not used as a pass condition.
- The round report counts denied writes, read from the opencode log, as evidence the guard fired.

### Evaluation

Two rounds of `godot-capsule-room`, 5 trials each, use the same kits and the same checker. They are compared with round 7, which is running as this is written and uses the pre-CLI harness. Its index text is identical, as the golden tests show.

- **Round 8, `--product`:** the CLI is in the sandbox and arc is off. This isolates the change from the CLI.
- **Round 9, `--product --arc`:** this isolates arc. The question is what changes from round 8 to round 9.

The questions:
- Did any trial try to edit a module, and was it refused?
- Did the pass rate or time move?
- Did the screenshots change?

A single run of 5 trials is weak evidence either way, and the report says so. The roadmap experiment (`Artifactory-5dx`) runs with arc on.

## Constraints

- arc follows `SPEC.md` first. SPEC changes land before code. The layout stays fixed, so new code goes in existing packages:
  - `internal/registry`, which holds the schema, `validate.go` and `render.go`;
  - `internal/hook`, `internal/gate`, `internal/brief` and `internal/initcmd`;
  - `internal/symbols` for find, and `internal/beads` for triage;
  - `cmd/arc` for the `module` command.
- arc's allowed dependencies are unchanged: stdlib, `yaml.v3`, `doublestar`.
- arc tests use real git fixture repos in temp dirs, including one with a submodule.
- arc commits merge to `main`. Push to both `origin` (Forgejo) and `github`. The user delegated the merge.
- artifactory changes follow the CLI's conventions (`--json`, exit codes 0/1/2, `internal/app` shared by the CLI and MCP).

## Decisions taken under delegation (check these)

- **A first-class `modules:` section,** rather than external checks only or one concept per module. It fits arc's grain: the registry is the source of truth, and entries are validated, rendered, briefed and approval-gated. Checks-only would give no hook deny. A concept per module would conflict with "one concept per file" and the placement rules.
- **The wiring check is static:** a text match on `entry` symbols, or `go list -deps`. Runtime liveness stays with the harness checker.
- **artifactory calls `arc module set`.** arc never reads artifactory files.
- **The session-start channel is the first-write hook context,** because opencode has no session-start hook.
- **Submodule pointer moves are allowed.** Dirty submodule content is not.
- **artifactory drops the three module bullets from the preamble when arc is present,** in both `MODULES.md` and the `AGENTS.md` block, so they are not said twice.
- **Module paths take precedence over concept paths,** instead of overlap being forbidden. This lets a project keep a catch-all concept.
- **The wiring check counts an entry symbol's leading identifier.** Without that, an autoload-only module, which the preamble calls correct, would fail.
- **Trials install through the CLI (`--product`),** and arc is evaluated on top of that in a separate round, so the two effects can be told apart.
- **`index` registers installed modules only, and prunes `source: artifactory` entries for modules that are no longer listed.**

## Left to the builder

- The exact hook and brief message wording, kept short and in arc's voice.
- The token cap for the brief's module section.
- How `go list -deps` finds the main packages (`go list -f '{{if eq .Name "main"}}{{.ImportPath}}{{end}}' ./...`).
- The arc pin mechanism in the harness, which can be a flag plus a default path.
