"""artifactory command line."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .descriptor import DescriptorError, load_descriptor
from .index import build_index, index_preamble

PREAMBLE = Path(__file__).resolve().parents[2] / "standard" / "preamble.md"


def _load_all(dirs: list[str]):
    ok, failed = [], False
    for d in dirs:
        try:
            ok.append(load_descriptor(Path(d)))
        except DescriptorError as e:
            failed = True
            for p in e.problems:
                print(f"{d}: {p}", file=sys.stderr)
    return ok, failed


def cmd_validate(args) -> int:
    _, failed = _load_all(args.module_dir)
    return 1 if failed else 0


def cmd_index(args) -> int:
    descriptors, failed = _load_all(args.module_dir)
    if failed:
        return 1
    ecosystems = {d.ecosystem for d in descriptors}
    if len(ecosystems) > 1:
        print(f"modules mix ecosystems: {', '.join(sorted(ecosystems))}", file=sys.stderr)
        return 1
    preamble = index_preamble(ecosystems.pop()) if ecosystems else PREAMBLE.read_text()
    Path(args.output).write_text(build_index(descriptors, preamble))
    return 0


def cmd_check(args) -> int:
    from .acceptance import load_acceptance

    test = load_acceptance(Path(args.test_dir))
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
        result = check_godot(Path(args.project_dir), test, Path(args.mirrors), args.branch, baseline=args.baseline)
    Path(args.output).write_text(result.to_json())
    return 0


def cmd_round(args) -> int:
    from .harness import run_round

    result = run_round(Path(args.test_dir), args.round, trials=args.trials, baseline=args.baseline)
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
    v = sub.add_parser("validate", help="validate module descriptors")
    v.add_argument("module_dir", nargs="+")
    v.set_defaults(func=cmd_validate)
    i = sub.add_parser("index", help="build the module index")
    i.add_argument("module_dir", nargs="+")
    i.add_argument("-o", "--output", required=True)
    i.set_defaults(func=cmd_index)
    c = sub.add_parser("check", help="grade one trial project (the harness runs this inside the sandbox)")
    c.add_argument("test_dir")
    c.add_argument("project_dir")
    c.add_argument("--mirrors", help="directory of bare kit mirrors (Godot)")
    c.add_argument("--branch", default="main", help="branch kits must be published on (Godot)")
    c.add_argument("--baseline", action="store_true", help="baseline grading (Godot)")
    c.add_argument("--proxy", help="file GOPROXY directory (Go)")
    c.add_argument("-o", "--output", required=True)
    c.set_defaults(func=cmd_check)
    r = sub.add_parser("round", help="run one round of sandboxed trials against the local model")
    r.add_argument("test_dir")
    r.add_argument("--round", type=int, default=0)
    r.add_argument("--trials", type=int, default=5)
    r.add_argument("--baseline", action="store_true", help="plain README index, kits checked against main")
    r.set_defaults(func=cmd_round)
    m = sub.add_parser("mirror", help="refresh bare mirrors of the Godot kits into results/mirrors/")
    m.set_defaults(func=cmd_mirror)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
