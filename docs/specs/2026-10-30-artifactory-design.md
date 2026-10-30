# Artifactory: design notes

Status: early design. Captured from the 2026-10-30 brainstorm. Nothing is built.

## Why

Local models can run long, unattended glue work cheaply, but they are not good
enough to build hard parts from scratch. Frontier models are. The artifactory
splits the work along that line:

- Frontier models build a small set of vetted, reusable modules once.
- Local models stitch those modules together into finished projects.
- Frontier models also benefit: they stop re-inventing the same code on every
  run, which saves tokens.

The modules are the niche or custom pieces that public libraries do not cover.
The Godot C# kits (AbilityKit, CrashKit, LootKit, ... and the `GodotKits`
monorepo) are the reference case: a local model does reasonably well when it has
pre-made, vetted kits to stitch together instead of writing a game from nothing.

The operator has a backlog of backburner projects to hand to local models once
this exists.

## Consumers

- **Vapula** fleet workers (`ProgramsBots/Vapula`).
- **Local agent harnesses** on the workstation (Claude Code, Codex, OpenCode).
  These are first-class consumers, not an afterthought. Discovery must not live
  only inside Vapula.
- **VentureAutomation** (`Tech/VentureAutomation`), whose spec already describes
  a Go-only "Component Artifactory". That section should become the Go ecosystem
  of this project rather than a separate system.

## Principles agreed so far

1. **Storage is the easy part.** Forgejo (`repo.billbert.co`) holds the code and
   packages, under a dedicated org so the ~260 repos under `yalt` stop growing.
   The Forgejo package registry is enabled and has never been used.
2. **Stitchability is the real product.** What makes a module usable by a weak
   model (small stable interface, short accurate usage doc, a worked example of
   wiring it in, tests that prove the glue is right) is the interesting design
   problem. It gets its own research and design session.
3. **Two roles.** Frontier models create and harden modules through review.
   Local models consume them and may propose new ones, which are vetted before
   they land.
4. **One publish gate for everyone.** New or changed modules arrive as PRs into
   the artifactory org, whether the author is a Vapula worker or a local session
   that holds credentials. Vapula workers hold no Forgejo credentials by design
   (`controller/catalog/server.py`), so a PR-based gate also fits that rule.
5. **Organized by ecosystem, not one language.** Existing reusable code is mostly
   Godot C#, Python and Go. Each ecosystem keeps its native package format.
6. **Extraction is continuous.** When duplication across projects is noticed,
   it is pulled into a module.

## Three sub-projects

1. **Stitchability standard.** Research and define what a module must contain
   for a weak model to wire it in reliably, and how to measure that. This decides
   the contents of each module's descriptor file.
2. **Artifactory core.** Forgejo org, per-module descriptor and its index,
   discovery service exposed as an MCP server (plus a CLI fallback) for both
   Vapula and local harnesses, and the publish gate.
3. **Duplication scanner.** A scheduled, largely autonomous job in which a
   frontier model sweeps the Forgejo repos and files extraction candidates.
   Likely submitted as a Vapula job.

Recommended order: 1, then 2, then 3. The standard decides the descriptor
format the core is built around; the scanner needs somewhere to put what it
finds.

## Existing pieces to build on

- Vapula read-only catalog service (`controller/catalog/server.py`): `/search`,
  `/readme`, `/tree`, `/file`, `/archive` over owner repos. Workers already reach
  it through `FLEET_CATALOG_URL`. Candidate to grow into, or be replaced by, the
  discovery service.
- Vapula `.fleet.json` `module_tags` / `module_summary`
  (`controller/fleet/project.py`) and `reusable_modules` matching in
  `agent-fleet-scan.py`. Written and tested, not wired into production.
- Vapula `bin/sync-fleet-skills`: an existing PR-based publish flow into
  `yalt/fleet-skills`.
- Vapula `fleet` org: where agent-created repos land today. Currently holds
  about a dozen throwaway calculator and smoke-test repos.
- VentureAutomation spec (`docs/specs/2026-10-26-venture-automation-design.md`):
  `component.yaml` schema, SQLite capability index, extension loop. Note its
  internal inconsistency: repo `yalt/venture-artifactory` versus import paths
  `repo.billbert.co/artifactory/pkg/...`.

## Open questions

- Order: confirm 1 → 2 → 3, or stand up the core first with a placeholder
  format so the Godot kits can move in sooner.
- Where do local models fail today when stitching the Godot kits? This is the
  main input to the stitchability standard.
- Should the duplication scanner stop at filing candidates, or also open the
  extraction PR?
- Org name on Forgejo (`artifactory` matches the VentureAutomation import paths).
- Does Vapula's catalog service grow into the discovery service, or does a new
  service replace it?
