# Round 2 review

## Results

| Test | Pass | Failing trials |
|---|---|---|
| go-url-shortener | 2/5 | t1, t4, t5: only no_duplication (`signal.NotifyContext`) |
| godot-capsule-room | 1/5 | t1: timeout, runs, player_moves, modules_live. t2: player_moves. t4: timeout only (all checks pass). t5: timeout and player_moves |

Correction to the brief: t5 also hit the 2 h timeout (`checker.json` reason `timeout`).

## Causes, ranked by trials sunk

**1. Go: the failing trials read the source, not the README (B). Sinks 3/3 Go failures.**
- The trials that passed read the README Wiring: t2 found it with `find ... -name README.md`, and t3 read `httpserver@v0.1.1/README.md`.
- t1, t4 and t5 never opened the README. They read only `httpserver.go`; t4 also read `httpserver_test.go`, and t5 also read `example/main.go`.
- What a source reader sees is `func Run(ctx context.Context, ...)` and the comment "triggered by ctx being cancelled or SIGINT/SIGTERM" (`httpserver.go:26-28`). Nothing there says not to wrap the ctx. The example passes `context.Background()` with no comment.
- So it is idiom filling a slot: main builds a signal ctx and hands it to the server. t5 even knew Run handles signals and added one anyway: `// Graceful shutdown on SIGINT/SIGTERM is owned by httpserver.Run; we just hand it a context that dies on signal.` (`t5 main.go:24-26`).
- Nothing in MODULES.md tells the model to read a module's README or where to find it after `go get`, and the preamble's "Wiring snippet" line names no location. That is also an (A) gap.

Is the check fair? Mostly yes. MODULES.md lists "graceful shutdown on SIGINT and SIGTERM" under "Use instead of writing", and a second NotifyContext writes exactly that. The cost is redundancy, not a bug, so this is the least harmful duplication the check can catch. Keep the check.

Should the API change? Yes. A `ctx` first parameter on a "Run forever" call is the hole the idiom fills. Docs only help models that read them, and 3 of 5 didn't. Changing the API puts the fix in the one file every trial reads.

**2. Godot: `script=` in the `[node ...]` header is silently ignored (A). Sinks t2 and t5 player_moves, and contributes to t1.**
- t2 `Player.tscn:13`: `[node name="Player" type="CharacterBody3D" script=ExtResource("1_player")]`
- t5 `Player.tscn:19`: `... script="ExtResource( 1_player )"]`
- Godot reports nothing for either. I reproduced t2 in a scratch copy with an autoload that prints the player after 1 s: `DBG group=0 player=<CharacterBody3D#...> script= scene=Main`. The script never attaches, so the `AddToGroup("player")` in `Player._Ready` never runs. Main.cs is not attached either; its `[InputRemapKit] move_forward =` print never appears.
- The model's own check (count the markers, then grep for `ERROR:`) cannot catch this, because the markers come from kit autoloads.
- t3 and t4 passed with `script = ExtResource(...)` on its own line under the header (t3 `Player.tscn:20`, t4 `Player.tscn:16`).
- The profile's Host project files section shows `instance=` but never shows how to attach a script.

**3. No stop rule; gold-plating, then wiping the engine cache (A, plus B for DevConsoleKit). Sinks t4's timeout and much of t5's time.**
- At 57.5 min t4 said "The run now **passes both criteria**". It then kept fixing its own invented `teleport` console command, justifying it with "use... its real job".
- At 58.9 min it cleared `.godot/mono/temp`. It then spent 60 minutes on the engine's "is not compiling" errors and `global_script_class_cache.cfg`, with 17 `rm -rf .godot` commands. The checker's own `dotnet build` and `--import` worked fine on the result.
- Adding custom commands to DevConsoleKit cost t4 (54-57 min, an InvalidCastException from `GetParent<DevConsoleManager>()`) and t5 (95-119 min, `parent="DevConsoleManager"` in a .tscn).
- The README says "add it as a child node of the `DevConsoleManager` autoload" but has no code for doing that.

**4. Model loops on `")` and `"]` (D, amplified by A). Sinks t1 (runs, player_moves, modules_live, timeout).**
- `Main.tscn:21`: `[node name="Main" type="Node3D" script=ExtResource("1_main") groups=["player]`. This gives `Parse Error: Expected ','` at line 23.
- t1 spent about 16 to 118 min on `od -c` and printf workarounds, convinced the edit tool was swapping characters ("swap trap").
- Header attributes in .tscn files make these quote and bracket sequences unavoidable.

**5. t5 guessed C# API names (D).** It spent about 45 to 85 min grepping GodotSharp.xml and building a MetadataLoadContext reflector to find `LightSource`/`PointLight3D` for a decorative Room.cs.

**What t3 did that the others didn't:** a plain scene (`[node name="Main" type="Node"]` then `script = ExtResource(...)`); no custom console commands or extra decoration; `AddToGroup` in an attached script; and it stopped at 39 min once the checks passed. t2 also stopped at 39 min, but with the unattached script.

No checker bugs (C) found. The probe's 1 s lookup is fair: a correctly attached script joins the group in `_Ready`.

## Proposed changes for round 3

1. **`samples/go/httpserver` (API, bump to v0.2.0).** Change to `func Run(addr string, h http.Handler, opts ...Option) error`, and add `WithContext(ctx)` for tests and embedding. Doc comment: "Run blocks until SIGINT or SIGTERM and handles them itself; do not install signal handlers." Update `httpserver_test.go`, `example/main.go`, the README Wiring and the descriptor. This leaves no ctx slot for the NotifyContext idiom to fill.
2. **`standard/profiles/godot-csharp.md` and `standard/consumer/godot-csharp.md`, Host project files.** Add a node-with-script snippet:
   ```
   [node name="Player" type="CharacterBody3D"]
   script = ExtResource("1_player")
   ```
   plus the warning: "`script=` or any property inside the `[node ...]` header is silently ignored." Also: "Keep .tscn files to a root node and a script. Create meshes, lights and colliders in C# `_Ready()`, and join groups with `AddToGroup()` in code, not `groups=[...]`." This targets causes 2 and 4.
3. **`standard/consumer/godot-csharp.md`, Before finishing.** Add: "Print a line from each of your own scripts' `_Ready` (for example `GD.Print("[Player] ready")`) and confirm it appears. Kit markers do not prove your scripts are attached." Add to the same section: "Never delete `.godot/`. If autoloads report 'is not compiling', run `dotnet build` then `godot --headless --import`."
4. **`standard/preamble.md`, new last rule.** "When the Before-finishing checks pass, stop. A module is in use once it is wired and its marker prints. Do not add extra features (console commands, menus) just to exercise it." This targets t4.
5. **`standard/consumer/go.md`.** After the install step, add: "Read each module's README before coding: `cat $(go list -m -f '{{.Dir}}' <path>)/README.md`." Name README Wiring as the snippet the preamble's Wiring line refers to.
6. **DevConsoleKit README (`stitchability`), "Adding your own commands".** Add the exact attach line `DevConsoleManager.Instance.CallDeferred(Node.MethodName.AddChild, new MyGameCommands());` from the host's `_Ready`, and add: "Do not declare handlers in a .tscn or parent them anywhere else."