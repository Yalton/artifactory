import json
from pathlib import Path

from artifactory.tooluse import MCP_PREFIX, count_tool_use


def _tr(tmp_path, events, name="transcript.jsonl"):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return p


def _call(tool, **inp):
    # Shape copied from real opencode transcripts: {"type": "tool_use", "part": {"tool", "state": {"input"}}}
    return {"type": "tool_use", "part": {"type": "tool", "tool": tool, "state": {"status": "completed", "input": inp}}}


def sh(cmd):
    return _call("shell", command=cmd)


def test_mcp_prefix_pinned():
    # opencode (mcp/index.ts) names an MCP tool "<sanitized server name>_<sanitized tool name>"
    # (sanitize: [^a-zA-Z0-9_-] -> "_"); the server is configured as "artifactory" in harness.py.
    # The sanitising pattern string is present in the installed binary ~/.opencode/bin/opencode.
    assert MCP_PREFIX == "artifactory_"


def test_command_word_positions(tmp_path):
    t = _tr(tmp_path, [
        sh("artifactory search foo"),
        sh("cd x && artifactory add y; arc status | cat"),
        sh("echo $(artifactory search z)"),
        sh("ls\nartifactory search again"),
        sh("arc init"),
    ])
    r = count_tool_use([t], None)
    assert r["artifactory"] == {"search": 3, "add": 1}
    assert r["arc"] == {"status": 1, "init": 1}


def test_path_and_prose_do_not_count(tmp_path):
    t = _tr(tmp_path, [
        sh("cat /home/u/Projects/artifactory/README.md"),
        sh('echo "run artifactory search later"'),
        sh("grep -r artifactory search.txt"),
        _call("read", path="/x/artifactory search/y", command="artifactory search"),  # not a shell tool
        {"type": "text", "part": {"type": "text", "text": "artifactory search"}},
    ])
    r = count_tool_use([t], None)
    assert r["artifactory"] == {} and r["arc"] == {}


def test_mcp_and_bash_tool(tmp_path):
    t = _tr(tmp_path, [_call("artifactory_search", query="q"), _call("artifactory_search"), _call("artifactory_info"),
                       _call("bash", command="artifactory info x"), _call("other_search")])
    r = count_tool_use([t], None)
    assert r["mcp"] == {"search": 2, "info": 1}
    assert r["artifactory"] == {"info": 1}


def test_proxy_snoop(tmp_path):
    proxy = tmp_path / "goproxy" / "t"
    t = _tr(tmp_path, [sh(f"ls {proxy}"), sh("echo $GOPROXY"), sh("go env GOPATH"), sh("go build ./..."),
                       _call("read", path=str(proxy))])
    assert count_tool_use([t], proxy)["proxy_snoop"] == 3
    assert count_tool_use([t], None)["proxy_snoop"] == 2


def test_multiple_transcripts_and_bad_lines(tmp_path):
    a = _tr(tmp_path, [sh("artifactory search a")], "transcript.jsonl")
    b = _tr(tmp_path, [sh("artifactory search b")], "transcript-2.jsonl")
    b.write_text(b.read_text() + "not json\n")
    assert count_tool_use([a, b], None)["artifactory"] == {"search": 2}


def test_non_dict_json_lines_skipped(tmp_path):
    t = tmp_path / "transcript.jsonl"
    t.write_text('0\nnull\n"x"\n[1]\n' + json.dumps(sh("artifactory search a")) + "\n")
    assert count_tool_use([t], None)["artifactory"] == {"search": 1}


def test_code_mode_mcp_calls(tmp_path):
    # Shape from the Nov 8 smoke round: opencode runs MCP tools through its "execute" tool.
    import json
    from artifactory.tooluse import count_tool_use
    t = tmp_path / "transcript-1.jsonl"
    ev = lambda code: json.dumps({"type": "tool_use", "part": {"type": "tool", "tool": "execute",
                                  "state": {"input": {"code": code}}}})
    t.write_text("\n".join([
        ev('return await tools.artifactory.search({ query: "http server" })'),
        ev('const a = await tools.artifactory.show({ name: "httpserver" }); await tools.artifactory.install({names: ["x"]})'),
        ev('return await tools.opencode.fetch("GET", "repo.billbert.co/artifactory/httpserver")'),
    ]) + "\n")
    assert count_tool_use([t], None)["mcp"] == {"search": 1, "show": 1, "install": 1}


def test_go_env_snoop_only_when_it_prints_goproxy(tmp_path):
    import json
    from artifactory.tooluse import count_tool_use
    t = tmp_path / "transcript-1.jsonl"
    ev = lambda cmd: json.dumps({"type": "tool_use", "part": {"type": "tool", "tool": "shell",
                                 "state": {"input": {"command": cmd}}}})
    t.write_text("\n".join([ev("GOROOT=$(go env GOROOT); ls $GOROOT"), ev("go env | grep PROXY"),
                            ev("go env -json"), ev("go env GOPROXY")]) + "\n")
    assert count_tool_use([t], None)["proxy_snoop"] == 3
