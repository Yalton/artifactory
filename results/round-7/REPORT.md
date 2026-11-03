# Round 7 review

`godot-capsule-room`: **2 of 5** passed, by the checker and by screenshot. The bar is not met. Go was not re-run.

This round used the checker from a7bf3a9:

- **Occlusion:** a drawn wall now blocks sight even without a physics body.
- **New `room_present` check:** a floor below the player and a wall on each side.
- **MoveCheck:** the self-check in the consumer notes gained the matching `RoomMissing` and occlusion code.

The harness also resumed the agent after a dropped model connection (70dafdf). This was the pre-CLI harness with arc off: the model read MODULES.md and installed the kits as submodules by hand, as in rounds 1–6. Two earlier attempts at round 7 were aborted after model-server connection drops and are kept as `round-7-aborted` and `round-7-aborted-2`. Neither counts.

## Results

Screenshots: `results/round-7/trial-N.png`, 1600×900, main scene after 2 s, for the trials that build.

| Trial | Result | Resumes | Screenshot | Cause |
|---|---|---|---|---|
| t1 | timeout (2 h) | 0 | none (no build) | `MoveCheck.cs` copied from the notes with one `)` missing on the `RoomMissing` line (CS1026). The model ran `dotnet build` 21 times and never found it. |
| t2 | pass | 0 | capsule seen from above, inside four walls | Pass. |
| t3 | pass | 1 | capsule from behind, floor and walls | Pass, after one resumed connection drop. |
| t4 | timeout (2 h) | 1 | none (no build) | Its own `MoveCheck.cs` change used `Notification` as a value (CS0119). The kits never got installed. |
| t5 | timeout (2 h) | 2 | none (no build) | The same missing `)` as t1, at `MoveCheck.cs(76,80)`. |

Every trial that finished installed all 8 kits, left them unmodified, printed the liveness markers and had no duplication. No trial failed on infrastructure.

## Findings

1. **Both passes are real.** For the first time since round 4, the checker and the screenshots agree. The room check and the drawn-wall occlusion closed the two gaps round 6 found (t3 without a room, t2 hidden behind a mesh wall).
2. **MoveCheck has become the failure.** In all three failures the build broke in `MoveCheck.cs`, not in game code.
   - The notes' version is correct. In t1 and t5 the model dropped one closing parenthesis while copying the dense one-line LINQ expression in `RoomMissing`, then spent the rest of its two hours on other edits.
   - The self-check grew with each round. It is now long enough that copying it is itself a risk for the local model.
3. **Connection drops are survivable.** Three resumes across t3–t5 and none lost a trial on their own. t3 passed after one.

## Next

Filed as beads, not a round 8 change:
- split MoveCheck's dense lines in `standard/consumer/godot-csharp.md` so they copy safely;
- add a test that compiles the notes' MoveCheck.

Round 8 runs the product CLI (`--product`) and round 9 adds arc (`--product --arc`). Both use this checker.
