# Artifactory CLI: design

Date: 2026-11-02. Bead: `Artifactory-07m` (sub-project 2). Builds on the Stitchability Standard (`standard/STANDARD.md`, Draft 0.2) and the results of sub-project 1 (`docs/specs/2026-11-01-stitchability-standard-results.md`).

## Intent

Sub-project 1 showed that a weak local model (Ornith) can build working programs by installing and wiring modules that follow a written standard. However, only the trial harness can deliver that setup. The harness copies a fixture, writes a `MODULES.md` and runs a trial, and nothing of it carries over to a real project.

The Artifactory CLI makes this a tool. It is the parts store in a three-tool system:

- **artifactory** stores the pieces: it finds, installs and publishes modules.
- **arc** (`github.com/Yalton/arc`, a separate project) makes sure the model assembles them correctly. This is optional and is integrated later, under bead `Artifactory-3rm`.
- **beads** is the roadmap: ordered work, with each bead naming the modules it uses.

There are two roles. A frontier agent (or a person) writes modules and publishes them. A local model like Ornith assembles them into projects. Either role may write the roadmap. Which one writes it better is measured later, under bead `Artifactory-5dx`.

The system must work for any project that can be built from pieces, not just Godot. It is general because the ecosystem-specific parts (profile, consumer notes, checker) stay data, separate from the core.

## Goals

1. Any agent can find modules that fit a task, from a shell, with no service running.
2. Any agent can install a module with the module's own `install` command, and the project ends up with a scoped index and the consumer rules.
3. A frontier agent, or a project lifting out a piece it built, can publish a module in one command. Publishing fails unless the module meets the standard.
4. A new ecosystem takes a profile and consumer notes, not changes to the core.
5. The trial harness uses the CLI, so every trial from then on tests the real product.

## Non-goals (first version)

- Detecting reusable code across projects, such as the same pause menu written in ten games. Deferred: `Artifactory-4gu`.
- Filing "module wanted" requests for another tool to build. Deferred: `Artifactory-t7l`.
- Installing each published module into a clean project to prove it works. Deferred to a scheduled job outside the CLI: `Artifactory-8r9`.
- Enforcement during a build (do not edit modules, wire every module). That belongs to arc.
- Providers other than Forgejo. The provider interface exists, but only Forgejo is implemented.

## Anti-goals

- **A package manager.** Installation always runs the module's own `install` line (`git submodule add`, `go get`, ...). The CLI never reimplements dependency resolution, lockfiles or downloads.
- **A server you must run.** The store is a git hosting org. The CLI talks to the provider's API and to git directly.
- **Showing a model the whole catalog.** In round 0, an index of all 34 kits made the model install nearly all of them. Anything a model reads must be scoped.
- **Hiding gaps.** When no module fits a need, the tool must say so plainly, so the gap gets recorded rather than quietly hand-written.

## Concepts

- **Module:** a git repository with a valid `module.yaml` at its root (rule 1 of the standard). Its version is a git tag `v<version>` that matches the descriptor's `version`.
- **Catalog:** every module in the configured provider org. For now that is the Forgejo org `artifactory` on `repo.billbert.co`. Repos without a valid `module.yaml` (for example the GodotKits catalog repo or demo projects) are not modules and are skipped.
- **Provider:** an interface for listing repos in an org, reading one file at a ref, and creating a repo and pushing to it. Forgejo is the first implementation. GitHub and GitLab will implement the same interface later.
- **Ecosystem data:** `standard/profiles/<eco>.md`, `standard/consumer/<eco>.md` and `standard/preamble.md`. The CLI embeds a copy of the standard at build time, so an installed binary needs no checkout of this repository.

## Commands

Every command accepts `--json`. Exit codes match arc: `0` ok, `1` the check found problems, `2` usage, configuration or environment error.

