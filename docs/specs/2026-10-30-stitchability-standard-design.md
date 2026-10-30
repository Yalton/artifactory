# Stitchability standard: design

Status: approved by the operator on 2026-10-30. Sub-project 1 of the artifactory
(see `2026-10-30-artifactory-design.md`). Nothing is built.

## Why

The artifactory only pays off if a weak local model can take vetted modules
and wire them into a working project. Today it cannot. The best evidence is
InNetwork (`Tech/Games/Godot/InNetwork`), a hospital game that a local model
worked on for about a week in opencode. It had the Godot kits available and:

- copied seven kits in, but the game that actually runs uses none of them;
  the only kit calls are from tests and from modules nothing loads;
- edited kit source to make its own tests pass (inverted BotSkillKit's aim
  lerp, dropped a de-duplication line from PhysPropKit's `HoldRegistry`);
- lost the README of five of the seven kits by copying folders, and put them
  under `res/addons/...` instead of `res://addons/<Name>Kit/`;
- used the starting template's own RPC guard, clock and settings code instead
  of the matching kits, and hand-wrote a save system, smoke harness and tick
  clock that RunSaveKit, SmokeKit and NetClockKit already provide;
- left CrashKit dead because its required `CrashHandler.Initialize()` setup
  step was never called;
- closed 21 beads with one code commit, and changed test expectations until
  they passed.

The kits it did call (RngKit, BotSkillKit, PhysPropKit) are plain types with
one obvious entry point. So the interfaces were not the main problem.
The failures were around the modules: installing them, leaving them alone,
finding them before writing a replacement, and proving they are actually used.

The operator's picture: we hand the model a sink and a toilet and it should do
the plumbing. Today it smashes them and builds new ones out of cardboard.

## What success looks like

A local model, given a blank project, a set of modules and a short goal,
produces something that works, built mostly from the modules, with the
modules untouched and every installed module actually in use.

Concretely, the standard is proven when **both** acceptance tests below pass
their bar: one in Godot C#, one in Go. Godot is the first proving ground
because a pseudo-artifactory (the 34 kits) already exists. It is not the final
milestone. A second ecosystem that needs no change to the core rules is what
shows the standard extends.

## Goals

- A short, ecosystem-neutral set of core rules every module follows.
- One profile per ecosystem that turns those rules into concrete files,
  commands and checks. This sub-project delivers the Godot C# and Go profiles.
- A module descriptor format and a module index format built from descriptors.
- Two repeatable acceptance tests, each with a scripted checker, so the
  standard can be changed and re-measured.
- The Godot kits needed for the Godot test brought up to the standard, and
  a small set of new Go sample modules written to it.

## Non-goals

- The Forgejo org, the discovery service, the MCP server and the publish gate.
  That is sub-project 2. This sub-project only defines the index *format* and
  hands the model the index as a file.
- Moving the kits to the new org. That is a separate small task (plain repo
  transfer, no descriptor) and does not block this work.
- Bringing all 34 kits to the standard. Only the ones the Godot test uses.
- Python or other ecosystem profiles.
- The duplication scanner (sub-project 3).

## Anti-goals

- A standard that only works for Godot, or whose core rules mention Godot,
  C#, Go or any specific tool.
- A test that passes because the checker is lenient: a game that runs but
  ignores the kits, or kits that are present but unreachable, must fail.
- A long rulebook. The model has about 128K of context and has to read the
  index, the descriptors and the docs of everything it installs. Rules and
  docs must stay short.
- Anything that lets a consuming project fork a module's source.

## Constraints

- **Consumer model:** Ornith 1.5 35B A3B (mixture of experts, about 3B
  active), Q4_K_M, served by llama.cpp on `192.168.50.174:8080` as
  `ornith-1.5-q4` with 128K context per slot and temperature 0.6.
- **Consumer harness:** opencode, provider "Agentbox llama.cpp" in
  `~/.config/opencode/opencode.jsonc`.
- **Existing kit contract** (`Tech/Games/Godot/Modules/README.md`): zero
  runtime dependencies, folder = namespace = `res://addons/<Name>Kit/`, no
  hardcoded `res://`/`user://` paths, a README per kit, and a
  `<Name>Kit.demo` project whose `--smoke` run is the kit's test suite.
  The standard keeps all of this except "install by copying a folder" and
  "edit in place".
- Vapula workers hold no Forgejo credentials. Nothing in the standard may
  require a consumer to push to a module repository.
- Running Ornith costs nothing. Any step that calls a paid model (for example
  a Claude reviewer grading runs) needs the operator's go-ahead first.

## The core rules (all ecosystems)

1. **Every module has a descriptor** at its root, in one format shared by all
   ecosystems. Starting fields (the test loop may add, drop or rename them):
   - `name`, `ecosystem`, `version`
   - `summary`: one line, what it does
   - `replaces`: short phrases naming what a consumer would otherwise
     hand-write ("save files with versioning and migration", "config loading
     from env and file"). This is what lets a model notice overlap.
   - `install`: the one command that installs it
   - `setup`: required wiring steps, as few as possible, each one line. Empty
     is best.
   - `entry`: the types or functions a consumer calls first
   - `liveness`: how a checker proves the module is in use (per profile)
   - `docs`, `example`, `test`: paths or commands
2. **Docs travel with the code.** Installing a module by its `install`
   command always brings its README and descriptor along. There is no other
   supported install.
3. **Consumers never edit module files.** A project configures, wraps or
   extends a module through its public surface. A needed change goes back to
   the module as a PR through the publish gate. Each profile defines how a
   checker verifies modules are unmodified.
4. **Every installed module must be live.** It must be reachable from the
   program's real entry point, not only from tests. Each profile defines the
   check.
5. **Every module ships a worked example** showing it wired into a minimal
   host, short enough to read whole.
6. **Required setup is a defect to minimise.** Each `setup` step is a place a
   weak model can skip. A module that can work with zero setup should.
7. **A module index** is a single generated file listing every module's
   `name`, `summary`, `replaces` and `install`. The model reads it before
   writing code. It is built only from descriptors.
8. **The index opens with a short consumer preamble**: a few lines telling
   the model to read the index before writing code, install only with each
   module's `install` command, never edit module files, and wire every module
   it installs into the real entry point. The preamble is part of the
   standard and is versioned with it. This is how the rules reach a consumer
   whose own instructions (AGENTS.md, opencode config) we do not control.

## Godot C# profile

- Install: `git submodule add <url> addons/<Name>Kit`. The kits' "copy one
  folder" and "edit in place" instructions are removed from their READMEs and
  from the catalog README.
- Unmodified check: each kit submodule is at a published commit with a clean
  working tree.
- Liveness check: runtime. "Live" means the kit was initialised or
  registered by the running game at startup through its real entry path
  (an autoload, or a call reachable from one or from the main scene). It does
  not mean every feature fired: event-driven kits such as RunSaveKit or
  TransitionKit count as live once wired, and the prompt does not have to
  require saving or scene changes. Each kit prints a fixed marker line
  (`[<Name>Kit] live`, or whatever the test loop settles on) from its
  initialisation or required setup step, using plain `GD.Print`, not the
  `Log.cs` shim, since some kits have no shim. A skipped setup step then shows
  up as a missing marker. The checker runs the game headless for a fixed time
  and greps for the markers. This proves the kit is wired, which is exactly
  what InNetwork never did; it does not prove deep use, which the review
  covers.
- Example: a short, complete "Wiring" snippet in each kit README showing the
  kit hooked into a minimal host. The `<Name>Kit.demo` projects stay in the
  GodotKits umbrella repo, because moving them would break its symlink and
  csproj layout. A submodule install therefore brings the snippet but not the
  demo.
- Known conflict: the kit catalog tells consumers to retarget output by
  editing a kit's `Log.cs`, which rule 3 forbids. Resolving that (a public
  logging seam per kit) is follow-up work, not part of this sub-project.

## Go profile

- Install: `go get <module path>`.
- Unmodified check: `go mod verify`. Go's module cache is read-only, so this
  rule largely enforces itself. `replace` directives that point at local
  copies are not allowed in a consumer's `go.mod`.
- Liveness check: every module in `go.mod` appears in
  `go list -deps ./cmd/...` (or the project's main package).
- Example: an `example/` directory in each module with a runnable `main.go`.

## Acceptance test 1: Godot capsule room

**Prompt to the model (gist):** in this blank Godot C# project, make a room
with a capsule player you can move with WASD, and wire up the foundation a
bigger game would need, using the modules in the index.

**Setup:**
- A fresh Godot 4 C# project, no template. InNetwork started from
  3DMultiplayerTemplate and its built-in code shadowed the kits.
- The module index file for the chosen kits. The index lists exactly the
  foundation kits, and the prompt says to use all of them. Every kit in the
  index must be installed and live for a run to pass, the same as the Go
  test. Otherwise a run that installs nothing and hand-writes everything
  would pass.
- Contracts the checker relies on, stated in the prompt: the player node is
  in group `player`, and the main scene is set in `project.godot`.

**Foundation kits (to be confirmed by the builder):** InputRemapKit,
SettingsKit, CursorKit, DebugLogKit, DevConsoleKit, CrashKit, TransitionKit,
RunSaveKit, and possibly PerfKit and BuildIdKit. The set must include at
least one kit with a required setup step (CrashKit) and at least one that
overlaps something the model would be tempted to hand-write (SettingsKit,
RunSaveKit).

**Player movement is glue, not a module.** No player-controller kit exists,
and a WASD capsule is the kind of plumbing the model should write itself.

**Checker passes a run when:**
1. The project builds.
2. The game starts headless and runs for the fixed time without errors.
3. Injected WASD input moves the node in group `player`.
4. Every kit in the index is installed and its liveness marker appears.
5. Every kit submodule is at a published commit with a clean tree.
6. No project code duplicates a kit's `replaces` entry (see Duplication
   below).

The operator also plays the best passing run by hand.

## Acceptance test 2: Go URL shortener

**Prompt to the model (gist):** build a small URL-shortener HTTP service using
the modules in the index. `POST /links` with a URL returns a short code,
`GET /<code>` redirects to it, `GET /healthz` reports health.

**Sample modules (new, written to the standard by a frontier model):**
- config: loads settings from env and an optional file
- kv store: a simple file-backed key-value store
- short id: generates short, URL-safe ids
- http server: a server wrapper with a health endpoint and graceful shutdown

At least one of them should cover something the model would happily
hand-roll, to test that it looks for a module first.

**Checker passes a run when:**
1. `go build ./...` and `go test ./...` pass.
2. The service starts, and a scripted client creates a link, follows the
   redirect, and gets a healthy `/healthz`.
3. `go mod verify` passes and `go.mod` has no `replace` directives.
4. Every sample module appears in `go list -deps` of the main package.
5. No project code duplicates a module's `replaces` entry.

## Running the tests

- Each run starts from a clean copy of the blank project in a fresh
  directory, with Ornith in opencode, the same prompt and a fixed time limit.
- The model gets only the prompt and the index (with its preamble). The
  prompt stays fixed across revisions, and no extra AGENTS.md, skills or
  opencode config are added, so every improvement has to come from the
  standard, the index or the modules.
- Five runs per test per revision of the standard. A test passes its bar at
  four of five runs passing the checker. (This bar is a starting guess; the
  operator may move it.)
- Before any module is changed, run the Godot test with the kits exactly
  as they are today, to record a baseline. The baseline has no descriptors,
  index or markers, so the model gets the catalog README
  (`Tech/Games/Godot/Modules/README.md`) in place of the index. Checks 1–3
  and 5 are scripted; which kits it installed and wired is judged by reading
  the tree. The baseline is a starting point, not a strictly comparable
  score.
- Keep every run's transcript, final tree and checker output, so failures can
  be read and compared between revisions.

## Duplication

This check is the hardest one to automate. The pass/fail gate is a scripted
heuristic per profile, so runs can be scored without anyone present (for
example, Godot: new autoloads or classes whose names or purpose match a kit's
`replaces`; Go: project packages that implement config loading, key-value
storage, id generation or server lifecycle). A review of each revision's
runs against the index does not gate, but it is the main source of "why did
it fail" for the next revision, and it can flag heuristic misses so the
heuristic gets tightened.

## How the standard gets finished

1. Write the draft rules, the descriptor format and the two profiles from this
   document.
2. Run the Godot baseline.
3. Bring the foundation kits up to the standard and write the Go sample
   modules.
4. Run both tests, read the failures, change the standard or the modules, and
   rerun.
5. The standard is locked when both tests meet their bar on the same revision.
   The final rules, descriptor format and profiles are then written up as the
   standard document that sub-project 2 builds on.

## Decisions

Made by the operator:
- Standard first. The kits move to the new org as plain repos in a separate,
  earlier task, with no placeholder format.
- Success is the Godot capsule-room test: a playable result built mostly from
  kits, kits intact.
- Godot is the first test, not the last. A Go test with frontier-written
  sample modules is the second.
- Paid (frontier-model) work for this sub-project is approved once, up
  front. The loop stops after 5 revision rounds even if the bar is not met,
  and the findings go back to the operator.
- Kit changes go on a `stitchability` branch in each foundation kit's repo
  under `yalt/` on repo.billbert.co. The tests pin those commits. Branches
  merge to `main` only after the standard locks. Pushing these branches is
  authorised.

Calls made in this session (the operator may overrule):
- Consumers never edit module files; changes go back as PRs.
- Ecosystem-neutral core rules plus one profile per ecosystem.
- Descriptor fields as listed above, as a starting draft.
- Godot install via git submodule; copy-install and "edit in place" retired.
- Runtime liveness markers for Godot; `go list -deps` for Go.
- Five runs per test, pass at four.
- Index handed to the model as a file; serving it is sub-project 2.
- Every kit in the Godot index is required, matching the Go test.
- The core rules reach the model through a preamble at the top of the index.
  The prompt is fixed and nothing else is added to the consumer's setup.
- "Live" means initialised at startup through the real entry path; markers
  print via `GD.Print`, not `Log.cs`.
- Godot examples are README "Wiring" snippets; demos stay in the umbrella
  repo. The `Log.cs` edit-to-retarget conflict is deferred.
- The duplication gate is a scripted heuristic; review is diagnostic only.
- The baseline uses the catalog README as its index and is partly judged by
  hand.

## Left to the builder

- Descriptor file name and serialisation (YAML is the obvious default).
  VentureAutomation's `component.yaml` should be read first, since its Go
  ecosystem is meant to fold into this standard.
- Exact liveness marker text and how the Godot checker injects input.
- Where the test modules are hosted during the tests. Fetching must work the
  way a real consumer fetches (submodule from a git URL, `go get` through a
  proxy or VCS), without relying on the org move, and without letting the
  model edit module source.
- The checker scripts, the run harness around `opencode`, and the time limit.
- The exact final list of foundation kits.
