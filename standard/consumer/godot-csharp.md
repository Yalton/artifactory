### Before finishing

Build, then run the game headless and check the output:

```
dotnet build
godot --headless --path . --quit-after 300
```

Each installed kit's marker must appear and no `ERROR:` line may be printed.

Also print a line from each of your own scripts' `_Ready` (for example `GD.Print("[Player] ready")`) and confirm it appears. Kit markers do not prove your scripts are attached.

Then check movement and the camera. Copy this to `MoveCheck.cs` in the project root. It does nothing unless run with `--move-check`:

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
    private bool _seen;

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
            _a = _p?.GlobalPosition ?? default; _seen = Seen(); Press(Key.W, true); _stage = 1;
        }
        else if (_stage == 1 && t >= 2) { Press(Key.W, false); _b = _p?.GlobalPosition ?? default; Press(Key.D, true); _stage = 2; }
        else if (_stage == 2 && t >= 3)
        {
            Press(Key.D, false); _c = _p?.GlobalPosition ?? default; _stage = 3;
            Vector3 w = Flat(_b - _a), d = Flat(_c - _b);
            Vector3 dw = w.Normalized(), dd = d.Normalized();
            bool ok = _p != null && w.Length() is >= 0.5f and <= 20f && d.Length() is >= 0.5f and <= 20f && dw.Z < -0.7f && dd.X > 0.7f;
            bool seen = _seen && Seen();
            if (_why != "") GD.PrintErr("MOVECHECK FAIL: " + _why);
            GD.Print($"MOVECHECK ok={(ok && seen).ToString().ToLower()} camera_sees_player={seen.ToString().ToLower()} w={F(w.Length())} d={F(d.Length())} dir_w={dw} dir_d={dd}");
            GetTree().Quit(ok && seen ? 0 : 1);
        }
    }

    private bool Seen()
    {
        Camera3D cam = GetViewport().GetCamera3D();
        if (_p == null || cam == null || !cam.IsPositionInFrustum(_p.GlobalPosition)) return false;
        var ray = PhysicsRayQueryParameters3D.Create(cam.GlobalPosition, _p.GlobalPosition);
        if (_p is CollisionObject3D body) ray.Exclude = new Godot.Collections.Array<Rid> { body.GetRid() };
        return GetViewport().World3D.DirectSpaceState.IntersectRay(ray).Count == 0; // nothing solid in between
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

It passes only if it prints `MOVECHECK ok=true` and no `ERROR:` line. No `MOVECHECK` line within 30 s is a failure: check the autoload line and `dotnet build`. It fails if the node in group `player` is not exactly one Node3D, or W and D do not move it about 0.5 to 20 units (W along -Z, D along +X), or no current `Camera3D` sees the player before and after it moves, with no wall, floor or ceiling collider in between (`camera_sees_player=false`). Fix the cause and re-run until it passes.

### Player pitfalls

- Key codes: W=87, A=65, S=83, D=68 (C=67 is not D).
- Override `_PhysicsProcess(double delta)`. `float delta` does not compile.
- Move in the XZ plane: `Input.GetVector(negX, posX, negY, posY)`, so `GetVector("move_left","move_right","move_forward","move_back")` gives `new Vector3(v.X, 0, v.Y)`. Set that world-space velocity directly. Never multiply a velocity by `Transform`.
- Make the `CollisionShape3D` a direct child of the body.
- Only the body joins group `player`, not its mesh.
- Set `Position`/`GlobalPosition` after `AddChild`, not before.
- Spawn the player above the floor.
- Add a `Camera3D` with `Current = true` inside the room that keeps the player in view (a ceiling or wall between them hides it), and a light. Without a camera the window is plain grey even though the game runs.
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
