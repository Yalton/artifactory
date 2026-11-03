Read this index before writing any code.

- If a module here does what you need, use it instead of writing your own.
- Install a module only with its `install` command.
- Never edit files inside an installed module. Configure, wrap or extend it through its public surface.
- Wire every module you install into the program's real entry point. A module that only tests reach is not in use.
- Before finishing, build and run the project and confirm each module's liveness marker appears and no errors are printed. The project notes below give the commands.
- The Wiring section of the module's README shows where its calls go. Merge it into your existing class of the same name instead of adding a second one.
- When the Before-finishing checks pass, stop. A module is in use once it is wired and its marker prints. Do not add features the task did not ask for (console commands, menus) just to exercise a module.

## Project notes (godot-csharp)

### Before finishing

Build, then run the game headless and check the output:

```
dotnet build
godot --headless --path . --quit-after 300
```

Each installed kit's marker must appear and no `ERROR:` line may be printed.

Also print a line from each of your own scripts' `_Ready` (for example `GD.Print("[Player] ready")`) and confirm it appears. Kit markers do not prove your scripts are attached.

Then check movement, the camera and the room. Copy this to `MoveCheck.cs` in the project root. It does nothing unless run with `--move-check`:

```csharp
using System.Globalization;
using System.Linq;
using Godot;

// Self-check autoload: inert unless run with `-- --move-check`.
public partial class MoveCheck : Node
{
    private ulong _t0; private int _stage;
    private Node3D _p;
    private Vector3 _a, _b, _c;
    private string _why = "";
    private string _view0 = "";
    private string _room = "";

    public override void _Ready()
    {
        if (!OS.GetCmdlineUserArgs().Contains("--move-check")) { SetProcess(false); return; }
        _t0 = Time.GetTicksMsec();
    }

    public override void _Process(double delta)
    {
        double t = (Time.GetTicksMsec() - _t0) / 1000.0;
        if (_stage == 0 && t >= 1)
        {
            var n = GetTree().GetNodesInGroup("player").OfType<Node3D>().ToList();
            if (n.Count == 1) _p = n[0]; else _why = $"{n.Count} Node3D in group player (need exactly 1)";
            _a = _p?.GlobalPosition ?? default; _view0 = Unseen(); _room = RoomMissing(); Press(Key.W, true); _stage = 1;
        }
        else if (_stage == 1 && t >= 2) { Press(Key.W, false); _b = _p?.GlobalPosition ?? default; Press(Key.D, true); _stage = 2; }
        else if (_stage == 2 && t >= 3)
        {
            Press(Key.D, false); _c = _p?.GlobalPosition ?? default; _stage = 3;
            Vector3 w = Flat(_b - _a), d = Flat(_c - _b);
            Vector3 dw = w.Normalized(), dd = d.Normalized();
            bool ok = _p != null && w.Length() is >= 0.5f and <= 20f && d.Length() is >= 0.5f and <= 20f && dw.Z < -0.7f && dd.X > 0.7f;
            string view1 = Unseen(), view = _view0 != "" ? _view0 : view1;
            bool seen = view == "", room = _room == "";
            if (_why != "") GD.PrintErr("MOVECHECK FAIL: " + _why);
            GD.Print($"MOVECHECK ok={(ok && seen && room).ToString().ToLower()} camera_sees_player={(seen ? "true" : view)} room={(room ? "true" : "missing:" + _room)} w={F(w.Length())} d={F(d.Length())} dir_w={dw} dir_d={dd}");
            GetTree().Quit(ok && seen && room ? 0 : 1);
        }
    }

    // World boxes of every drawn mesh that is not part of the player.
    private System.Collections.Generic.List<Aabb> Boxes() =>
        GetTree().Root.FindChildren("*", "GeometryInstance3D", true, false).OfType<GeometryInstance3D>()
            .Where(g => g.IsVisibleInTree() && Drawn(g) && g != _p && !_p.IsAncestorOf(g))
            .Select(g => g.GlobalTransform * g.GetAabb()).ToList();

    private static bool Drawn(GeometryInstance3D g) => g is not MeshInstance3D mi
        || (mi.Mesh?.GetRid() is Rid r && r.IsValid && RenderingServer.MeshGetSurfaceCount(r) > 0);

    // Directions from the player with no drawn geometry: a floor below, a wall on each side.
    private string RoomMissing()
    {
        if (_p == null) return "no_player";
        Vector3 o = _p.GlobalPosition; var boxes = Boxes();
        var dirs = new (string, Vector3)[] { ("down", Vector3.Down * 10), ("+x", Vector3.Right * 100),
            ("-x", Vector3.Left * 100), ("+z", Vector3.Back * 100), ("-z", Vector3.Forward * 100) };
        return string.Join(",", dirs.Where(d => !boxes.Any(b => b.HasPoint(o) || b.IntersectsSegment(o, o + d.Item2))).Select(d => d.Item1));
    }

    // "" when the current camera sees a drawn mesh of the player at 16:9, else why not.
    private string Unseen()
    {
        Camera3D cam = GetViewport().GetCamera3D();
        if (_p == null) return "no_player";
        if (cam == null) return "no_camera";
        if (_p.IsAncestorOf(cam) && cam.GlobalPosition.DistanceTo(_p.GlobalPosition) <= 2f) return ""; // first person
        var meshes = _p.FindChildren("*", "GeometryInstance3D", true, false).OfType<GeometryInstance3D>()
            .Where(g => g.IsVisibleInTree() && Drawn(g)).ToList();
        if (meshes.Count == 0) return "no_drawn_mesh";
        var own = new Godot.Collections.Array<Rid>(_p.FindChildren("*", "CollisionObject3D", true, false)
            .OfType<CollisionObject3D>().Append(_p as CollisionObject3D).Where(b => b != null).Select(b => b.GetRid()));
        var walls = Boxes().Where(b => !b.HasPoint(cam.GlobalPosition)).ToList();
        bool framed = false;
        foreach (var g in meshes)
        {
            Aabb box = g.GetAabb(); Vector3 mid = box.GetCenter();
            foreach (Vector3 p in new[] { mid, mid with { Y = box.Position.Y + box.Size.Y * 0.9f } }) // centre and top
            {
                Vector3 c = g.GlobalTransform * p, l = cam.GlobalTransform.AffineInverse() * c;
                float half = -l.Z * Mathf.Tan(Mathf.DegToRad(cam.Fov / 2f)); // headless viewports are 64x64, so frame at 16:9 by hand
                if (-l.Z < cam.Near || Mathf.Abs(l.Y) > half || Mathf.Abs(l.X) > half * 16f / 9f) continue;
                framed = true;
                var ray = PhysicsRayQueryParameters3D.Create(cam.GlobalPosition, c); ray.Exclude = own;
                if (GetViewport().World3D.DirectSpaceState.IntersectRay(ray).Count == 0
                    && !walls.Any(b => b.IntersectsSegment(cam.GlobalPosition, c))) return "";
            }
        }
        return framed ? "blocked" : "out_of_frame";
    }

    private static Vector3 Flat(Vector3 v) => new(v.X, 0, v.Z);
    private static string F(float f) => f.ToString("0.##", CultureInfo.InvariantCulture);
    private static void Press(Key k, bool down) =>
        Input.ParseInputEvent(new InputEventKey { Keycode = k, PhysicalKeycode = k, Pressed = down });
}
```

