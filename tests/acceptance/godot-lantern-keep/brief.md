Build Lantern Keep, a small top-down Godot 4.7 C# game, in this project. It is 3D: a camera looks down on capsule-style characters.

What the game has:
- A title screen with New Game, Continue, Settings and Quit.
- Three rooms (courtyard, hall, tower) joined by doors. Walking through a door changes room with a fade.
- A player that moves with WASD (rebindable).
- An NPC keeper in the hall. Walking up to the keeper and pressing interact opens a dialogue box that types out three lines, one per press.
- A pause menu (Escape) with Resume, Settings, Save and Quit to Title.
- Settings: master volume, fullscreen, vsync, and key rebinding.
- Save and Continue: the current room and the player position persist across runs.
- A custom cursor on menus, hidden during play.
- A developer console (backtick) with at least a `room <name>` command.
- Debug logging for room changes, and crash reports written on unhandled exceptions.

Use every module listed in `MODULES.md` for the job it does, instead of writing that functionality yourself.

Contracts:
- The player node is in the group `player`; the keeper NPC is in the group `keeper`.
- The main scene (`run/main_scene` in `project.godot`) is the title screen. The room scenes are `res://rooms/courtyard.tscn`, `res://rooms/hall.tscn` and `res://rooms/tower.tscn`, and each has the player.
- The dialogue box is a node in the group `dialogue` that becomes visible after interact is pressed near the keeper.
- An input action `interact` exists.
- The project builds with `dotnet build`.
