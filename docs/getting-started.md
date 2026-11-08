# Getting started

This guide sets up a new project so a coding agent finds and uses Artifactory kits. It uses opencode with the local Ornith model, but the project files work the same for Claude Code and Codex.

Every command here was run on a fresh Go project against the real kit library, and Ornith then built a working service from it in a few minutes using both installed kits. Steps that differ for Python and Godot are noted.

## 1. Install the tools (once per machine)

You need Go 1.26 or newer, git, and an SSH key that can read the `artifactory` org on repo.billbert.co.

```
cd /path/to/Artifactory            # this repository
go install ./cmd/artifactory
go install github.com/Yalton/arc/cmd/arc@latest    # optional, see step 3
```

Both land in `$(go env GOPATH)/bin`; put that on your `PATH`.

**Library access.** The CLI lists kits through the Forgejo API. It uses `FORGEJO_TOKEN` if set, otherwise the token of your default `tea` login (`~/.config/tea/config.yml`). Check it works:

```
artifactory catalog --provider forgejo:repo.billbert.co/artifactory
```

**Installing kits** uses each kit's own install line (`go get`, `pip install … git+ssh://…`, `git submodule add git@…`), so it goes over git, not the API. Go needs two settings or `go get` fails with `could not read Username for 'https://repo.billbert.co'`:

```
go env -w GOPRIVATE=repo.billbert.co
git config --global url."ssh://git@repo.billbert.co/".insteadOf "https://repo.billbert.co/"
```

## 2. Create the project

```
mkdir my-service && cd my-service
git init
go mod init example.com/my-service      # Python: uv init; Godot: create the Godot project first
```

## 3. Add arc (optional, do it before step 4)

```
arc init
```

This writes `.arch/registry.yaml`, `ARCHITECTURE.md`, an `AGENTS.md`, a git pre-commit hook, and hooks for each agent:
- `.opencode/plugins/arc.js`;
- `.claude/settings.json`;
- `.codex/hooks.json`.

arc must be on the agent's `PATH`, or its hooks allow everything.

Do this before `artifactory init` for two reasons. `artifactory init` only copies its agent skill into agent folders that already exist (`.opencode/`, `.claude/`, `.agents/`). And with arc present, each kit you install is registered with arc, which then blocks edits inside kit files.

Without arc, create the folder for your agent first, for example `mkdir .opencode`, so the skill is copied.

## 4. Set up Artifactory

```
artifactory init --ecosystem go      # or python, godot-csharp
```

It writes:

| File | For |
|---|---|
| `artifactory.yaml` | the ecosystem, the library (`provider: forgejo:repo.billbert.co/artifactory`) and the pinned kits |
| `MODULES.md` | the index the agent reads: each kit's summary, what it replaces, install line and setup |
| `AGENTS.md` (a marked block) | the standard's rules and the ecosystem's build, run and check notes from `standard/consumer/` |
| `.opencode/skills/artifactory/SKILL.md` and `.claude/skills/…` | when to search and how to install |

Commit these files. Re-run `artifactory index` after editing `artifactory.yaml` by hand.

## 5. Add kits

Search by need, and pass the ecosystem: `search` covers the whole library, so a Go project otherwise also gets Python hits.

```
artifactory search --ecosystem go http server graceful shutdown
artifactory show httpserver
artifactory install httpserver config
```

`install` runs the kit's install line, pins the version in `artifactory.yaml`, and rewrites `MODULES.md`, the `AGENTS.md` block and arc's registry (`arc module list` shows them).

You can also leave this to the agent (step 6): the skill and the MCP tools let it search and install itself.

## 6. Point the agent at it

**opencode with Ornith.** Put this in `opencode.json` at the project root, or in `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "agentbox/ornith-1.5-q4",
  "provider": {
    "agentbox": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ornith (llama.cpp)",
      "options": { "baseURL": "http://192.168.50.174:8080/v1", "apiKey": "llama-cpp", "timeout": false },
      "models": {
        "ornith-1.5-q4": { "name": "Ornith 1.5", "tool_call": true, "reasoning": true,
                           "limit": { "context": 131072, "output": 32768 } }
      }
    }
  },
  "mcp": {
    "artifactory": { "type": "local", "command": ["artifactory", "mcp"], "enabled": true }
  }
}
```

The `mcp` entry is optional. It gives the agent `search`, `show`, `install` and `index` as tools. Without it, the agent runs the same commands in the shell.

**Claude Code and Codex** read the same `AGENTS.md` and skill. For the MCP tools in Claude Code: `claude mcp add artifactory -- artifactory mcp`.

## 7. Prompt so the kits get used

opencode reads `AGENTS.md` by itself. The trials still showed that a weak model writes things itself unless the task says otherwise, so say it in the prompt:

> Before writing code, read MODULES.md and AGENTS.md, and search for modules for anything else you need. Use every installed module instead of writing that code yourself. Build and run the project, and do the checks AGENTS.md lists.

What the trial rounds taught:
- **Name the index in the prompt.** Every passing trial was told to use the modules in `MODULES.md`.
- **The consumer notes carry the fixes.** They tell the agent:
  - not to rewrite what a kit does, even as a fallback;
  - how to build offline;
  - to stop once the checks pass.

  They are already in the `AGENTS.md` block. Keep that block current with `artifactory index`.
- **Check the result.** Python and Godot kits print `[<name>] live` once when the program starts; a missing marker means the kit is installed but not used. A Go kit counts as used when the main package depends on it: `go list -deps ./cmd/... | grep repo.billbert.co/artifactory`.

## Making a kit

A kit is a folder or repo that follows `standard/STANDARD.md` and its ecosystem's profile in `standard/profiles/`: a `module.yaml` descriptor, a README with a Wiring section, an example, tests and a liveness marker. The samples in `samples/go` and `samples/python` are complete examples.

```
artifactory validate path/to/kit
artifactory publish path/to/kit      # validates, runs its tests, pushes main and tags v<version>
```

Publishing needs write access to the org. A kit in a subfolder of a larger repo is published as its own repo. Bump `version` in `module.yaml` for each release.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `no provider: pass --provider or run artifactory init` | Run it inside a project with `artifactory.yaml`, or pass `--provider forgejo:repo.billbert.co/artifactory`. |
| `could not read Username for 'https://repo.billbert.co'` on install | Set `GOPRIVATE` and the git `insteadOf` rule from step 1. |
| No skill in `.opencode/skills` | The folder did not exist at `artifactory init`, and `init` refuses to run twice. Copy it by hand: `mkdir -p .opencode/skills/artifactory && cp /path/to/Artifactory/skill/SKILL.md .opencode/skills/artifactory/`. |
| `arc pre-commit: 'arc' not found on PATH` | Put arc on `PATH`; the gate is skipped until then. |
| New kits do not show up | The catalog is cached for 10 minutes. Pass `--refresh`. |
