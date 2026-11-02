# Round 4 review

Both tests passed 5 of 5 on the checker as it stood: `go-url-shortener` and `godot-capsule-room`.

## The pass did not mean "playable"

A screenshot of each Godot trial's main scene (1280×720, `godot-shot`, settle 2 s) shows a plain grey window in all five. None of the trials adds a `Camera3D`: a grep of every trial's own `.cs` and `.tscn` files finds no camera. Each one does add a light. The checker tested building, running without errors, movement under W and D, and kit installation and wiring. It never tested whether a person can see the game.

Re-grading trial 5 with the camera check added in round 5:

```
player_visible False PROBE player_visible=false camera=none start=out end=out
```

## Per-trial notes (Godot)

| Trial | Duration | Own files | Notes |
|---|---|---|---|
| t1 | 31 min | Main, Player, Room (+ .tscn), MoveCheck | no camera |
| t2 | 94 min | Bootstrap, GameCommands, Main, Player, MoveCheck | adds its own console commands; no camera |
| t3 | 44 min | Bootstrap, Player, MoveCheck | no camera |
| t4 | 54 min | Bootstrap, Main, Player, SaveSystem, MoveCheck | no camera |
| t5 | 23 min | Bootstrap, Main, Player, MoveCheck | no camera; speed 1 m/s; no gravity |

Movement is now correct in every trial (W along -Z, D along +X). The MoveCheck self-check from round 4 did its job.

## Change for round 5

- Checker: new `player_visible` check. It requires a current `Camera3D`, the player inside its frustum both before and after moving, and no collider on the ray from the camera to the player.
- Consumer notes: MoveCheck also prints `camera_sees_player`, and the pitfalls list gains a line about the camera and the light.
