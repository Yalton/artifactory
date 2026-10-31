### Before finishing

Build, then run the game headless and check the output:

```
dotnet build
godot --headless --path . --quit-after 300
```

Each installed kit's marker must appear and no `ERROR:` line may be printed.

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

Never write or edit `.uid` files or `uid=` attributes. Omit them. Godot generates them on import. `.uid` files under `addons/` belong to the kit.
