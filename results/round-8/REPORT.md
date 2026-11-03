# Round 8 review

`godot-capsule-room` with the product CLI (`--product`, arc off): **2 of 5** passed, by the checker and by screenshot. Round 7 also scored 2 of 5. The bar is not met.

This round is the first that used the Artifactory CLI instead of the pre-CLI harness:

- each trial project had `artifactory.yaml` (a `dir:` provider on the local mirrors), the product MODULES.md and the AGENTS.md block from `artifactory index --arc off`;
- `artifactory` was on PATH in the sandbox, and the index lists each kit as `artifactory install <Name>`.

The checker, the consumer notes (MoveCheck included), the prompt and the time limit (2 h) are the same as in round 7. The harness resumes after dropped model connections; none dropped this round.

## Results

Screenshots: `results/round-8/trial-N.png`, 1600×900, main scene after 2 s, for the trials that build.

| Trial | Result | Screenshot | Cause |
|---|---|---|---|
| t1 | pass | capsule from behind, floor and three walls | Pass. |
| t2 | timeout (2 h) | none (no build) | `MoveCheck.cs(61,140)`: the same dropped `)` on the `RoomMissing` line as round 7's t1 and t5. The kits were installed but never confirmed live. |
| t3 | pass | capsule from a high angle, close to the camera, inside walls | Pass. |
| t4 | timeout (2 h) | capsule at the bottom edge of the frame, inside walls | Every check passed except `runs`, which saw one engine error (`Condition "!is_inside_tree()" is true`, a transform read before the node entered the tree). It ran out of time while still working. |
| t5 | timeout (2 h) | capsule in a room, with the dev console open over the top of the screen | `player_moves` false (W moved it 0, D moved it 5), `room_present` false (no wall on +x and +z). The console is open on the first frame. A console that holds keyboard focus would explain W doing nothing; this is not confirmed. |

All five trials installed all 8 kits, left them unmodified and had no duplication. Four of five installed them with `artifactory install`. t3 used one `git submodule add` command line instead, which gives the same result.

## Findings

1. **The CLI changed how kits get installed, not the pass rate.** The model found `artifactory` on its own and used it, and installation was never the problem: every trial got all 8 kits in cleanly, as in round 7. What fails is the game code and the self-check around it.
2. **MoveCheck copying is still the top failure.** For the third time in two rounds, a build broke on a dropped parenthesis in the notes' dense `RoomMissing` line. Artifactory-ksz (split the line, compile the notes' MoveCheck in a test) is now the clearest fix available. It waits until after round 9 so rounds 7–9 stay comparable.
3. **Time is tight.** Three of five trials hit 2 h. t4 was one runtime error short of passing.

## Next

Round 9 runs the same setup with arc enforcing the installed modules (`--product --arc`).
