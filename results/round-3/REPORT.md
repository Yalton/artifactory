# Round 3 review

The probe is fair for all four Godot failures. In each one, a small fix by the model makes it pass, and t5 passes with the same event shape. Go 5/5 looks real. Its `tests` check passes trivially because no Go trial wrote a `_test.go` file, but the prompt doesn't ask for tests, so nothing is wrong there.

## Results

| Trial | Fails | Root cause (confirmed by re-running a scratch copy) | Class |
|---|---|---|---|
| t1 | player_moves `w=0 d=5` | `Main.cs` `Surface(size, pos, …)` never assigns `pos`, so every wall sits at the origin and the player (spawned at x=0) is pressed against one. Debug print: `coll=/root/Main/@StaticBody3D@18 n=(1,0,0)`. A second bug: `GetVector("move_forward","move_back","move_left","move_right")` with `Basis*(X,Y,0)` (`Player.cs:77-79`) makes D move the player *up*, and that is the only reason D got "past" the wall. | D |
| t2 | runs, player_moves `w=300 d=0` | `move_right` is bound to `physical_keycode:67` (C, not D). Changing it to 68 passes: `w=300 d=300`. The DevConsoleKit README says to add `toggle_dev_console`; the model read it at 2.3 min and never added the action. `DevConsoleUI._Input` (`DevConsoleUI.cs:104`) only errors when a key event arrives. I confirmed the model's own no-input run prints **0** ERROR lines. | D (key code); B (console action) |
| t3 | player_moves `found 2 Node3D` | `Player.cs:59` `body.AddToGroup("player", true)` also puts the mesh in the group. With that line removed: `w=6 d=6`. | D, with an A gap |
| t4 | runs, player_moves `w=13485 d=1.6M` | `Room.cs:73` `wall.GlobalPosition = pos` runs before `AddChild`, which raises `!is_inside_tree`. `Player.cs:51` `(Transform * new Vector3(...)) * Speed` adds the position into the velocity, so the player runs away exponentially even with no input. That gives the `!v.is_finite()` errors. | D |
| t5 | pass | — | — |

Is the probe fair on each point?
- **Event shape:** the probe sets both Keycode and PhysicalKeycode, which matches a `physical_keycode` binding.
- **w=300:** 300 m in 1 s is not a sane player. t2's collider is a child of the mesh (`Player.cs:48`), so it has no collision and goes through walls. The probe is *lenient* here, not unfair.
- **toggle_dev_console:** this is a real kit setup step. It sits in a prose paragraph after the README's Wiring section (`README.md:66`) and in `module.yaml` `setup:`, but MODULES.md shows only the install line (`index.py:31` renders just `d.install`).
- **Exactly one Node3D:** stricter than the prompt's "The player node is in the group `player`", but defensible.

## Before-finishing checks

- **t1** ran a clean check at 54.8 min and stopped. **t2** did the same at 35.3 min, **t3** at 31.7 min, and **t5** at about 50 min. The checks were run correctly. They just can't see these bugs: none of them sends input, so they miss broken movement, miscounted group members, and errors that only fire on input.
- **t4** never finished. It lost about 54–100 min to a `_PhysicsProcess(float delta)` override, decompiling GodotSharp and reflection-dumping APIs. Its first run used `--editor false` and opened the editor instead of the game. The session then ended mid-turn at about 106 min (reason null, not a timeout) just after it had seen `!v.is_finite()`.

## What t5 did differently

- World-space velocity from `GetActionStrength` on X/Z with no Transform maths.
- Collider added as a direct child of the body.
- Only the body in group `player`.
- Bound `toggle_dev_console`.
- Fixed its own `!is_inside_tree` errors over five check runs before stopping.

## Causes ranked

1. **No way to check movement or input headless (A).** Hit 4/4. Every failure is visible the moment W and D are pressed.
2. **The model's own movement and geometry bugs (D).** t1 (wall position, axes), t2 (key code), t3 (mesh in group), t4 (Transform used as a vector).
3. **DevConsoleKit's action requirement is easy to miss and fails late (B).** t2. Other trials missed it too but didn't instance the UI, so it never fired.
4. **t4's API detour (D, which the notes could have prevented).** The wrong `delta` signature and `--editor false`.

## Proposed changes for round 4

1. **`standard/consumer/godot-csharp.md`, Before finishing: a copyable movement self-check.** Give a ~40-line `MoveCheck.cs` autoload that does nothing unless `OS.GetCmdlineUserArgs()` contains `--move-check`. When it does: at 1 s it asserts exactly one Node3D in `player`, sends W then D for 1 s each via `Input.ParseInputEvent` (Keycode and PhysicalKeycode), and prints `MOVECHECK w=… d=… dir_w=… dir_d=…`. Command: `godot --headless --path . -- --move-check`. Required result: both distances between 1 and 20 per second, W along -Z, D along +X, and no `ERROR:` lines. Sending key events also surfaces input-only errors like t2's. It is gated, so it can't interfere with the checker's probe, and it matches no duplication pattern.
2. **Same file, a short "Player pitfalls" list (facts, not a full controller).**
   - Key codes: W=87, A=65, S=83, D=68.
   - `_PhysicsProcess(double delta)`.
   - Move in the XZ plane. `Input.GetVector(negX, posX, negY, posY)`, so `GetVector("move_left","move_right","move_forward","move_back")` maps to `(x, 0, y)`.
   - Never multiply by `Transform`; use `Basis` if anything.
   - The CollisionShape3D must be a direct child of the body.
   - Only the body joins `player`.
   - Set `Position`/`GlobalPosition` after `AddChild`.
   - Spawn the player above the floor.
   - Never pass `--editor`.
3. **DevConsoleKit (`stitchability`) API.** In `DevConsoleManager._Ready`, register `toggle_dev_console` with a backtick default when `!InputMap.HasAction(...)`, and remove the setup step. If not, at least move the action's `[input]` ini block into the README Wiring section.
4. **`tools/artifactory/index.py`.** Render each descriptor's `setup:` lines under its install command in MODULES.md, so kit setup steps reach the model without it having to read every README.
5. **Probe, optional (borderline C).** When several Node3D are in `player` and exactly one is an ancestor of all the others, test that one. The prompt doesn't say "only", so t3's solution is arguably correct. If you'd rather not change the checker, item 2's "only the body" line covers this case.

Scratch reproductions are in `/data/fast/state/tmp/claude-1000/r3rev/` (t1, t1b, t2, t3). No files under the repo were changed.