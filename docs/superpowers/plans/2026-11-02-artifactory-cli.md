# Artifactory CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Go single-binary `artifactory` CLI that searches, installs, indexes, validates and publishes stitchable modules in any project, and that the trial harness uses in place of its Python index code.

**Architecture:** One Go module at the repository root (`repo.billbert.co/artifactory/artifactory`). `cmd/artifactory` handles argument dispatch and output, in the same shape as arc's `cmd/arc` (`run(args, stdout, stderr) int`, a `--json` flag in any position, exit codes 0/1/2). Logic lives in `internal/*` packages. A `Provider` interface hides where modules are stored. `forgejo:` talks to the Forgejo API plus git over SSH. `dir:` reads a local folder of repos and is used by tests and the harness. `standard/` becomes a Go package that embeds its own markdown.

**Tech Stack:** Go 1.26, `gopkg.in/yaml.v3`, `github.com/modelcontextprotocol/go-sdk` (Task 9 only), git CLI, Python 3 harness (uv, pytest) for Task 11.

**Spec:** `docs/superpowers/specs/2026-11-02-artifactory-cli-design.md`

## Global Constraints

- Exit codes: `0` ok, `1` the check found problems, `2` usage, configuration or environment error. Every command accepts `--json`. In `--json` mode an error is printed to stdout as `{"error": msg}`, as arc does.
- The descriptor field list and rules stay exactly as `tools/artifactory/descriptor.py` has them today (`STR_FIELDS`, `LIST_FIELDS`, ecosystems `godot-csharp` and `go`, summary one line under 100 characters, `replaces` 1–5 items each under 80 characters, godot-csharp `name` equal to the folder, godot-csharp liveness matching `^\[\w+\] live$`, `setup` may be absent).
- The CLI never edits a module's `install` line and never runs `setup` steps.
- A module's version is the git tag `v<version>`. "Latest" means the highest semver tag. Untagged repos are not modules. `publish` never moves an existing tag.
- The CLI never calls a model and never stores secrets. The Forgejo token comes from `FORGEJO_TOKEN`, or else from the `token` of the default login in `~/.config/tea/config.yml`.
- `MODULES.md` rendered by the CLI must match, byte for byte, what the Python `build_index(..., index_preamble(eco))` produces for the same descriptors (golden files, Task 4).
- Code style follows arc (`/home/yalt/Documents/Projects/Tech/AI/arc/cmd/arc/main.go`, `output.go`): table-driven tests, small packages, doc comments on exported names.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run the Go tests with `go test ./...` from the repository root. Run the Python tests with `uv run --project tools pytest tools/tests -q`.

## Review Focus

1. **A catalog repo with a broken `module.yaml` at its latest tag.** `search` and `catalog` skip that repo and report it on stderr. They do not fail outright. Covered by `TestLoadSkipsInvalidDescriptor` (Task 2).
2. **`install` with an install line that fails.** `artifactory.yaml` and `MODULES.md` stay byte-identical. Covered by `TestInstallFailureLeavesProjectUntouched` (Task 6).
3. **Publishing a version whose tag already exists.** It exits 1 before running tests or pushing anything. Covered by `TestPublishRefusesExistingTag` (Task 7).
4. **Running `index` twice, or on an `AGENTS.md` that already has user text.** The marked block is replaced in place and text outside it is kept. Covered by `TestWriteAgentsBlockIsIdempotent` (Task 4).
5. **A search that matches nothing.** Exit 0, the text says `no module matches`, and the JSON has `"hits": []`. Covered by `TestSearchNoMatch` (Task 5).

---

### Task 1: Module scaffold, descriptor and `validate`

**Files:**
- Create: `go.mod` (`module repo.billbert.co/artifactory/artifactory`, `go 1.26`)
- Create: `cmd/artifactory/main.go`, `cmd/artifactory/output.go`, `cmd/artifactory/validate.go`
- Create: `internal/descriptor/descriptor.go`, `internal/descriptor/descriptor_test.go`
- Create: `internal/validate/validate.go`, `internal/validate/validate_test.go`
- Modify: `.gitignore` (ignore `/artifactory` binary at root)

