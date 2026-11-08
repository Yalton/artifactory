---
name: artifactory
description: Use before writing any new functionality, a feature, system or helper, and when planning or splitting work into beads. Search the module catalog first, so existing modules are used instead of rewritten.
---

Artifactory is a catalog of stitchable modules. Reuse beats writing. The project's `MODULES.md` lists the modules in scope; `AGENTS.md` holds the ecosystem's rules and the commands that build and run the project.

## Before writing code

1. Read `MODULES.md` and the artifactory block in `AGENTS.md`.
2. Run `artifactory search WORDS...` for each need (it searches the project's ecosystem; `--ecosystem all` searches every one). Run `artifactory show NAME` on a hit to read its descriptor.
3. A hit that covers the need is the answer: use it. Nothing is written in its place.
4. Done when every need has a module or a recorded gap.

With arc present, run `arc find <words>` before writing a new piece. When arc is on, it also enforces the module rules below: it denies edits under module paths and its gate checks wiring.

## Using a module

- Install with `artifactory install NAME...` and nothing else. It runs the module's own install line and records it in `artifactory.yaml`.
- Installed module files are read-only to you. Configure, wrap or extend a module through its public surface.
- Wire every installed module into the program's real entry point, following the Wiring section of its README. A module only tests reach is not in use.
- Before finishing, build and run the project. Confirm each module's liveness marker appears and no errors print. Then stop: a wired module with a printing marker is in use. Add no features to exercise it.
- `artifactory add NAME...` puts a module in scope without installing it. `artifactory index` regenerates `MODULES.md` and the `AGENTS.md` block.

## Beads

Each bead names the modules it uses, or says `modules: none`. Search before the bead is written, so the list is real.

## Gaps

A need with no module is a gap.

1. Note the gap in the bead: the words searched and that nothing matched.
2. Build the piece in its own folder, to the standard: `module.yaml`, `README.md`, and a liveness marker. `artifactory validate FOLDER` must pass.
3. Keep the folder free of project-specific code so `artifactory publish FOLDER` can lift it out later.

Every command takes `--json`. Exit 0 is ok, 1 means the check found problems, 2 is a usage or environment error.
