# Round 5 review

`godot-capsule-room`: 1 of 5 passed. The bar is 4 of 5, so it was not met. Go was not re-run, because nothing the Go trials or the Go checker read had changed since round 4, where Go passed 5 of 5.

This round added the `player_visible` check. It requires a current `Camera3D` that has the player inside its frustum, with no collider between the camera and the player, both before and after the player moves. The consumer MoveCheck reports the same thing as `camera_sees_player`.

## Results

| Trial | Checks failed | Hit 2 h limit | Cause (confirmed on a scratch copy) |
|---|---|---|---|
| t1 | none | no | Pass. The FollowCamera sees the capsule, and the screenshot shows it. |
| t2 | player_visible | yes | Model bug. The east and west walls reuse the north wall's box size without rotating it, so a wall slab runs through the middle of the room. A debug ray from the camera hits `Wall_E` at (0.5, 3.9, 0.5), so the player really is hidden. The model ran its self-check about 50 times and never fixed it. |
| t3 | player_moves, player_visible | yes | The player does not move (w=0, d=0), which is a model bug. The camera result is partly a **checker artifact**: a headless Godot viewport is 64×64, so the frustum test uses a 1:1 aspect ratio. Its camera at (6, 3, 8) looking down -Z leaves the player just outside a square frustum, but inside a 16:9 window. |
| t4 | none | yes | Every check passes, but the session was still working at 2 h. It had written its own variant of MoveCheck rather than the given one. |
| t5 | none | yes | Every check passes, but its first `MOVECHECK ok=true` came at 115 min. **The screenshot shows no capsule.** Its player builds a custom mesh (`_SurfaceGetPrimitiveType` override), and the frustum test passes on the node position even when nothing is drawn there. |

## Findings

1. **The camera requirement roughly doubled the time spent.** In round 4 every trial finished in 23–94 min. In round 5, four of five ran out the 2 h limit, and two of those had passing games when time ran out. Ornith can place a camera, but debugging a camera it cannot see is slow for it.
2. **Visibility checked from the frustum is necessary but not sufficient.** The check catches a missing camera, a camera facing away, and a wall in between. It misses a player with no visible mesh (t5).
3. **The headless 64×64 viewport skews the frustum test** for wide, off-centre cameras (t3). The probe and MoveCheck should resize the viewport to 16:9 before testing, or the check should run under a private display.

## Not changed

Round 5 is the last round under the 5-round cap, so these go to beads instead of a round 6.
