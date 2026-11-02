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
git submodule add git@repo.billbert.co:artifactory/<Name>Kit.git addons/<Name>Kit
```

Copy-the-folder and edit-in-place instructions are not supported.

## Liveness

"Live" means the running game initialised or registered the kit at startup through its real entry path: an autoload, or a call reachable from one or from the main scene. It does not mean every feature fired. Event-driven kits count as live once wired.

Each kit prints exactly `[<Name>Kit] live`, once per process, with plain `GD.Print` (not a `Log.cs` shim), from its initialisation or its required setup step. A skipped setup step shows up as a missing marker.

The checker runs the game headless for a fixed time and greps for each marker.

## Descriptor `liveness` value

The marker line itself, exactly `[<Name>Kit] live`. No other words.

## Consumer notes

`standard/consumer/godot-csharp.md` holds the consumer-facing project notes (verification commands, host project file formats). Every index for this ecosystem includes it after the preamble.
