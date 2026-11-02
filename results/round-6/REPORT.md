# Round 6 review

`godot-capsule-room`: the checker passed 5 of 5, so by the checker the bar is met. A screenshot audit counts **3 of 5** as a capsule visible in a room, so by eye the bar is **not** met. Go was not re-run; nothing it reads changed since round 4.

This round used the reworked `player_visible` check: a camera within 2 m of the player and parented to it counts as first person; otherwise the player needs a mesh that actually draws, framed in a 16:9 frustum, with no collider between the camera and each mesh. MoveCheck in the consumer notes mirrors it. Round 6 ran past the 5-round cap with the operator's approval.

Every trial installed all 8 kits as submodules, left them unmodified, and printed all 8 liveness markers. No trial hit the 2 h limit.

## Results

Screenshots: `results/round-6/trial-N.png`, 1600×900, main scene after 2 s.

| Trial | Minutes | Checker | Screenshot | Cause |
|---|---|---|---|---|
| t1 | 58 | pass | capsule in a room | Pass. The only trial whose walls are `StaticBody3D`, so they also stop the player. |
| t2 | 41 | pass | **no capsule**: a grey wall face fills the view | Model geometry bug. Every wall is a 22×4×22 box, so the "walls" overlap the whole room, and the follow camera sits inside them. The north wall's front face lies between camera and player. Its `CollisionShape3D` is a child of a `MeshInstance3D`, which gives no physics body, so the checker's ray passes through it. |
| t3 | 87 | pass | capsule on a grey void | **No room.** `Main.cs` builds a camera and nothing else: no floor, no walls. The checker has no room check. |
| t4 | 28 | pass | capsule from above, inside walls | Visible and in a room. Walls have no physics body, so the player can walk through them. |
| t5 | 42 | pass | blue capsule in a coloured room | Visible and in a room. Walls have no physics body. |

## Findings

1. **Time came back down.** Round 5 had four of five trials at the 2 h limit. Here all five finished in 28–87 min. The clearer reasons in MoveCheck's `camera_sees_player=<reason>` probably helped; the sample is too small to be sure.
2. **The checker's occlusion test only sees physics.** A wall drawn as a mesh with no physics body hides the player but does not block the ray (t2). Four of five trials put colliders under `MeshInstance3D`, a recurring model mistake that the consumer notes do not warn about.
3. **Nothing checks for a room.** The prompt asks for one, and t3 has none. The checker tests the player and the camera, never the scene around them.
4. **Walls do not stop the player** in t2, t4 and t5. The prompt does not say walls must be solid, but a WASD room you can walk out of is a weak reading of it.

## Not changed

The fixes are filed as beads rather than a round 7: occlusion against drawn meshes, a room check (floor plus enclosing walls), and a pitfall line about `CollisionShape3D` needing a `PhysicsBody3D` parent.
