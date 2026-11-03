You are writing a roadmap: a set of work items (beads) for a game that other sessions will build later. You do not build the game.

The game is described in `BRIEF.md` in the project root. Each bead you write will be worked later by a fresh session that cannot see `BRIEF.md`, so each bead must say everything that session needs.

Commands you can run:
- `artifactory search <terms>` finds modules (reusable code packages) that cover a need. It matches words, so use a short noun phrase such as `scene fade transition`.
- `artifactory show <Name>` shows what one module does and how to use it.
- `bd create "Title" --silent --stdin <<'EOF'` creates a bead. Put the description on the lines after it and end with a line that says only `EOF`. The quotes around `EOF` matter: they keep backticks and `$` in the description as typed. Add `-l gap` before `--stdin` when the bead is a gap (see step 4). Never put a description inside double quotes on the command line, because backticks there run as shell commands.
  Example:
  ```
  bd create "Title" -l gap --silent --stdin <<'EOF'
  Description text, with `backticks` kept as written.
  Modules: none
  EOF
  ```
  With `--silent`, `bd create` prints only the new bead's id. Write the ids down.
- `bd dep add <issue> <depends-on>` makes `<issue>` wait until `<depends-on>` is closed. Both are ids printed by `bd create`.
- `bd list` lists the beads you have made so far, with their ids.

Steps:
1. Read `BRIEF.md` in full.
2. List the separate needs in the brief (for example: scene changes, saving, settings, key rebinding, dialogue).
3. For each need, run `artifactory search` with a few words that describe it. Run `artifactory show <Name>` on each candidate to check that it really does the job.
4. Write the beads with `bd create`. Rules for every bead:
   - It can be finished by one fresh session in one sitting. Split anything bigger.
   - The description says what to build, in terms of what the player or developer sees (outcomes), and how to check it is done. Do not write code or code outlines.
   - The description has a line `Modules: A, B` naming the modules the bead uses, or `Modules: none` when it uses no module. Use exact module names from `artifactory search`.
   - If a bead's job is covered by a module, tell the builder to use that module and not to write that functionality itself.
   - If no module covers a need, add the label `gap` with `-l gap`, and say in the description that the builder has to write it.
   - Each contract in the brief's Contracts list must be copied word for word into the description of the bead that implements it. The builder will not see the brief. A contract that needs more than one bead goes into each of them.
5. Add dependencies with `bd dep add` so that `bd ready` lists the beads in a sensible build order. The first bead should set up the project, scenes and anything the others stand on.
6. Run `bd list` and check that every need in the brief has a bead, every bead has a `Modules:` line, and the contracts are all present.

Do not claim beads or change their status. Do not write any game files.

Write the roadmap only. Do not build anything.
