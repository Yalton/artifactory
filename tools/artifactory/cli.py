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
        if bool(args.arc_registry) != bool(args.arc_base):
            print("check: --arc-registry and --arc-base go together for a Go test", file=sys.stderr)
            return 2
        if args.main_pkg:
            import dataclasses
            test = dataclasses.replace(test, main_pkg=args.main_pkg)
        from .checks import go as go_check
        result = go_check.check_go(Path(args.project_dir), test, Path(args.proxy),
                                   arc_registry=Path(args.arc_registry) if args.arc_registry else None,
                                   arc_base=args.arc_base)
    elif test.ecosystem == "python":
        if not args.pyindex:
            print("check: --pyindex is required for a Python test", file=sys.stderr)
            return 2
        if not test.python_app:
            print(f"check: {args.test_dir}/test.yaml has no python_app", file=sys.stderr)
            return 2
        from .checks.python import check_python
        result = check_python(Path(args.project_dir), test, Path(args.pyindex))
    elif test.ecosystem == "godot-csharp":
        if not args.mirrors:
            print("check: --mirrors is required for a Godot test", file=sys.stderr)
            return 2
        from .checks.godot import check_godot
        result = check_godot(Path(args.project_dir), test, Path(args.mirrors), args.branch, baseline=args.baseline,
                              arc_base=args.arc_base if args.arc else None)
    else:
        print(f"check: no checker for ecosystem {test.ecosystem!r} (known: go, python, godot-csharp)",
              file=sys.stderr)
        return 2
    Path(args.output).write_text(result.to_json())
    return 0


def cmd_round(args) -> int:
    from .harness import run_round

    try:
        result = run_round(Path(args.test_dir), args.round, trials=args.trials, baseline=args.baseline,
                           product=args.product, arc=args.arc, arc_src=args.arc_src, roadmap=args.roadmap,
                           time_limit_s=args.time_limit_s)
    except ValueError as e:
        print(f"artifactory round: {e}", file=sys.stderr)
        return 1
    print(f"{result.test} {'baseline' if args.baseline else f'round {result.round}'}: "
          f"{result.passes}/{len(result.results)} passed"
          + ("" if result.met_bar is None else f"; bar {'met' if result.met_bar else 'not met'}")
          + (f"; {result.infrastructure_failures} infrastructure failures" if result.infrastructure_failures else ""))
    return 0


def cmd_experiment(args) -> int:
    from . import harness

    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()] if args.conditions else None
    try:
        rounds = harness.run_experiment(Path(args.test_dir), args.round, trials=args.trials, conditions=conditions,
                                        arc_src=args.arc_src)
    except (ValueError, FileExistsError) as e:
        print(f"artifactory experiment: {e}", file=sys.stderr)
        return 1
    for c, result in rounds.items():
        print(f"{result.test} round {result.round} {c}: {result.passes}/{len(result.results)} passed"
              + (f"; {result.infrastructure_failures} infrastructure failures" if result.infrastructure_failures else ""))
    return 0


def cmd_blind_export(args) -> int:
    from .blind import blind_export

    test_dir = Path(args.results_dir)
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()] if args.conditions else None
    if conditions is None:
        conditions = sorted({p.name.split("-", 2)[2] for p in test_dir.glob(f"round-{args.round}-*")})
    try:
        key = blind_export(test_dir, args.round, conditions, Path(args.out), args.seed)
    except FileExistsError as e:
        print(f"artifactory blind-export: {e}", file=sys.stderr)
        return 2
    print(f"blind export: {args.out} (key: {key})")
    return 0


def cmd_mirror(args) -> int:
    from .harness import refresh_mirrors

    for path in refresh_mirrors(tests=[Path(t) for t in args.test_dirs] or None):
        print(path)
    return 0


def cmd_roadmap_workspace(args) -> int:
    import tempfile

    from .acceptance import load_acceptance
    from .harness import RESULTS, build_arc, build_cli, prepare_roadmap_workspace

    test = load_acceptance(Path(args.test_dir))
    mirrors = RESULTS / "mirrors"
    for name in test.modules:
        if not (mirrors / f"{name}.git").is_dir():
            print(f"roadmap-workspace: no mirror at {mirrors / (name + '.git')}; run `artifactory mirror` first",
                  file=sys.stderr)
            return 2
    with tempfile.TemporaryDirectory(prefix="artifactory-build-") as tmp:
        trial, prefix = prepare_roadmap_workspace(test, Path(args.out_dir), mirrors, build_cli(Path(tmp)),
                                                  build_arc(Path(tmp), args.arc_src))
    print(f"project: {trial.project}")
    print(f"env: {prefix}")
    return 0