Add the autoload `MoveCheck="*res://MoveCheck.cs"` under `[autoload]`, run `dotnet build`, then:

```
timeout 30 godot --headless --path . -- --move-check
```

It passes only if it prints `MOVECHECK ok=true` and no `ERROR:` line. No `MOVECHECK` line within 30 s is a failure: check the autoload line and `dotnet build`. It fails if the node in group `player` is not exactly one Node3D, or W and D do not move it about 0.5 to 20 units (W along -Z, D along +X), or the camera cannot see the player before and after it moves, or there is no room around the player's start. Then `camera_sees_player` names why: `no_camera`, `no_drawn_mesh` (the player has no visible built-in mesh such as `CapsuleMesh`), `out_of_frame`, or `blocked` (a wall, floor or ceiling is in between, drawn or solid). `room=missing:<directions>` lists where no drawn floor (`down`) or wall (`+x`, `-x`, `+z`, `-z`) surrounds the player's start. Fix the cause and re-run until it passes.

### Player pitfalls

- Key codes: W=87, A=65, S=83, D=68 (C=67 is not D).
- Override `_PhysicsProcess(double delta)`. `float delta` does not compile.
- Move in the XZ plane: `Input.GetVector(negX, posX, negY, posY)`, so `GetVector("move_left","move_right","move_forward","move_back")` gives `new Vector3(v.X, 0, v.Y)`. Set that world-space velocity directly. Never multiply a velocity by `Transform`.
- Make the `CollisionShape3D` a direct child of the body.
- Build each floor and wall as a `StaticBody3D` with a `MeshInstance3D` and a `CollisionShape3D` as children. A `CollisionShape3D` under a `MeshInstance3D` or a plain `Node3D` collides with nothing, so the player walks through that wall.
- Only the body joins group `player`, not its mesh.
- Set `Position`/`GlobalPosition` after `AddChild`, not before.
- Spawn the player above the floor.
- Add a `Camera3D` with `Current = true` inside the room that keeps the player in view (a ceiling or wall between them hides it), and a light. Without a camera the window is plain grey even though the game runs. A camera parented to the player within 2 units counts as first person.
- Give the player a built-in mesh (`new MeshInstance3D { Mesh = new CapsuleMesh() }`). Never subclass `Mesh`: a C# `Mesh` subclass draws nothing.
- Never pass `--editor`.

