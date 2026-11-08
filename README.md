# Artifactory

Artifactory lets coding agents reuse code instead of rewriting it. It has three parts:
- a library of small modules, called kits;
- a written standard that makes those kits easy for a weak model to find, install, wire in and prove in use;
- a CLI that puts the right kits and instructions in front of the agent.

It was built and tested with a local model: Ornith 1.5 (35B) in opencode.

## The pieces

| Piece | Where | What it does |
|---|---|---|
| Stitchability standard | `standard/` | Eight rules every kit follows (`standard/STANDARD.md`), a profile per ecosystem (`standard/profiles/`), and the notes an agent reads before it codes (`standard/preamble.md`, `standard/consumer/`). |
| Kit library | the `artifactory` org on repo.billbert.co | One repo per kit, tagged `v<version>`. Each kit carries a `module.yaml` descriptor, a README with a Wiring section, an example and a liveness marker it prints when in use. |
| `artifactory` CLI | `cmd/artifactory`, `internal/` | Searches the library, installs kits with their own install line, and writes `artifactory.yaml`, `MODULES.md` and a block in `AGENTS.md` for the agent. Also validates and publishes kits, and runs as an MCP server. |
| arc (optional) | [github.com/Yalton/arc](https://github.com/Yalton/arc) | An architecture registry with agent hooks. When present, Artifactory registers each installed kit with it; arc then blocks edits inside kit files and checks wiring at commit time. |
| Test harness | `tools/`, `tests/acceptance/` | Runs sandboxed trials of the local model against acceptance tests and checks the result. Only needed to develop the standard. |

Ecosystems: `go`, `python` and `godot-csharp`. The library holds 8 Godot kits (settings, saves, transitions, console, crash reports and so on), 4 Go kits and 3 Python kits. List them with `artifactory catalog --provider forgejo:repo.billbert.co/artifactory`, or plain `artifactory catalog` inside a project.

## Getting started

See **[docs/getting-started.md](docs/getting-started.md)**: install the tools, set up a project, add kits, and point an agent at them.

The short version, for a Go project. It needs a Forgejo token (`FORGEJO_TOKEN` or a `tea` login) and an SSH key for the org:

```
go install ./cmd/artifactory                     # from this checkout
go install github.com/Yalton/arc/cmd/arc@main    # optional; v0.1.0 lacks 'arc module'
go env -w GOPRIVATE=repo.billbert.co
git config --global url."ssh://git@repo.billbert.co/".insteadOf "https://repo.billbert.co/"

cd my-project && git init && go mod init example.com/my-project
mkdir .opencode                                  # the agent folder, so init copies the skill
arc init                                         # optional, before artifactory init
artifactory init --ecosystem go
artifactory search --ecosystem go http server
artifactory install httpserver
```

Then tell the agent to read `MODULES.md` and use every module listed there.

## Commands

| Command | Does |
|---|---|
| `artifactory catalog [--ecosystem E]` | List every kit in the library. |
| `artifactory search WORDS... [--ecosystem E]` | Rank kits against a need. |
| `artifactory show NAME` | Print a kit's descriptor and README. |
| `artifactory init --ecosystem E` | Set up a project: `artifactory.yaml`, `MODULES.md`, the `AGENTS.md` block, the agent skill. |
| `artifactory install NAME...` | Run each kit's install line, pin its version and re-index. |
| `artifactory add NAME...` | Put a kit in scope without installing it. |
| `artifactory index` | Regenerate `MODULES.md` and the `AGENTS.md` block, and sync arc. |
| `artifactory validate DIR` | Check a kit against the standard. |
| `artifactory publish [DIR]` | Validate, test, push and tag a kit. |
| `artifactory mcp` | Serve `search`, `show`, `install` and `index` as MCP tools over stdio. |

Every command takes `--json`. Exit 0 is ok, 1 means a check found problems, 2 is a usage or environment error.

## Results

The first three tests run 5 trials of the local model per round, with a bar of 4 of 5. The roadmap experiment compared three ways of writing a 16-bead plan, with 3 trials per condition in round 10 and 1 in round 11.

| Test | Result | Report |
|---|---|---|
| `go-url-shortener` | 5/5 from round 3 | `docs/specs/2026-11-01-stitchability-standard-results.md` |
| `godot-capsule-room` | not met: 5/5 by the checker in rounds 4 and 6, but screenshots showed missing cameras or rooms; 2/5 in rounds 7–9 with stricter checks | same |
| `python-url-shortener` | 5/5 in round 5 | `results/python-round-5/REPORT.md` |
| `godot-lantern-keep` (16-bead roadmap) | 0/9 and 0/3; stopped by choice after round 11 | `results/roadmap/REPORT.md`, `results/roadmap/round-11/REPORT.md` |

## Developing

- Go: `go test ./...`
- Harness and checkers: `cd tools && uv run pytest -q`
- A round: `uv run --project tools artifactory round tests/acceptance/<test> --round N --trials 5`. It needs the local model server and the mirrors from `artifactory mirror`.

Work is tracked in beads (`bd ready`).
