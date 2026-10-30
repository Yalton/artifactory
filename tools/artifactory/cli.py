"""artifactory command line."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .descriptor import DescriptorError, load_descriptor
from .index import build_index

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
    Path(args.output).write_text(build_index(descriptors, PREAMBLE.read_text()))
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
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
