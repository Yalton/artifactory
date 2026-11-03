"""artifactory command line."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cmd_check(args) -> int:
    from .acceptance import load_acceptance

    test = load_acceptance(Path(args.test_dir))
    if args.arc and not args.arc_base:
        print("check: --arc needs --arc-base", file=sys.stderr)
        return 2
    if test.ecosystem == "go":
        if not args.proxy:
            print("check: --proxy is required for a Go test", file=sys.stderr)
            return 2
        from .checks.go import check_go
        result = check_go(Path(args.project_dir), test, Path(args.proxy))
    else:
        if not args.mirrors:
            print("check: --mirrors is required for a Godot test", file=sys.stderr)
            return 2
        from .checks.godot import check_godot
        result = check_godot(Path(args.project_dir), test, Path(args.mirrors), args.branch, baseline=args.baseline,
                              arc_base=args.arc_base if args.arc else None)
    Path(args.output).write_text(result.to_json())
    return 0


def cmd_round(args) -> int:
    from .harness import run_round

    result = run_round(Path(args.test_dir), args.round, trials=args.trials, baseline=args.baseline,
                       product=args.product, arc=args.arc, arc_src=args.arc_src, roadmap=args.roadmap)
    print(f"{result.test} {'baseline' if args.baseline else f'round {result.round}'}: "
          f"{result.passes}/{len(result.results)} passed; bar {'met' if result.met_bar else 'not met'}")
    return 0


def cmd_mirror(args) -> int:
    from .harness import refresh_mirrors

    for path in refresh_mirrors():
        print(path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="artifactory")
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="grade one trial project (the harness runs this inside the sandbox)")
    c.add_argument("test_dir")
    c.add_argument("project_dir")
    c.add_argument("--mirrors", help="directory of bare kit mirrors (Godot)")
    c.add_argument("--branch", default="main", help="branch kits must be published on (Godot)")
    c.add_argument("--baseline", action="store_true", help="baseline grading (Godot)")
    c.add_argument("--arc", action="store_true", help="also report arc gate, informationally (Godot)")
    c.add_argument("--arc-base", help="fixture commit arc gate compares against (with --arc)")
    c.add_argument("--proxy", help="file GOPROXY directory (Go)")
    c.add_argument("-o", "--output", required=True)
    c.set_defaults(func=cmd_check)
    r = sub.add_parser("round", help="run one round of sandboxed trials against the local model")
    r.add_argument("test_dir")
    r.add_argument("--round", type=int, default=0)
    r.add_argument("--trials", type=int, default=5)
    r.add_argument("--baseline", action="store_true", help="plain README index, kits checked against main")
    r.add_argument("--product", action="store_true",
                   help="run the artifactory CLI in the sandbox (dir: provider on the local mirrors)")
    r.add_argument("--arc", action="store_true",
                   help="with --product: install arc (registry, opencode plugin) in each trial; checker reports arc_gate")
    r.add_argument("--roadmap", choices=["none", "frontier", "ornith"], default="none",
                   help="bead conditions (need --product --arc): frontier imports the frozen roadmap, "
                        "ornith writes one first; none is one session with the brief")
    r.add_argument("--arc-src", type=Path, help="arc source tree to build (default $ARC_SRC)")
    r.set_defaults(func=cmd_round)
    m = sub.add_parser("mirror", help="refresh bare mirrors of the Godot kits into results/mirrors/")
    m.set_defaults(func=cmd_mirror)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