**Interfaces:**
- Produces:
  - `descriptor.Descriptor{Name, Ecosystem, Version, Summary string; Replaces []string; Install string; Setup, Entry []string; Liveness, Docs, Example, Test string}` with yaml and json tags in snake_case field names.
  - `descriptor.Ecosystems = []string{"godot-csharp", "go"}`.
  - `descriptor.Parse(data []byte, folder string) (Descriptor, []string)`. `folder` is the name the godot-csharp name rule compares against. It returns the problems, which is empty when valid.
  - `descriptor.Load(dir string) (Descriptor, error)`. Its error is `*descriptor.Error{Problems []string}`.
  - `validate.Module(dir string) (descriptor.Descriptor, []string)`. It runs the descriptor checks plus three more: the file named by `docs` exists; the file part of `example` before any `#` exists; and for ecosystem `go`, the module line in `go.mod` equals the path in an install line of the form `go get <path>`.
  - CLI `artifactory validate [DIR...]` (default `.`) prints `DIR: problem` per problem, and exits 1 if any problem is found. With `--json` it prints `{"modules":[{"dir":..,"descriptor":{..},"problems":[..]}]}`.

- [ ] **Step 1: Write the failing tests.** Port each case from `tools/tests/test_descriptor.py` into `TestParse` as a table. Add:
  - `TestValidateMissingDocs`: `docs: NOTES.md` absent gives the problem `docs: NOTES.md not found`.
  - `TestValidateExampleFragment`: `example: README.md#wiring` with a README present passes.
  - `TestValidateGoModPathMismatch`: install `go get repo.billbert.co/artifactory/kvstore` with `go.mod` `module example.com/kv` gives the problem `go.mod: module example.com/kv does not match install path repo.billbert.co/artifactory/kvstore`.
  - `TestValidateRealSamples`: every `samples/go/*` folder validates clean.
  - `TestRunValidateExitCodes` in `cmd/artifactory`: a valid dir exits 0, an invalid one exits 1, and an unknown command exits 2.
- [ ] **Step 2:** Run `go test ./...` and expect it to FAIL (packages missing).
- [ ] **Step 3:** Implement the packages and `cmd/artifactory`. `main.go` copies arc's dispatch shape (`handlers` map, `extractJSONFlag`, `usage()`).
- [ ] **Step 4:** Run `go test ./...` and expect it to PASS. Run `go run ./cmd/artifactory validate samples/go/kvstore` and expect exit 0.
- [ ] **Step 5: Commit.** `feat(cli): Go scaffold, descriptor parsing and validate`

### Task 2: Provider interface, `dir:` provider, catalog, `catalog` and `show`

**Files:**
- Create: `internal/provider/provider.go`, `internal/provider/dir.go`, `internal/provider/dir_test.go`
- Create: `internal/catalog/catalog.go`, `internal/catalog/catalog_test.go`
- Create: `cmd/artifactory/catalog.go` (`catalog` and `show` handlers)

**Interfaces:**
- Consumes: `descriptor.Parse`.
- Produces:
  - ```go
    type Provider interface {
        Spec() string                                   // e.g. "dir:/abs/path"
        List(ctx context.Context) ([]string, error)     // repo names
        Tags(ctx context.Context, repo string) ([]string, error)
        ReadFile(ctx context.Context, repo, ref, path string) ([]byte, error)
        Ensure(ctx context.Context, repo string) (pushURL string, err error) // create the repo if missing
    }
    func Open(spec string) (Provider, error) // "dir:<path>" here; "forgejo:<host>/<org>" in Task 3
    ```
  - `dir:` provider: each child of the folder is one repo, named after the child minus any `.git` suffix.
    - For a git repo, bare or not, `Tags` lists its tags and `ReadFile` uses `git show <ref>:<path>`.
    - For a plain folder with a `module.yaml`, `Tags` returns `["v"+version]` from that file and `ReadFile` reads the working tree. This lets `samples/go` act as a catalog.
    - `Ensure` creates `<name>.git` as a bare repo when it is missing and returns its absolute path.
  - `catalog.Module{descriptor.Descriptor; Repo, Tag string}` (json: the descriptor fields plus `repo` and `tag`).
  - `catalog.Latest(tags []string) (string, bool)`: the highest `vMAJOR.MINOR.PATCH` tag. Other tags are ignored.
  - `catalog.Load(ctx, p Provider) ([]catalog.Module, []string, error)`. It returns the modules sorted by name, plus warnings for repos that were skipped. A repo is skipped with no warning when it has no semver tag. A repo is skipped with a warning when it has no `module.yaml` or an invalid one at that tag. The `folder` passed to `Parse` is the repo name.
  - `catalog.Find(mods []Module, name string) (Module, bool)`.
  - `artifactory catalog [--provider SPEC] [--ecosystem E]` and `artifactory show NAME [--provider SPEC]`. `show` prints the descriptor and then the README at the tag. Provider resolution order: the `--provider` flag, then `artifactory.yaml` in the current folder (Task 4; until then, the flag only), then exit 2 `no provider: pass --provider or run artifactory init`.