def cmd_roadmap_export(args) -> int:
    from .harness import export_roadmap

    try:
        n = export_roadmap(Path(args.project), Path(args.output))
    except RuntimeError as e:
        print(f"roadmap-export: {e}", file=sys.stderr)
        return 1
    print(f"{n} beads exported to {args.output}")
    return 0


def cmd_roadmap_score(args) -> int:
    import json

    from .acceptance import load_acceptance
    from .roadmap import CONTRACTS, format_score, score_roadmap

    kits = load_acceptance(Path(args.test)).modules
    try:
        score = score_roadmap(Path(args.file), kits, CONTRACTS)
    except (OSError, ValueError) as e:
        print(f"roadmap-score: {e}", file=sys.stderr)
        return 1
    print(json.dumps(score, indent=2) if args.json else format_score(score, kits))
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
    c.add_argument("--arc-base", help="fixture commit arc gate compares against (with --arc; Go: with --arc-registry)")
    c.add_argument("--proxy", help="file GOPROXY directory (Go)")
    c.add_argument("--main-pkg", help="package to build and run, overriding test.yaml's main_pkg (Go)")
    c.add_argument("--arc-registry", help="arc registry the checker installs to report arc_gate boundary findings (Go)")
    c.add_argument("--pyindex", help="wheel directory the clean environment installs from (Python)")
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
    r.add_argument("--time-limit-s", type=int, help="wall-clock seconds per trial (default: test.yaml's time_limit_s)")
    r.set_defaults(func=cmd_round)
    x = sub.add_parser("experiment", help="run a Go test's conditions, trials interleaved, on its frozen roadmap")
    x.add_argument("test_dir")
    x.add_argument("--round", type=int, required=True)
    x.add_argument("--trials", type=int, default=3, help="trials per condition (default 3)")
    x.add_argument("--conditions", help="comma-separated subset of the test's conditions, in run order "
                                        "(default: all, as test.yaml lists them)")
    x.add_argument("--arc-src", type=Path, help="arc source tree to build (default $ARC_SRC)")
    x.set_defaults(func=cmd_experiment)
    b = sub.add_parser("blind-export", help="copy an experiment round's projects under shuffled labels, tool traces removed")
    b.add_argument("results_dir", help="results/<test>")
    b.add_argument("--round", type=int, required=True)
    b.add_argument("--out", required=True, help="directory for the labelled projects (key.json goes beside it)")
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--conditions", help="comma-separated (default: every condition found for the round)")
    b.set_defaults(func=cmd_blind_export)
    m = sub.add_parser("mirror", help="refresh bare mirrors of the tests' kits (default: the Godot kits) into results/mirrors/")
    m.add_argument("test_dirs", nargs="*", help="acceptance test dirs whose modules to mirror")
    m.set_defaults(func=cmd_mirror)
    w = sub.add_parser("roadmap-workspace", help="prepare the frontier roadmap writer's workspace (no roadmap imported)")
    w.add_argument("test_dir")
    w.add_argument("out_dir")
    w.add_argument("--arc-src", type=Path, help="arc source tree to build (default $ARC_SRC)")
    w.set_defaults(func=cmd_roadmap_workspace)
    e = sub.add_parser("roadmap-export", help="export the writer's beads as the frozen roadmap, after checks")
    e.add_argument("project")
    e.add_argument("output")
    e.set_defaults(func=cmd_roadmap_export)
    s = sub.add_parser("roadmap-score", help="score an exported roadmap: kits named, unknown modules, contracts, gap coverage")
    s.add_argument("file")
    s.add_argument("--test", default=str(Path(__file__).resolve().parents[2] / "tests" / "acceptance" / "godot-lantern-keep"),
                   help="acceptance test directory whose modules are the kits (default: godot-lantern-keep)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_roadmap_score)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
