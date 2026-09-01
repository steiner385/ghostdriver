"""Command-line entry point.

Iteration 1 ships a CLI rather than an MCP server so the read path can be
validated against a real target before any protocol layer exists. The MCP
server arrives in Iteration 2 and calls the same functions.
"""

import argparse
import json
import sys

from .model.locator import Locator
from .resolve import resolve
from .summarize import summarize


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ghostdriver", description="Read-only desktop reconnaissance"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list-targets", help="List processes that own windows")

    describe = sub.add_parser("describe", help="Summarize a target's window tree")
    describe.add_argument("--pid", type=int, required=True)
    describe.add_argument("--depth", type=int, default=5)
    describe.add_argument("--max-nodes", type=int, default=200)
    describe.add_argument(
        "--all", action="store_true", help="Include hidden windows"
    )
    describe.add_argument(
        "--collapse-threshold",
        type=int,
        default=3,
        help=(
            "Collapse a run of this many same-class siblings into one line, "
            "hiding their subtrees. Raise it (e.g. 1000) to defeat collapsing "
            "when it is hiding the controls you need."
        ),
    )

    find = sub.add_parser("find", help="Resolve a locator")
    find.add_argument("--pid", type=int, required=True)
    find.add_argument("--locator", required=True)

    read = sub.add_parser("read", help="Read text of matching elements")
    read.add_argument("--pid", type=int, required=True)
    read.add_argument("--locator", required=True)

    probe = sub.add_parser("probe", help="Emit a phase-1 capability profile")
    probe.add_argument("--pid", type=int, required=True)
    probe.add_argument("--out", default=None)

    return parser


def _main_tree(pid: int):
    from .backends.windows.enumerate import enumerate_process

    trees = enumerate_process(pid)
    if not trees:
        print(f"error: pid {pid} has no windows on this desktop", file=sys.stderr)
        return None
    return max(trees, key=lambda t: sum(1 for _ in t.walk()))


def cmd_list_targets() -> int:
    import psutil

    from .backends.windows.enumerate import top_level_windows

    rows = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            handles = top_level_windows(proc.info["pid"])
        except Exception:
            continue
        if handles:
            rows.append((proc.info["pid"], proc.info["name"], len(handles)))

    print(f"{'PID':>8}  {'WINDOWS':>7}  NAME")
    for pid, name, count in sorted(rows):
        print(f"{pid:>8}  {count:>7}  {name}")
    return 0


def cmd_describe(
    pid: int,
    depth: int,
    max_nodes: int,
    show_all: bool,
    collapse_threshold: int = 3,
) -> int:
    tree = _main_tree(pid)
    if tree is None:
        return 2
    summary = summarize(
        tree,
        max_depth=depth,
        visible_only=not show_all,
        max_nodes=max_nodes,
        collapse_threshold=collapse_threshold,
    )
    print(summary.text)
    print(
        f"\n{summary.node_count} nodes shown, "
        f"truncated={summary.truncated}, elided={summary.elided_nodes}"
    )
    if summary.suggested_locators:
        print("\nSuggested locators:")
        for locator in summary.suggested_locators[:30]:
            print(f"  {locator}")
    return 0


#: Printed in place of a control's text when the control never answered.
#: An empty line would be indistinguishable from a control that answered
#: and genuinely has no text, which is the one distinction
#: WindowNode.responsive exists to preserve.
NO_ANSWER = "<no answer>"


def _parse_locator(expr: str) -> Locator | None:
    """Parse a locator expression, reporting a bad one cleanly.

    Locator.parse raises ValueError naming the offending key. Letting that
    escape prints a traceback, which in a one-shot remote session buries
    the one line that says what to type instead.
    """
    try:
        return Locator.parse(expr)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None


def cmd_find(pid: int, expr: str) -> int:
    locator = _parse_locator(expr)
    if locator is None:
        return 2
    tree = _main_tree(pid)
    if tree is None:
        return 2
    matches = resolve(tree, locator)
    if not matches:
        print("no matches", file=sys.stderr)
        return 1
    for node in matches:
        print(
            f"0x{node.handle:08X}  {node.class_name:<32} "
            f"visible={str(node.visible):<5} "
            f"responsive={str(node.responsive):<5} "
            f"rect={node.rect}  {node.text!r}"
        )
    print(f"\n{len(matches)} match(es)")
    return 0


def cmd_read(pid: int, expr: str) -> int:
    locator = _parse_locator(expr)
    if locator is None:
        return 2
    tree = _main_tree(pid)
    if tree is None:
        return 2
    matches = resolve(tree, locator)
    if not matches:
        print("no matches", file=sys.stderr)
        return 1
    for node in matches:
        # A control that did not answer carries text="" exactly like a
        # control that answered with nothing. Printing a blank line for
        # both would erase the difference at the command this gate exists
        # to exercise.
        print(NO_ANSWER if not node.responsive else node.text)
    return 0


def cmd_probe(pid: int, out: str | None) -> int:
    from .probe.runner import run_phase1

    try:
        document = run_phase1(pid)
    except (RuntimeError, OSError, AttributeError) as exc:
        # OSError covers a Win32 call failing or a DLL that will not load;
        # AttributeError covers a system library missing an export we
        # declared. Both are environmental, and a one-shot remote session
        # should get a line it can report rather than a stack dump.
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    payload = json.dumps(document.to_dict(), indent=2)
    if out:
        document.save(out)
        print(f"profile written to {out}")
        print(f"matched_profile={document.matched_profile} "
              f"toolkit={document.toolkit.get('inferred')} "
              f"uia={document.uia.get('verdict')} "
              f"windows={document.window_count}")
    else:
        print(payload)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.command:
        print("error: a subcommand is required", file=sys.stderr)
        return 2
    if args.command == "list-targets":
        return cmd_list_targets()
    if args.command == "describe":
        return cmd_describe(
            args.pid, args.depth, args.max_nodes, args.all,
            args.collapse_threshold,
        )
    if args.command == "find":
        return cmd_find(args.pid, args.locator)
    if args.command == "read":
        return cmd_read(args.pid, args.locator)
    if args.command == "probe":
        return cmd_probe(args.pid, args.out)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
