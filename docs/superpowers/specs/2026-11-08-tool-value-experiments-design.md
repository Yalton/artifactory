# Tool-value experiment: the same project four ways

Status: design, from the user's direction on Nov 8. Bead: Artifactory-1zo. This replaces the earlier two-experiment draft of the same day.

## Why

Every trial so far handed the model a project whose kits were already chosen. It showed that a weak model can wire in kits it is given. It never showed whether the tools themselves change what gets built:
- the `artifactory` CLI and its MCP tools, which let an agent find and install kits;
- arc, which declares an architecture and is meant to keep agents inside it across sessions.

The user's words: "build essentially the same project" several times, once with nothing, once with Artifactory, once with arc and once with both, then "evaluate the quality of each project". Then fix whatever the tools did badly.

## The rule that matters most: no intervention

Once the real run starts, nobody touches it. No fixes, no reruns, no tuning, whatever breaks. A trial that times out, stalls or loses its model connection is recorded as it ended. The harness's own automatic behaviour (resuming a dropped model connection up to 3 times, the bead loop's stall handling) is part of the setup and stays on.

Before the real run, one smoke trial per condition checks that the setup works. Smoke trials are thrown away, and harness bugs they show may be fixed. After the smoke run, the code, kits and fixtures are frozen at one commit, recorded in every round.json.

Findings about the tools go into beads and get fixed after the experiment, not during it.

## The project

A Go link service, built from a frozen 4-bead roadmap, one fresh opencode session per bead, with the existing bead loop. The same 4 beads in every condition.

1. **Service skeleton.** Configuration from environment variables (`LINKS_ADDR`, default `:8080`; `LINKS_DATA`, default `links.json`; `LINKS_ADMIN_TOKEN`, no default). An HTTP server on `LINKS_ADDR` with `GET /healthz` returning 200, shutting down cleanly on SIGTERM. The binary is built from `./cmd/links`.
2. **Short links.** `POST /links` with `{"url": …}` returns 201 and `{"code": …}`, with a random code. `GET /<code>` redirects (302) to the URL. An unknown code returns 404. Links are stored in the data file and survive a restart.
3. **Expiry and stats.** `POST /links` accepts an optional `ttl_s`; an expired link returns 410. Every redirect increments a click count. `GET /links/<code>/stats` returns `{"url", "clicks", "expires_at"}`.
4. **Admin delete and tests.** `DELETE /links/<code>` with `Authorization: Bearer <LINKS_ADMIN_TOKEN>` deletes a link (204), a wrong or missing token returns 401, and a deleted code then returns 404. Tests in the repo cover beads 1 to 4 and pass with `go test ./...`.

Each bead's text states its contract and how to check it. It never names a module, library, tool or package layout, so the bead text is identical in every condition.

**The session prompt is the same in every condition (my call):** the bead loop's existing prompt, "Work bead {id}. Run bd show {id} first, do only what it says, run its check, then bd close {id}." Anything that pushes an agent toward kits or toward the layout has to come from the tool itself: the `AGENTS.md` block and skill that `artifactory init` writes, and arc's sections and hook. opencode reads `AGENTS.md` by itself. Earlier trials showed a weak model often ignores kits unless the prompt names them. If that happens here, it is a finding about the tools ("their instructions don't get the kits used") and gets fixed in the tools afterwards.

Why this shape:
- The four Go kits fit naturally: config (bead 1), httpserver (bead 1), shortid (bead 2), kvstore (beads 2 to 4).
- Beads 3 and 4 change code that earlier sessions wrote: the store, the handlers and the config. That is where drift shows up: a second config loader, file I/O in handlers, storage logic in two places, or an edited kit.

**Kit preparation, before the experiment (my call):** kvstore today has only `Open`, `Get`, `PutIfAbsent` and `Close`. Beads 3 and 4 need an update and a delete, so without them every condition would have to work around the kit. kvstore gains `Put` and `Delete` as version 0.2.0 before the smoke run.

## Conditions

All four start from the same blank Go fixture, with `go.mod`, beads and the frozen roadmap imported. All four run on local Ornith, in the same sandbox, with the same opencode config, except where the table says otherwise. The kits are served offline through the file GOPROXY in every condition, so nothing but discovery separates them.

| | `control` | `artifactory` | `arc` | `both` |
|---|---|---|---|---|
| beads and the roadmap | yes | yes | yes | yes |
| `artifactory` on PATH, `artifactory.yaml` with no kits in scope, the `AGENTS.md` block, `MODULES.md` (notes only), the skill | no | yes | no | yes |
| `artifactory mcp` in opencode config | no | yes | no | yes |
| `arc` on PATH, registry, opencode plugin (hook), arc's sections in `AGENTS.md` and `ARCHITECTURE.md` | no | no | yes | yes |

The `artifactory` setup is what `docs/getting-started.md` produces: `mkdir .opencode`, then `artifactory init --ecosystem go`. The catalog holds the 4 Go kits and the 3 Python kits.

**The arc registry (my call):** the arc conditions start with a registry that declares the intended layout, the way a user would after `arc init` and describing their architecture:
- `cmd/links` wires;
- `internal/httpapi` handles requests;
- `internal/links` holds the rules (codes, expiry, clicks);
- `internal/store` is the only package that persists.

With the registry come the boundary rules arc can express for packages inside the repo, for example that `internal/httpapi` may not import `internal/store` directly. Each declared package starts as a one-line `doc.go`, because arc requires every registry path to match a file; without them, `arc module set` refuses every kit installed in bead 1. With them, `artifactory` in `both` registers installed kits with arc, as it does today. Those `doc.go` files are part of the arc treatment (my call, after the builder check).