- [ ] **Step 1: Write the failing tests.**
  - `TestLatest`: `[v0.1.0 v0.10.0 v0.2.0 pre-stitchability]` gives `v0.10.0, true`. `[main]` gives `"", false`.
  - `TestDirProviderGitRepo`: a temporary bare repo with commits tagged `v0.1.0` and `v0.2.0`. `ReadFile` at `v0.1.0` returns the old content.
  - `TestDirProviderPlainFolder`: `samples/go` lists `config httpserver kvstore shortid`, and the tag is `v` plus the descriptor version.
  - `TestLoadSkipsInvalidDescriptor`: one good repo and one with a bad yaml at its tag give 1 module and 1 warning naming the bad repo.
  - `TestLoadSkipsUntagged`: an untagged repo gives no module and no warning.
  - `TestEnsureCreatesBareRepo`.
  - `TestRunShowUnknownModule` exits 1 with `no module named X`.
- [ ] **Step 2:** Run `go test ./...` and expect FAIL.
- [ ] **Step 3:** Implement. Shell out to `git` with `exec.CommandContext`. Do not add a git library.
- [ ] **Step 4:** Run `go test ./...` and expect PASS. Run `go run ./cmd/artifactory catalog --provider dir:samples/go` and expect 4 lines.
- [ ] **Step 5: Commit.** `feat(cli): provider interface, dir provider and catalog`

### Task 3: Forgejo provider and catalog cache

**Files:**
- Create: `internal/provider/forgejo.go`, `internal/provider/forgejo_test.go`
- Create: `internal/provider/cache.go`, `internal/provider/cache_test.go`
- Modify: `internal/provider/provider.go` (`Open` handles `forgejo:`)

**Interfaces:**
- Consumes: `Provider`, from Task 2.
- Produces:
  - `forgejo:<host>/<org>` uses the API base `https://<host>/api/v1`.
    - `List`: `GET /orgs/{org}/repos?page=N&limit=50`, paging until an empty page.
    - `Tags`: `GET /repos/{org}/{repo}/tags`, paged.
    - `ReadFile`: `GET /repos/{org}/{repo}/raw/{path}?ref={ref}`. A 404 becomes `provider.ErrNotFound`.
    - `Ensure`: `GET /repos/{org}/{repo}`. On a 404 it calls `POST /orgs/{org}/repos` with `{"name": repo, "default_branch": "main"}`. It returns the SSH URL `git@<host>:<org>/<repo>.git`.
  - Auth header `Authorization: token <t>`, with the token from `FORGEJO_TOKEN`, or else the default login's `token` in `~/.config/tea/config.yml` (`logins[].default: true`). Reads work without a token. `Ensure` without a token returns the error `no Forgejo token: set FORGEJO_TOKEN or log in with tea`.
  - `provider.Cached(p Provider, dir string, ttl time.Duration) Provider` wraps `List`, `Tags` and `ReadFile` with JSON files under `dir`, keyed by spec and arguments. `Ensure` is never cached. The CLI wraps the `forgejo:` provider with `~/.cache/artifactory` and a TTL of 10 minutes. A global `--refresh` flag skips reads from the cache.
  - A test hook: `provider.forgejoBaseURL` can be overridden in tests, so the provider can point at `httptest.Server`.