Never delete `.godot/`. If autoloads report "is not compiling", run `dotnet build`, then `godot --headless --import`.

### Host project files

Copy these exactly. They were written by Godot 4.7 and load with no errors. Hand-invented variants of these formats fail.

`project.godot`: comments start with `;`, never `#`. The main scene key is `run/main_scene` under `[application]`, not under `config/`.

```ini
[application]

config/name="MyGame"
run/main_scene="res://Main.tscn"
```

Input actions go under `[input]` (not `[input_map]`). One key event, bound by physical key (`physical_keycode` 87 is W; `"device":-1` matches every device):

```ini
[input]

move_forward={
"deadzone": 0.2,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":0,"physical_keycode":87,"key_label":0,"unicode":0,"location":0,"echo":false,"script":null)
]
}
```

For another key, change only `physical_keycode` (the Godot `Key` enum value). Add more `Object(...)` entries to `events` for more keys.

Instancing a scene inside another `.tscn` takes an `ext_resource` of type `PackedScene` and a node with `instance=`. A node declared with only `type=` does not instance the scene:

```ini
[gd_scene format=3]

[ext_resource type="PackedScene" path="res://Player.tscn" id="1_player"]

[node name="Main" type="Node3D"]

[node name="Player" parent="." instance=ExtResource("1_player")]
```

To attach a script, put `script = ...` on its own line under the `[node ...]` header. `script=` or any property inside the header is silently ignored:

```ini
[gd_scene format=3]

[ext_resource type="Script" path="res://Player.cs" id="1_player"]

[node name="Player" type="CharacterBody3D"]
script = ExtResource("1_player")
```

Keep each `.tscn` to its root node, its `instance=` nodes and a script. Create meshes, lights and colliders in C# `_Ready()`, and join groups with `AddToGroup()` in code, not `groups=[...]`.

