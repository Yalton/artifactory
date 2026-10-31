# Godot C# profile (ecosystem `godot-csharp`)

Applies Stitchability Standard Draft 0.1.

| Rule | In this profile |
|---|---|
| 1 Descriptor | `module.yaml` at the module root. `name` is `<Name>Kit` and equals the folder name. |
| 2 Docs travel | README and `module.yaml` live in the kit folder, which the submodule brings. |
| 3 Unmodified | Each kit submodule is at a published commit with a clean working tree. |
| 4 Live | Runtime check, below. |
| 5 Example | A short, complete "Wiring" snippet in the kit README, showing the kit in a minimal host. |
| 6 Setup | Prefer zero steps. Any required step must print the liveness marker. |
| 7 Index | Generated from `module.yaml` files. |
| 8 Preamble | Prepended to the index. |

## Install

```
git submodule add -b stitchability git@repo.billbert.co:yalt/<Name>Kit.git addons/<Name>Kit
```

Copy-the-folder and edit-in-place instructions are not supported.

## Liveness

"Live" means the running game initialised or registered the kit at startup through its real entry path: an autoload, or a call reachable from one or from the main scene. It does not mean every feature fired. Event-driven kits count as live once wired.

Each kit prints exactly `[<Name>Kit] live`, once per process, with plain `GD.Print` (not a `Log.cs` shim), from its initialisation or its required setup step. A skipped setup step shows up as a missing marker.

The checker runs the game headless for a fixed time and greps for each marker.

## Descriptor `liveness` value

The marker line itself, exactly `[<Name>Kit] live`. No other words.

## Before finishing

Build, then run the game headless and check the output:

```
dotnet build
godot --headless --path . --quit-after 300
```

Each installed kit's marker must appear and no `ERROR:` line may be printed.

## Host project files

Copy these exactly. They were written by Godot 4.7 and load with no errors. Hand-invented variants of these formats fail.

`project.godot`: comments start with `;`, never `#`. The main scene key is `run/main_scene` under `[application]`, not under `config/`.

```ini
[application]

config/name="MyGame"
run/main_scene="res://Main.tscn"
```

Input actions go under `[input]` (not `[input_map]`). One key event, bound by physical key (`physical_keycode` 87 is W):

```ini
[input]

move_forward={
"deadzone": 0.2,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":16,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":0,"physical_keycode":87,"key_label":0,"unicode":0,"location":0,"echo":false,"script":null)
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

Never write or edit `.uid` files or `uid=` attributes. Omit them. Godot generates them on import. `.uid` files under `addons/` belong to the kit.