- [ ] **Step 1: Write the failing tests** against an `httptest.Server`:
  - `TestForgejoListPages`: 60 repos across 2 pages plus an empty one gives 60 names.
  - `TestForgejoReadFileNotFound` gives `ErrNotFound`.
  - `TestForgejoEnsureCreatesMissing` asserts the POST body and the token header.
  - `TestForgejoEnsureNeedsToken`.
  - `TestTokenFromTeaConfig` uses a temporary HOME with a two-login config and picks the default one.
  - `TestCachedServesWithinTTL`: a second `List` within the TTL makes no HTTP call. After the TTL it calls again.
- [ ] **Step 2:** Run `go test ./internal/provider/...` and expect FAIL.
- [ ] **Step 3:** Implement with `net/http` only.
- [ ] **Step 4:** Run `go test ./...` and expect PASS. Then run the live smoke test `go run ./cmd/artifactory catalog --provider forgejo:repo.billbert.co/artifactory`. Before Task 10 it is expected to print no modules, because the kits are untagged. Expect exit 0 and no crash.
- [ ] **Step 5: Commit.** `feat(cli): Forgejo provider with catalog cache`

### Task 4: Embedded standard, project file, `index`, `init`, `add`

**Files:**
- Create: `standard/standard.go` (package `standard`, `//go:embed preamble.md consumer/*.md profiles/*.md`)
- Create: `internal/project/project.go`, `internal/project/project_test.go`
- Create: `internal/index/index.go`, `internal/index/index_test.go`, `internal/index/testdata/godot-csharp.golden.md`, `internal/index/testdata/go.golden.md`
- Create: `internal/testdata/kits/<Kit>/module.yaml` for the 8 kits, copied from the mirrors at `main` (folder name = kit name, so the godot-csharp name rule holds). Tasks 5 and 9 reuse these fixtures.
- Create: `cmd/artifactory/project.go` (`init`, `add` and `index` handlers)

**Interfaces:**
- Consumes: `catalog.Load` and `catalog.Find`, `provider.Open`.
- Produces:
  - `standard.Preamble() string`, `standard.Notes(eco string) (string, bool)`.
  - `project.File{Ecosystem string; Provider string; Modules []project.Entry}` and `project.Entry{Name string; Version string `yaml:",omitempty"`}`. An entry without a version is in scope but not installed.
  - `project.Load(dir) (File, error)` and `project.Save(dir, File) error`. The file is `artifactory.yaml`, and Save sorts modules by name.
  - `project.Detect(dir) (string, error)`. It returns `go` for `go.mod` and `godot-csharp` for `project.godot`. Both or neither is an error.
  - `index.Render(eco string, mods []descriptor.Descriptor) string`, which reproduces Python `build_index(mods, index_preamble(eco))` exactly.
  - `index.AgentsBlock(eco string) string`, wrapped in `<!-- artifactory:begin -->` / `<!-- artifactory:end -->`. It contains the preamble, then `See MODULES.md for the modules in scope and their install commands.`.
  - `index.WriteAgents(path, block string) error` replaces an existing marked block, or appends one (with a blank line before it) and creates the file if it is missing.
  - CLI:
    - `init [--ecosystem E] [--provider SPEC] [--project DIR]`. The default provider is `forgejo:repo.billbert.co/artifactory`. It refuses to run if `artifactory.yaml` exists (exit 1), then runs `index`.
    - `add NAME... [--project DIR]` puts modules in scope without installing them. It exits 1 on an unknown name or an ecosystem mismatch, then runs `index`.
    - `index [--project DIR] [--modules-only]` writes `MODULES.md`, and the `AGENTS.md` block unless `--modules-only` is set. Descriptors come from the catalog at the latest tag for each module in scope.