Never write or edit `.uid` files or `uid=` attributes. Omit them. Godot generates them on import. `.uid` files under `addons/` belong to the kit.

## CrashKit

Crash reports, freeze watchdog and breadcrumbs for managed and engine-swallowed exceptions.

Use instead of writing:
- writing crash reports on unhandled exceptions
- a freeze watchdog for a hung main thread
- detecting that the last run ended abnormally
- logging engine-swallowed exceptions

```
git submodule add git@repo.billbert.co:artifactory/CrashKit.git addons/CrashKit
```

Setup:
- call CrashKit.CrashHandler.Initialize() once, from the earliest autoload _Ready or a bootstrap script

## CursorKit

Push/pop stack that owns the mouse cursor mode so overlapping UI layers never fight.

Use instead of writing:
- a stack of mouse-mode owners for menus and overlays
- setting Input.MouseMode directly from several scripts

```
git submodule add git@repo.billbert.co:artifactory/CursorKit.git addons/CursorKit
```

Setup:
- project.godot [autoload]: InputModeManager="*res://addons/CursorKit/InputModeManager.cs"

## DebugLogKit

Per-module debug logging that can be toggled on and off and is saved between runs.

Use instead of writing:
- a debug print wrapper with on/off switches per system
- saving which debug channels are enabled

```
git submodule add git@repo.billbert.co:artifactory/DebugLogKit.git addons/DebugLogKit
```

Setup:
- project.godot [autoload]: DebugLogger="*res://addons/DebugLogKit/DebugLogger.cs"

## DevConsoleKit

In-game developer console with a command dispatcher, history and built-in commands.

Use instead of writing:
- a debug console UI with typed commands
- a command registry and dispatcher for cheats and debug actions

```
git submodule add git@repo.billbert.co:artifactory/DevConsoleKit.git addons/DevConsoleKit
```

Setup:
- project.godot [autoload]: DevConsoleManager="*res://addons/DevConsoleKit/DevConsoleManager.cs"
- instance addons/DevConsoleKit/DevConsole.tscn under a CanvasLayer in the main scene

## InputRemapKit

Rebind keyboard and mouse actions at runtime, with conflict checks and saved overrides.

Use instead of writing:
- a key-rebinding screen backend over InputMap
- saving and loading custom key bindings
- key conflict detection
- tracking keyboard vs gamepad as the last-used device

```
git submodule add git@repo.billbert.co:artifactory/InputRemapKit.git addons/InputRemapKit
```

Setup:
- project.godot [autoload]: InputRemapManager="*res://addons/InputRemapKit/InputRemapManager.cs"

## RunSaveKit

Versioned save file with atomic writes, optional encryption, migration and safe recovery.

Use instead of writing:
- saving a run to a file safely
- save file versioning and migration
- recovering from a corrupt or missing save
- encrypting a save file

```
git submodule add git@repo.billbert.co:artifactory/RunSaveKit.git addons/RunSaveKit
```

## SettingsKit

User settings autoload: audio, video, graphics, accessibility and language, saved to disk.

Use instead of writing:
- an options menu backend for volume, resolution and graphics
- saving and loading a settings config file
- creating Music/SFX/Ambience audio buses
- graphics quality presets
- mouse sensitivity and FOV settings

```
git submodule add git@repo.billbert.co:artifactory/SettingsKit.git addons/SettingsKit
```

Setup:
- project.godot [autoload]: SettingsManager="*res://addons/SettingsKit/SettingsManager.cs"

## TransitionKit

Full-screen scene transitions: fade, kaleidoscope shader, messages and threaded scene loading.

Use instead of writing:
- a fade-to-black scene change overlay
- threaded scene loading with a fade
- a message shown on a black transition screen

```
git submodule add git@repo.billbert.co:artifactory/TransitionKit.git addons/TransitionKit
```

Setup:
- project.godot [autoload]: TransitionManager="*res://addons/TransitionKit/TransitionManager.tscn"
