# Baseline: godot-capsule-room

Ornith, full 34-kit MODULES.md, 5 trials, 2-hour limit: 0/5 passed.

| Trial | build | runs | player | installed | live | unmodified | no_dup | Ended |
|---|---|---|---|---|---|---|---|---|
| 1 | pass | fail | fail | pass | fail | fail | fail | timeout |
| 2 | fail | fail | fail | fail | fail | fail | fail | model stopped |
| 3 | pass | fail | fail | pass | fail | fail | fail | timeout |
| 4 | fail | fail | fail | fail | fail | fail | fail | timeout |
| 5 | pass | fail | fail | pass | fail | fail | fail | model stopped |



## Hand judgment

- **Trial 1:** 34 submodules. Autoloads cover InputRemap, Settings, Cursor, DevConsole; Crash via a Bootstrap script; RunSaveKit used in game code. DebugLog and Transition not wired. Kits edited (RegistryKit, PoolKit). Player.tscn failed to load, so no player.
- **Trial 2:** 33 kits copied. Only autoload is NetworkClock. One game file, Main.cs. No player. Stopped itself.
- **Trial 3:** 33 submodules, unedited. Six foundation autoloads; Crash and RunSave only referenced. Room.tscn parse error, game never started; CapsulePlayer.cs never ran.
- **Trial 4:** 33 kits copied. Six foundation autoloads, Crash via script, no RunSave. Player.cs does not compile (invented AbilityKit/StatModifier members).
- **Trial 5:** 33 submodules plus a locally made ScreenshotKit, kits unedited. Seven foundation autoloads, Crash in Main.cs, RunSaveKit in Player.cs. project.godot fails to load. Stopped itself.

## Causes

- **a. Scope blowup: confirmed.** Trials 1, 3, 5 installed 33-34 submodules; 2 and 4 copied 33. All put non-foundation kits (NetClock, Chat, Perf, ConnQuality, Pool) on autoload. Caveat: rounds 1+ list only the 8 foundation kits, so baseline vs round 1 confounds index scope with the standard.
- **b. Install friction: confirmed.** Trials 1, 2, 3, 5 spent their first 10-25 tool calls on ssh, proxy, https, API and .netrc probing before using the local mirror. Trials 2 and 4 both copied files.
- **c. Hand-written scenes: partly confirmed.** Trial 1 logged MeshMaterial and RectangleTexture2D errors; trial 3 a .tscn parse error; trial 5 a broken project.godot. Failed web lookups of Godot source: trials 1 (16 web calls) and 2 (8).
- **d. BuildIdKit: confirmed.** Trial 2's build died on missing GitBuildStamp; trial 1 hit it and patched the csproj.
- **e. Checker false positive: confirmed.** Every trial hits addons/ChatKit and addons/PerfKit. Trials 3 and 5 also hit a `user://` save path in the player script, probably an argument to RunSaveKit. Skip addons/ in the scan.

## Historical project (InNetwork)

Kits are copied into res/addons and a few game files (Main.cs, NetworkPlayer.cs, TemplateCommands.cs) reference them, but all twelve autoloads are the game's own services (SaveService, SessionNet and others). So kits are present yet largely not the foundation, a similar pattern; Not checked: whether SaveService duplicates RunSaveKit.