- [ ] **Step 1: Capture the golden files from the Python code while it still exists.** Write a throwaway script in the scratchpad. It loads the 8 kit descriptors from `results/mirrors/<Kit>.git` at `main` (the main checkout's mirrors, `/data/fast/Projects/Tech/AI/Artifactory/results/mirrors`), and all 4 `samples/go` descriptors. It writes `build_index(ds, index_preamble(eco))` to the two golden files. Commit the golden files only.
- [ ] **Step 2: Write the failing tests.**
  - `TestRenderMatchesPythonGolden`, for both ecosystems: load the same descriptors through `descriptor.Load` (kits from `internal/testdata/kits`, Go from `samples/go`) and compare `Render` output with the golden file byte for byte.
  - `TestWriteAgentsBlockIsIdempotent`: run it twice on a file holding `# Mine\n\ntext\n`. The user text is kept and exactly one block remains.
  - `TestDetect`: go, godot, both (error), neither (error).
  - `TestProjectRoundTrip`.
  - `TestRunAddRejectsOtherEcosystem`: a go project with a godot module from a `dir:` catalog exits 1.
  - `TestRunIndexScopesModules`: a catalog of 4 with 2 in scope gives `MODULES.md` with exactly 2 `## ` module headings.
- [ ] **Step 3:** Run `go test ./...` and expect FAIL.
- [ ] **Step 4:** Implement.
- [ ] **Step 5:** Run `go test ./...` and expect PASS.
- [ ] **Step 6: Commit.** `feat(cli): embedded standard, project file, index, init and add`

### Task 5: `search`

**Files:**
- Create: `internal/search/search.go`, `internal/search/search_test.go`
- Create: `cmd/artifactory/search.go`

**Interfaces:**
- Consumes: `catalog.Module`.
- Produces:
  - `search.Hit{Module catalog.Module; Score float64}` (json: `name`, `summary`, `install`, `score`).
  - `search.Rank(mods []catalog.Module, query []string, eco string) []search.Hit`. It is case-insensitive, drops hits below a threshold the builder chooses, sorts by score descending and then by name, and limits results to `eco` when that is non-empty. Weights are the builder's choice, but `name` must outweigh `summary`, `summary` must outweigh `replaces`, and `replaces` must outweigh `entry`. (Amended 2026-11-06: `replaces` used to share the top weight, which let generic words such as "saving" or "loading" in passing outrank the module built for the need. Rank now compares stems, splits CamelCase names, and keeps a module that matches only some query words (at least a third) only when one of them is in its name, or is in its `replaces` list and no other module matches it; see `internal/search/search.go`.)
  - `artifactory search WORDS... [--ecosystem E] [--provider SPEC]`. With hits it prints `name  score  summary` and an `install:` line per hit. With none it prints `no module matches "<words>"; record this as a gap` and exits 0.

- [ ] **Step 1: Write the failing tests**, using `internal/testdata/kits` plus `samples/go` as a `dir:` catalog each (a plain folder with `module.yaml` counts as a module, Task 2).
  - `TestSearchFindsCursor`: `mouse cursor mode` gives `CursorKit` first.
  - `TestSearchFindsKV`: `persist key value` gives `kvstore` first.
  - `TestSearchEcosystemFilter`: `config --ecosystem godot-csharp` has no `config` (go) hit.
  - `TestSearchNoMatch`: `send mail to the IRS` gives no hits, the text contains `no module matches`, and the exit code is 0.
- [ ] **Step 2:** Run `go test ./...` and expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `go test ./...` and expect PASS.
- [ ] **Step 5: Commit.** `feat(cli): keyword search with explicit no-match`

### Task 6: `install`

**Files:**
- Create: `internal/install/install.go`, `internal/install/install_test.go`
- Create: `cmd/artifactory/install.go`

**Interfaces:**
- Consumes: `catalog.Module`, `project.File`, `index.Render`/`WriteAgents`, `descriptor.Load`.
- Produces:
  - `install.Locate(projectDir string, m catalog.Module) (string, error)` finds the installed copy. For godot-csharp it is `<project>/addons/<Name>`. For go it is the output of `go list -m -f '{{.Dir}}' <path from install line>`, run in the project.
  - `install.Run(ctx, projectDir string, m catalog.Module) (version string, err error)`. It runs `sh -c <m.Install>` in `projectDir` with the inherited environment, streaming output to stderr. It then calls `Locate` followed by `descriptor.Load`, and returns that version.
  - `artifactory install NAME... [--project DIR]` requires `artifactory.yaml` (exit 2 otherwise).
    - For each name it checks the catalog and the ecosystem (exit 1 on a mismatch). A module already recorded with a version is skipped, printing `NAME already installed (vX)`.
    - Otherwise it runs the install and records the version in `artifactory.yaml`.
    - After all names, it re-runs `index`.
    - If any install fails, it stops at that module, leaves the files untouched for that module, and exits 1.

- [ ] **Step 1: Write the failing tests**, with a `dir:` catalog of local git repos, and a godot-csharp module whose install line is `git submodule add <abs path to bare repo> addons/<Name>` into a temporary git project.
  - `TestInstallRecordsVersion`.
  - `TestInstallSkipsInstalled`.
  - `TestInstallFailureLeavesProjectUntouched`: an install line of `false` leaves `artifactory.yaml` and `MODULES.md` byte-identical, and the exit is 1.
  - `TestInstallGoModule`: a `samples/go` module through a file GOPROXY. Build it in the test with `tools/artifactory/goproxy.py`'s layout, or skip with `t.Skip` when `go` cannot reach it. Do not leave this test always skipped: build the proxy folder in Go in the test helper.
- [ ] **Step 2:** Run `go test ./...` and expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `go test ./...` and expect PASS.
- [ ] **Step 5: Commit.** `feat(cli): install runs the module's own install line`

### Task 7: `publish`

**Files:**
- Create: `internal/publish/publish.go`, `internal/publish/publish_test.go`
- Create: `cmd/artifactory/publish.go`

**Interfaces:**
- Consumes: `validate.Module`, `Provider.Tags`/`Ensure`, `catalog.Latest`.
- Produces:
  - `publish.Result{Name, Tag, PushURL string; Split bool}`.
  - `publish.Publish(ctx, dir string, p provider.Provider, stdout, stderr io.Writer) (publish.Result, error)`. The steps run in this order, and each one stops the publish on failure:
    1. `validate.Module(dir)` must have no problems.
    2. Tag `v<version>` must not exist in `p.Tags(name)`. Otherwise the error is `v<version> already published; bump version in module.yaml`.
    3. Run `sh -c <test>` in `dir`, which must exit 0.
    4. `p.Ensure(name)` returns the push URL.
    5. If `dir` is the top of a git work tree, push `HEAD:refs/heads/main`. Otherwise build the commit with git plumbing from the repo top: `git ls-remote <url> refs/heads/main` and, if the remote has a `main`, `git fetch` it; then `git commit-tree <tree of HEAD:<rel>>` with the fetched `main` as parent (none when the remote has no `main`). Push that commit to `refs/heads/main` without force, then the tag. It fast-forwards by construction, and the remote keeps one commit per publish, not the folder's history. (`git subtree` is not used: it is not installed on this host or in the sandboxes.) Uncommitted changes under `dir` are an error before step 3: `commit your changes first`.
    6. Push the tag `v<version>` on the pushed commit.
  - `artifactory validate DIR --provider SPEC` additionally reports `v<version> already published` when the tag exists. Without `--provider`, validate stays offline. This is how the spec's "version tag is free" check is placed.
  - `artifactory publish [DIR] [--provider SPEC] [--skip-tests]`. `--skip-tests` exists only for modules whose `test` needs a sibling demo project. It prints a warning and is recorded in the result as `"tests_skipped": true`.

- [ ] **Step 1: Write the failing tests**, with a `dir:` provider in a temporary folder.
  - `TestPublishRootRepo`: the target bare repo has `main` and the `v0.1.0` tag.
  - `TestPublishSubfolderSplits`: a project with `lib/mymod/` publishes. The target `main` tree holds only the files of `mymod`. Bumping to `0.2.0` and committing, then publishing again, fast-forwards `main`.
  - `TestPublishRefusesExistingTag`: the test command is `touch ran` and the file `ran` must not exist afterwards.
  - `TestPublishFailingTestPushesNothing`.
  - `TestPublishRefusesDirtyTree`.
- [ ] **Step 2:** Run `go test ./...` and expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `go test ./...` and expect PASS.
- [ ] **Step 5: Commit.** `feat(cli): publish validates, tests, pushes and tags`

### Task 8: Skill file and `init` copies

**Files:**
- Create: `skill/SKILL.md`, `skill/skill.go` (package `skill`, embeds `SKILL.md`)
- Modify: `cmd/artifactory/project.go` (`init` writes the copies)
- Test: `cmd/artifactory/init_test.go`

**Interfaces:**
- Produces: `init` writes `SKILL.md` to `<dir>/skills/artifactory/SKILL.md` for each of `.claude`, `.agents` and `.opencode` that already exists in the project, and prints `wrote <path>` for each. It never creates `.claude`, `.agents` or `.opencode`.
- `SKILL.md` content, following the `writing-for-agents` skill:
  - frontmatter `name: artifactory`, plus a description that triggers before writing new functionality.
  - Body:
    - Search before writing (`artifactory search`).
    - Install only with `artifactory install`.
    - Never edit installed modules.
    - Wire every module into the real entry point.
    - When search finds nothing, record a gap in the bead and build the piece to the standard in its own folder with a `module.yaml`, so it can be published later with `artifactory publish <folder>`.
    - Each bead names the modules it uses.
  - Under 60 lines.

- [ ] **Step 1: Write the failing tests.**
  - `TestInitCopiesSkillOnlyIntoExistingHarnessDirs`: with only `.claude/` present, only that copy exists.
  - `TestInitRefusesExistingProjectFile`.
- [ ] **Step 2:** Run `go test ./cmd/...` and expect FAIL.
- [ ] **Step 3:** Implement and write `SKILL.md`.
- [ ] **Step 4:** Run `go test ./...` and expect PASS.
- [ ] **Step 5: Commit.** `feat(cli): agent skill file installed by init`

### Task 9: `artifactory mcp`

**Files:**
- Create: `internal/mcpserver/server.go`, `internal/mcpserver/server_test.go`
- Create: `cmd/artifactory/mcp.go`

**Interfaces:**
- Consumes: the same functions the `search`, `show`, `install` and `index` handlers call. Refactor those handlers so that each calls a function returning a value, used by both the CLI and MCP. Do not have the MCP server shell out to the CLI.
- Produces: `artifactory mcp [--project DIR]` serves MCP over stdio with tools `search{query string, ecosystem string?}`, `show{name string}`, `install{names []string}` and `index{}`. Each returns the same JSON the CLI's `--json` prints. Use `github.com/modelcontextprotocol/go-sdk`, pinned to a release at least two weeks old.

- [ ] **Step 1: Write the failing test.** `TestMCPToolsListAndSearch` uses the SDK's in-memory transport. It lists the tools (exactly the 4 names), then calls `search` with `mouse cursor` against a `dir:` catalog and gets `CursorKit`.
- [ ] **Step 2:** Run `go test ./internal/mcpserver/...` and expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `go test ./...` and expect PASS.
- [ ] **Step 5: Commit.** `feat(cli): optional MCP server over the same commands`

### Task 10: First real use: tag the kits and publish the Go samples

This task changes things outside the repository. It pushes tags and creates repos in the Forgejo org `artifactory`. The user authorised pushes to Forgejo.

**Files:**
- Modify: `standard/profiles/go.md` (state that Go modules live in the org and are published with `artifactory publish`)
- Modify: `docs/specs/2026-11-02-artifactory-cli-design.md` only if a fact in it turns out wrong

- [ ] **Step 1:** For each of the 8 kits in `/data/fast/Projects/Tech/Games/Godot/Modules/<Kit>`:
  - confirm `main` equals `origin/main` and `module.yaml` says `version: 0.1.0`;
  - then `git tag v0.1.0 && git push origin v0.1.0`.
  - Do not use `publish` here. The kits' `test` commands need sibling demo projects, so tag them by hand.
- [ ] **Step 2:** Run `go run ./cmd/artifactory catalog --provider forgejo:repo.billbert.co/artifactory --refresh` and expect the 8 kits. Any warnings are listed and explained in the commit message.
- [ ] **Step 3:** For each of `config httpserver kvstore shortid`, run `go run ./cmd/artifactory publish samples/go/<name> --provider forgejo:repo.billbert.co/artifactory` from the repository root. Expect 4 new repos, each with `main` and `v0.1.0` (or the descriptor's version).
- [ ] **Step 4:** Check that installing works for real. In a scratch folder:
  - `go mod init example.com/x && go get repo.billbert.co/artifactory/kvstore@v0.1.0`
  - expect success with `GOPROXY=direct GOPRIVATE=repo.billbert.co`.
  - If that fails, record the go-get failure in a bead (`bd create`) and continue. The harness still uses the local proxy.
- [ ] **Step 5:** Run `go run ./cmd/artifactory search persist key value --provider forgejo:repo.billbert.co/artifactory` and expect `kvstore` first.
- [ ] **Step 6: Commit.** `chore: kits tagged v0.1.0; Go samples published to the org`

### Task 11: The harness uses the CLI

**Files:**
- Modify: `tools/artifactory/harness.py`: `run_round` builds the binary and writes `MODULES.md` through it; drop `_godot_descriptors` and `_go_descriptors`
- Modify: `tools/artifactory/cli.py`: drop the `validate` and `index` subcommands and their imports
- Modify: `tools/artifactory/checks/godot.py`: `_liveness` reads `liveness` from the installed `module.yaml` with `yaml.safe_load`, keeping the profile default as fallback. (Ruling: the spec suggested `artifactory show --json`, but the checker runs inside the sandbox without the binary and reads a single field. Reading one field is not validation, so there is still only one validator.)
- Delete: `tools/artifactory/descriptor.py`, `tools/artifactory/index.py`, `tools/tests/test_descriptor.py`, `tools/tests/test_index.py`
- Test: `tools/tests/test_harness.py`

**Interfaces:**
- Consumes: `artifactory index --project DIR --modules-only`, `--provider dir:...`.
- Produces: `build_cli(out: Path) -> Path` in `harness.py` runs `go build -o <out>/bin/artifactory ./cmd/artifactory` from `REPO` and returns the path. `render_index(cli: Path, ecosystem: str, provider: str, modules: list[str]) -> str`:
  - writes `artifactory.yaml` into a fresh temporary folder;
  - runs `<cli> index --project <tmp> --modules-only`;
  - returns the contents of `MODULES.md`.
  - Godot: provider `dir:<root>/mirrors`, modules `test.modules`. This needs the mirrors to carry the `v0.1.0` tags from Task 10, which `artifactory mirror` fetches.
  - Go: provider `dir:<REPO>/samples/go`, modules all four samples, matching today's index.
  - The trial project still receives only `MODULES.md`, as in round 6. No `artifactory.yaml`, `AGENTS.md` block or skill file is added, so round 8 stays comparable. Adding them is a deliberate change for the arc rounds (`Artifactory-3rm`).

- [ ] **Step 1: Write the failing test.** `test_render_index_matches_golden`: `render_index` over `dir:<REPO>/samples/go` with all 4 samples equals `internal/index/testdata/go.golden.md`.
- [ ] **Step 2:** Run `uv run --project tools pytest tools/tests/test_harness.py -q` and expect FAIL.
- [ ] **Step 3:** Implement, and remove the dead Python. `grep -rn "descriptor\|build_index" tools` must then show nothing but `checks/godot.py`'s yaml read.
- [ ] **Step 4:** Run `uv run --project tools pytest tools/tests -q` and `go test ./...` and expect both to PASS.
- [ ] **Step 5:** Refresh the mirrors (`uv run --project tools artifactory mirror`) and run a one-trial Go dry check. Run `uv run --project tools artifactory round tests/acceptance/go-url-shortener --round 99 --trials 1` with `results_root` pointed at the scratchpad, or stop it after `MODULES.md` is written. Confirm the trial's `MODULES.md` equals the golden file. Delete the scratch results afterwards.
- [ ] **Step 6: Commit.** `harness: build the index with the artifactory CLI`