| Command | What it does |
|---|---|
| `artifactory search <words...> [--ecosystem E]` | Ranks catalog modules against the words, using `name`, `summary`, `replaces` and `entry`. Prints name, summary, install line and a score. A search with no good match says **no module matches**, so the caller can record a gap. |
| `artifactory show <name>` | Prints the full descriptor and the module's README at its latest version. |
| `artifactory install <name>... [--project DIR]` | Runs each module's `install` line in the project and records the module in `artifactory.yaml`. Then regenerates the index (below). It refuses a module whose ecosystem differs from the project's. |
| `artifactory index [--project DIR] [--arc auto\|on\|off]` | Regenerates `MODULES.md` from the modules listed in `artifactory.yaml`, and writes or refreshes a marked consumer-rules block in `AGENTS.md`. The block holds the preamble plus the ecosystem's consumer notes, and points to `MODULES.md`. With arc on and at least one module in arc's registry (checked after the sync below), the two preamble bullets marked `<!-- arc -->` in `standard/preamble.md` are left out of both files, because arc enforces them. `index` and `install` then register each installed module (one with a version in `artifactory.yaml`) in arc's registry (`arc module set`, source `artifactory`) and remove entries for modules no longer installed. `auto` (the default) turns arc on when `.arch/registry.yaml` exists and `arc module list --json` works. `on` without a working arc exits 2, and `off` keeps the full preamble. A full `index` prints an `artifactory install <Name>` line for each module. |
| `artifactory init [--ecosystem E] [--project DIR]` | Creates `artifactory.yaml`, guessing the ecosystem from project files (`go.mod`, `project.godot`) when not given. Runs `index`. |
| `artifactory validate [DIR]` | Checks a module against the standard and its profile, without publishing: descriptor fields, the liveness format for the ecosystem, that `docs` and `example` exist, and that the version tag is free. |
| `artifactory publish [DIR]` | Runs `validate`, then the descriptor's `test` command, which must exit 0. Creates the repo in the org if it is missing, pushes, and tags `v<version>`. It refuses to move an existing tag. |
| `artifactory catalog [--ecosystem E]` | Lists every module, for people. Agents use `search`. |

### Project file: `artifactory.yaml`

```yaml
ecosystem: godot-csharp
provider: forgejo:repo.billbert.co/artifactory
modules:
  - name: CursorKit
    version: 0.1.0
```

This file records the scope. `MODULES.md` lists only these modules, which keeps a model from installing the whole catalog. A roadmap writer chooses the modules with `search`, and installing them writes them here.

### Gaps

A need with no module is a gap. In the first version:
- The roadmap writer (frontier agent or Ornith) records the gap in the bead that needs it.
- The project builds the piece itself, but to the standard from the start: its own folder, a `module.yaml`, a README, and a liveness marker. With arc present, it is fenced as its own concept.
- Later, `artifactory publish <that folder>` lifts it out as a module. Publishing a subfolder pushes only that folder's contents to the new repo.

## Agent surface

- **Skill file.** The CLI ships a short `SKILL.md`, written per `writing-for-agents`. It tells an agent when to search, how to install, and how to record a gap. `artifactory init` copies it into the harness skill folders the project uses, and tells the user about each copy it makes, the same way arc writes its hooks.
- **MCP server (optional).** `artifactory mcp` serves `search`, `show`, `install` and `index` over stdio and calls the same code. It is not required. Files plus the CLI are the main path, since Ornith already works well that way.

## Roadmaps and beads

When a roadmap is written, each bead names the modules it uses, or says it uses none, and names any gap. The first version only asks for this. The instructions in the skill file are the only enforcement. Checking beads against the modules installed is a natural fit for `arc triage` and belongs to `Artifactory-3rm`.

## The harness

`tools/artifactory/harness.py` stops building the index itself (`index.py`). For each trial, it calls `artifactory init` and `artifactory index` in the trial project, with the acceptance test's module list written into `artifactory.yaml`. The trial prompt then refers to `MODULES.md` and the `AGENTS.md` block as before. Trials can see the same text as round 6, or the CLI can deliberately change it. If it changes, the round report says so.

`artifactory round TEST_DIR --product` runs the trials through the CLI as above. Adding `--arc` installs arc in each trial (registry and opencode plugin, built from `--arc-src DIR` or `$ARC_SRC`), and the checker reports `arc_gate`. `arc_gate` is informational: it never decides `passed`. The result also records `arc_denials`, the number of edits the arc hook refused, counted from the trial transcript, and `arc_hook_live`, true when arc's hook left session state (`.arch/cache/hook-*.json`) in the trial project. A false `arc_hook_live` means the hook never ran, so a zero `arc_denials` says nothing. Both are informational. `check --arc --arc-base COMMIT` reports the gate for one trial project (Godot).

## Constraints

- Language: Go, single static binary, the same as arc. It installs with `go install` from this repository (`repo.billbert.co/artifactory/artifactory/cmd/artifactory`). The Python harness and its checkers stay in Python.
- The descriptor format and its field list stay exactly as the standard defines them. The CLI ports the existing checks from `tools/artifactory/descriptor.py` (`STR_FIELDS`, `LIST_FIELDS`, and the godot-csharp liveness rule `[<Kit>] live`). The Python validator either calls the binary or is removed. There must be only one validator.
- Provider access uses the user's existing credentials: SSH for git, and a token from the environment or from `tea`'s config for the Forgejo API. The CLI never stores secrets.
- Forgejo is origin. Kits are in the `artifactory` org on branch `main`. The Go sample modules (`samples/go/*`) are in this repository and reach trials through a local GOPROXY mirror (`tools/artifactory/goproxy.py`). Publishing them to the org is the first real use of `publish`.

