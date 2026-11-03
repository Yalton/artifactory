# Stitchability Standard, Draft 0.2

A module is stitchable when a weak model can find it, install it, wire it in and prove it is in use. These eight rules apply to every module, whatever its ecosystem. Each profile maps them to concrete files, commands and checks.

1. **Every module has a descriptor** at its root, in one format shared by all modules. Fields:
   - `name`, `ecosystem`, `version`
   - `summary`: one line, what the module does
   - `replaces`: short phrases naming what a consumer would otherwise hand-write
   - `install`: the one command that installs it
   - `setup`: required wiring steps, one line each. Empty is best.
   - `entry`: the types or functions a consumer calls first
   - `liveness`: how a checker proves the module is in use
   - `docs`, `example`, `test`: paths or commands
2. **Docs travel with the code.** Installing a module by its `install` command always brings its README and descriptor along. There is no other supported install.
3. **Consumers never edit module files.** A project configures, wraps or extends a module through its public surface. A needed change goes back to the module as a pull request. Each profile defines how a checker verifies modules are unmodified.
4. **Every installed module must be live.** It must be reachable from the program's real entry point, not only from tests. Each profile defines the check.
5. **Every module ships a worked example** showing it wired into a minimal host, short enough to read whole.
6. **Required setup is a defect to minimise.** Each `setup` step is a place a weak model can skip. A module that can work with zero setup should.
7. **A module index** is a single generated file listing every module's `name`, `summary`, `replaces`, `install` and `setup`. The model reads it before writing code. It is built only from descriptors.
8. **The index opens with a short consumer preamble** telling the model to read the index before writing code, install only with each module's `install` command, never edit module files, and wire every module it installs into the real entry point. After the preamble, the index carries the ecosystem's project notes: how to build, run and verify the result, and when to stop. The preamble and project notes live in `standard/` and are versioned with this standard. An enforcing tool such as arc may carry the module bullets (use before writing, never edit, wire every module) instead. The index then drops them from the preamble once the tool has a module registered, and the tool enforces them.
