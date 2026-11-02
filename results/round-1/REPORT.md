# Round 1 review

## Results

| Test | Pass | Failing checks |
|---|---|---|
| go-url-shortener | 3/5 | t2, t3: no_duplication only |
| godot-capsule-room | 0/5 | all: modules_live, player_moves, no_duplication; t1-t4: runs; t2, t5: modules_unmodified; t1-t3 timed out |

Re-check with literal markers (checker unchanged otherwise): t1, t2 and t5 print all eight `[<Kit>] live` lines. The kits print their own marker from autoload `_Ready` (`CrashHandler.Initialize()` for CrashKit, the `SaveSlot` constructor for RunSaveKit). All five trials registered the seven autoloads and called CrashKit.

Fixing every non-model cause below still leaves Godot at 0/5: each trial also has a model-side runs or player_moves failure.

## Causes, ranked by trials sunk

**1. Kit descriptors give prose instead of the marker (B). 5/5 Godot (modules_live).**
Kit commits have `liveness: "prints [InputRemapKit] live at startup"` (`addons/InputRemapKit/module.yaml:18`, same in all 8 kits). The profile says the value is "The marker line". `godot.py:_marker` greps for the descriptor string as given, so the check can never pass. t4 installed `main` commits with no `module.yaml`, so it fell back to `[X] live`, but the game never ran.

**2. Duplication regexes match documented kit usage (C). 5/5 Godot; the only no_duplication cause in t1, t3, t4 and t5.**
- `crash_reports` (t2-t5): CrashKit README:57 itself shows `CrashHandler.ReportDirectory = "user://crash_reports/";`.
- `user://.*save` (t1, t2, t3, t5): RunSaveKit README:57 wiring is `new SaveSlot("user://run_save.dat", ...)`. The constructor needs a path, so correct use fails. The baseline report already flagged this.
- t1 `scenes/TransitionDemo.cs:8 class TransitionDemo : Node2D` is a scene that calls `TransitionManager.Instance.TransitionToScene`. The regex `(Control|Node|CanvasLayer)` has no `\b`, so it matches `Node2D`.

**3. Hand-written project.godot and .tscn files are wrong (D, can be reduced by A). 4 trials (runs, player_moves).**
- t2: `project.godot:34 [input_map]` (should be `[input]`) gives `InputMap action "move_forward" doesn't exist`. The player is found but `w=0 d=0`.
- t3: `project.godot:14 config/run/main_scene` gives "no main scene defined".
- t4: same key, plus `#` comments and a made-up `InputEventKey("InputEventKey", ...)`, gives `error code 43` (parse failure).
- t5: `Main.tscn:66 [node name="Player" type="Node3D"]` never instances `Player.tscn` (its ext_resource `2_player` is unused). Result: "found 0 Node3D in group player".

**4. Time spent on Godot UIDs and file-format experiments (D, can be reduced by A). Timeouts in t1-t3; modules_unmodified in t2.**
Shell commands mentioning uid: t1 21, t2 54, t3 9, t5 13. t5 spent minutes 4-11 reverse-engineering Godot's UID hash, with web fetches of `resource_uid.cpp`. At minute 54, t2 rewrote kit files with its own hashes (`M InputDeviceTracker.cs.uid`: `uid://4xn2f0qrpu4j` became `uid://b5cd4vjeihkgq`). t1 and t3 spent minutes 80-120 building throwaway /tmp test projects to debug .tscn parsing.

**5. RunSaveKit does not commit its `.uid` files (B). 1 trial (t5 modules_unmodified).**
`?? Log.cs.uid, SaveOutcome.cs.uid, SaveSlot.cs.uid`. Godot's import step generates these files. The other seven kits commit theirs, and RunSaveKit commits 0 of 3. Any consumer that opens or imports the project gets a dirty kit tree.

**6. Real reimplementation, Go (B). 2 trials (Go t2, t3).**
Both trials call `ctx, stop := signal.NotifyContext(..., SIGINT, SIGTERM)` before `httpserver.Run` (t2 `main.go:25`, t3 `main.go:105`). `Run` already does this (`httpserver.go:37`), so the hit is genuine. The cause is the README wiring: it passes an undeclared `ctx` and never says that `context.Background()` is enough. Passing trials used `context.Background()`, as `example/main.go` does.

**7. 2D player is rejected by the probe (C, borderline). 1 trial (t1).**
`Main.tscn:86` puts a `CharacterBody2D` in group `player`. CheckerProbe counts only `Node3D`. The prompt does not say 3D. t1 would still fail runs: `MainScene.cs:31 GetTree().Root.AddChild` during `_Ready` gives "Parent node is busy" (D).

**8. Real CursorKit duplication (D). 1 trial (t2).**
`PlayerMovement.cs:39 Input.MouseMode = Input.MouseModeEnum.Captured`, despite the CursorKit README ("consumers should Push/Pop rather than assigning to it themselves").

**9. Install deviation (D). 1 trial (t4).**
t4 tried `ssh://git@repo.billbert.co/yalt/X.git`, which the harness `insteadOf` rewrite does not cover. It hit ssh errors for 8 minutes, then ran `submodule add <mirror path>` without `-b stitchability`. That got `main` commits with no markers (`InputRemapKit ddd1412`). The harness is outside the changeable set.

## Proposed changes for round 2

1. **8 kits, `module.yaml`:** set `liveness: "[<Name>Kit] live"` exactly. In `tools/artifactory/descriptor.py`, reject a godot-csharp `liveness` that does not match `^\[\w+Kit\] live$`, so this cannot recur silently.
2. **`tests/acceptance/godot-capsule-room/duplication.yaml` (checker fix):** drop `crash_reports` and `user://.*save`. They match documented kit configuration, and `FileAccess.Open` already catches real save code. Add `\b` after the base types in the Transition and Console class patterns (`(Control|Node|CanvasLayer|Panel)\b`).
3. **`standard/profiles/godot-csharp.md`, new "Host project files" section** with exact, copyable snippets: `[application]` `run/main_scene="res://..."` (not `config/run/...`), an `[input]` action block with a `physical_keycode` InputEventKey, `;` comments only, and instancing a scene with `instance=ExtResource("id")`. Also add: "Never write or edit `.uid` files or `uid=` attributes. Omit them, and Godot generates them on import. `.uid` files under `addons/` belong to the kit."
4. **`standard/preamble.md` plus the profile:** add a final rule, "Before finishing, run the game headless and confirm each module's marker prints and no `ERROR:` lines appear." The Godot profile supplies the command (`godot --headless --path . --quit-after 300`) and says to build first with `dotnet build`.
5. **RunSaveKit (`stitchability`):** commit `Log.cs.uid`, `SaveOutcome.cs.uid` and `SaveSlot.cs.uid`.
6. **`samples/go/httpserver/README.md` Wiring:** start the snippet with `ctx := context.Background() // Run already stops on SIGINT/SIGTERM; do not add signal.NotifyContext`.
7. **`tools/artifactory/godot_probe/CheckerProbe.cs` (checker fix, optional):** accept exactly one `Node2D` or `Node3D` in group `player`, since the prompt does not fix the dimension.
8. **CursorKit README Wiring:** add a mouse-capture example for a player or camera (`InputModeManager.Instance.Push(InputMode.Captured)` in `_Ready`, `Pop()` in `_ExitTree`), so capturing the mouse does not lead to assigning `Input.MouseMode` directly.