## Decided by the user

- A CLI with an optional MCP server.
- Pull and publish in one tool, wrapping git so that publishing always works the same way.
- Forgejo first, but not tied to it. GitHub and GitLab come later.
- arc is an optional add-on that enforces correct use. The guidance we put in prompts moves into arc, in later work.
- Either a frontier agent or a local model may write the roadmap. The roadmap writer picks modules using search. Beads name the modules they use. Gaps are detected and built inside the project, then published later.
- Publishing checks the descriptor, the docs and the module's own tests. Clean-install checks run as a scheduled job somewhere else.
- Cross-project reuse detection and module-wanted requests come later, recorded as beads.

## My calls (check these)

- Go rather than Python, so the CLI can be dropped into a sandbox and matches arc.
- The CLI lives in this repository, under `cmd/artifactory`, beside `standard/`, and embeds the standard.
- The scope is recorded in `artifactory.yaml`, with `MODULES.md` and the `AGENTS.md` block generated from it.
- Search is keyword ranking over descriptor fields. It does not use embeddings and never calls a model, the same rule arc follows.
- The catalog is read from the provider every time, with a short-lived cache under `~/.cache/artifactory`. Nothing local holds authoritative state.
- `publish` never moves an existing tag. A new version needs a version bump in `module.yaml`.

## Settled after the builder check (my calls)

- **Versions.** `install` runs the descriptor's `install` line exactly as written, so it always gets the latest release. Afterwards the CLI reads the installed copy's `module.yaml` and records that version in `artifactory.yaml`. It never edits install lines, which keeps the CLI a runner and not a package manager. A module's "latest version" is its highest semver tag.
- **Catalog membership.** A repo is in the catalog when its highest semver tag has a valid `module.yaml`. Untagged repos are not listed. `main` is never read for catalog data.
- **Go modules from the org.** For ecosystem `go`, `validate` checks that the `go.mod` module line equals the path in the `install` line. `install` passes the environment through unchanged, so a harness-set `GOPROXY` mirror still works. Before the Go samples are published, the builder confirms that `go get repo.billbert.co/artifactory/<name>` resolves against Forgejo, using its go-get meta tags.
- **Publishing a subfolder.** `publish DIR` inside a larger git repo uses git plumbing. It reads the remote's `main` with `git ls-remote` and, when it exists, fetches it. It then commits the tree of `HEAD:<folder>` with `git commit-tree`, with the remote's `main` as the parent (no parent when the remote has none yet). It pushes that commit to `<org>/<name>` as `main` without force, then pushes the tag. Because each commit sits on top of the remote's `main`, the push fast-forwards by construction. The remote keeps one commit per publish, not the folder's history. This replaces `git subtree split`, because `git subtree` is not installed on this host or in the sandboxes. The link between the folder and its repo is the descriptor's `name`, so no local state is kept. A module whose folder is the root of its own repo is pushed as is.
- **Ecosystems.** One `artifactory.yaml` holds one ecosystem. A repo with several ecosystems keeps one `artifactory.yaml` per sub-project folder and runs commands with `--project`. When `init` finds both `go.mod` and `project.godot`, or neither, it exits 2 and asks for `--ecosystem`.
- **Install failures and repeats.**
  - `artifactory.yaml` and the index change only after the install line exits 0.
  - Installing a module that is already present is a no-op with a message. Upgrades are out of the first version.
  - `setup` steps are never run by the CLI. They are listed in `MODULES.md` (rule 6 treats them as defects to minimise, and running them would mean editing project files the model owns).
- **Skill file copies.** `init` writes `SKILL.md` only into harness folders that already exist: `.claude/skills/artifactory/`, `.agents/skills/artifactory/` and `.opencode/skills/artifactory/`. It reports each copy it writes and never creates the harness folder itself.
- **Harness and binary.** At the start of each round, the harness runs `go build` from the same checkout into the round's results folder and calls that binary. The embedded standard and the checked-out one are therefore identical by construction. `descriptor.py` is deleted, and the Python checkers that need descriptor data call `artifactory show --json`. That leaves one validator.

## Left to the builder

- The ranking formula for search, and the score threshold for "no module matches".
- The cache layout and its lifetime.
- How a godot-csharp `test` command that refers to a sibling demo project (`../CursorKit.demo`) is run by `publish`. One option is to clone the demo repo next to the module into a temporary folder.
- The exact wording of the skill file and the `AGENTS.md` block, kept close to `standard/preamble.md`.