"arc" in this experiment therefore means the declared layout plus arc's enforcement, because that is what arc is: a registry someone writes, and checks that hold agents to it. arc runs as it is today, with no changes for this experiment. The control and `artifactory` conditions have no stated architecture, which is the point.

## Trials

3 per condition, 12 in total, with a 2-hour limit per trial. Ornith built the url shortener in 30 to 45 minutes, so 4 beads should take about 1 to 1.5 hours: roughly 15 hours for the whole run, 24 at worst. Conditions are interleaved (control t1, artifactory t1, arc t1, both t1, control t2, …), so a slow model server or a bad hour hits every condition alike.

## Evaluation

Everything is scored after the run, from each finished project, the same way for every condition.

**Checks (automatic):**
- **Works:** builds; `go test ./...` passes; a scripted check of every bead's contract (health, create, redirect, 404, restart survival, ttl and 410, click counts and stats, delete with good and bad tokens).
- **Kits:** for each of the 4 Go kits, required in `go.mod` and live in the main package (`go list -deps ./cmd/links`); kits unmodified (no `replace`, vendor or `go.work`).
- **Hand-written duplicates:** the duplication patterns from `go-url-shortener`, counted for kits that are not live.
- **Consistency** (layout-agnostic, so the control is scored fairly). A call to a kit counts as the one place: `config.Load` for environment reads, `kvstore.Open` for the data file (my call: the kits do the reading and writing inside themselves).
  - Environment variables are read in at most one package of the repo, counting direct `os.Getenv` and `os.LookupEnv` calls and `config.Load` calls together.
  - The data file is opened or written in at most one package, counting direct file calls and `kvstore.Open` calls together.
  - HTTP handlers do no file I/O (`os.Open`, `os.ReadFile`, `os.WriteFile`, `os.Create` and similar in files that register handlers);
  - no function defined twice with the same body.
- **arc gate:** run on a copy of each project with the registry above, with no module entries. Only boundary findings count; render, empty-glob, placement, clone and module findings are dropped. Placement findings would fault the control for not knowing a layout it was never given, kit edits are caught by the kit check above, and duplicates by the consistency check. This measures adherence to the declared layout. It is reported for every condition but read as arc's effect only between `arc` and `both`, and as context for the others. It gates nothing.
- **Beads:** closed, blocked, sessions, stalls (the existing roadmap outcome).
- **Tool use**, from transcripts: `artifactory` commands, MCP calls and `arc` commands by name, and arc hook denials.

**Quality review (blind, with known leaks):** after the run, each project is copied without anything that reveals its condition: `.arch`, `artifactory.yaml`, `MODULES.md`, `AGENTS.md`, `ARCHITECTURE.md`, `.beads`, `.opencode` and transcripts. The copies get shuffled labels. A fresh reviewer subagent of the controlling session scores each one 1 to 5 on structure, consistency across the four features, duplication, and test quality, with one paragraph of reasons. The labels are revealed only after all 12 are scored. The blinding leaks: kit imports in `go.mod` give away Artifactory, and the arc layout gives away arc. The report says so; the review is a second opinion beside the automatic checks, not the headline.

**Kits visible to the control:** the file GOPROXY is in every sandbox, so an agent could stumble on the kits through `go env` or the proxy folder. Transcripts are searched for that, and any such trial is flagged in the report, not removed.

**Report:** a table per condition (works, kits live, consistency findings, gate findings, beads closed, quality scores), the per-trial detail, and what each tool did or failed to do. With 3 trials per condition, the report states differences and does not claim significance. A tool counts as helping only if its conditions beat the ones without it on the measure it targets: kits live for Artifactory (`artifactory` and `both` against `control` and `arc`); the layout-agnostic consistency findings and the blind review for arc (`arc` and `both` against `control` and `artifactory`).

**After the report:** every problem the tools showed becomes a bead in this repo or in arc, and gets fixed then.

## Non-goals

- No Godot, no Python project. Go has the cheapest and most reliable checker.
- No hosted models. A later Claude run of the same four conditions needs the user's OK and a cost estimate first.
- No tool changes for the experiment beyond kvstore 0.2.0 and the harness work below.

## Harness changes needed

From a read of `tools/artifactory` on Nov 8:
- **Conditions.** A `--condition control|artifactory|arc|both` for roadmap rounds on Go, replacing the Godot-only rules that roadmap mode needs `--product --arc` and that `--product` rejects Go.
- **Artifactory setup for Go:** provider `dir:` over a folder holding `samples/go/*` and `samples/python/*`, read-only; `artifactory.yaml` with no modules; `.opencode/` created before init; `artifactory mcp` added to the opencode config. Today a harness test forbids any `mcp` key; it changes to allow exactly this one.
- **arc setup without Artifactory:** today arc setup lives inside the product setup.
- **The roadmap:** imported from `tests/acceptance/go-link-service/roadmaps/frontier.jsonl` (the name the harness reads), in every condition.
- **Go checker:**
  - the main package path comes from test.yaml;
  - kit checks are reported, not gating;
  - the link-service contract checks;
  - the consistency checks;
  - the arc gate with a supplied registry, keeping boundary findings only.
- **Round layout:** round directories and round.json name the condition. A `--interleave` runner runs the 12 trials in the order above.
- **The tool-use counter and the blind-copy export.**

## Left to the builder

- Exact flag and test.yaml spellings.
- The arc registry file, within the layout above.
- The consistency checks' patterns, within the rules above.
- The reviewer prompt and rubric wording, within the four criteria above.
