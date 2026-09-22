"""Command-line entry point.

Iteration 1 ships a CLI rather than an MCP server so the read path can be
validated against a real target before any protocol layer exists. The MCP
server arrives in Iteration 2 and calls the same functions.
"""

import argparse
import json
import os
import sys

from .model.locator import Locator
from .model.window import select_main_tree
from .operator import ENV_VAR, OperatorDir, OperatorDirError
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
        "--all-windows",
        action="store_true",
        help=(
            "Describe every top-level window of the process, not just the "
            "main one. --max-nodes is then a budget for the whole command, "
            "spent main window first"
        ),
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

    all_windows_help = (
        "Search every top-level window of the process, not just the main "
        "one. Menus, dropdowns, lookups and modal dialogs are separate "
        "top-level windows in some toolkits and are invisible without this"
    )

    find = sub.add_parser("find", help="Resolve a locator")
    find.add_argument("--pid", type=int, required=True)
    find.add_argument("--locator", required=True)
    find.add_argument("--all-windows", action="store_true", help=all_windows_help)

    read = sub.add_parser("read", help="Read text of matching elements")
    read.add_argument("--pid", type=int, required=True)
    read.add_argument("--locator", required=True)
    read.add_argument("--all-windows", action="store_true", help=all_windows_help)

    probe = sub.add_parser("probe", help="Emit a phase-1 capability profile")
    probe.add_argument("--pid", type=int, required=True)
    probe.add_argument("--out", default=None)

    surfaces = sub.add_parser(
        "surfaces",
        help=(
            "Map which mechanism can drive each region: window messages, "
            "an accessibility surface, a web document, or pixels only"
        ),
    )
    surfaces.add_argument("--pid", type=int, required=True)
    surfaces.add_argument(
        "--all", action="store_true", help="Include hidden windows"
    )
    surfaces.add_argument(
        "--all-windows",
        action="store_true",
        help=(
            "Map every top-level window of the process, not just the main "
            "one. Menus, dropdowns, lookups and modal dialogs are separate "
            "top-level windows in some toolkits"
        ),
    )
    surfaces.add_argument(
        "--changed-from",
        default=None,
        metavar="DIGEST",
        help=(
            "Exit 4 if the surface map's shape differs from this digest, "
            "for detecting that a screen now needs a different approach"
        ),
    )

    modals = sub.add_parser(
        "modals",
        help=(
            "Report whether the target is held by a modal dialog, and by "
            "which one"
        ),
    )
    modals.add_argument("--pid", type=int, required=True)

    restore = sub.add_parser(
        "restore",
        help=(
            "Bring a minimized target back on screen without taking focus. "
            "The only command that changes what is on screen; it is never "
            "run as a side effect of describe, find, read or probe."
        ),
    )
    restore.add_argument("--pid", type=int, required=True)

    # The operator's harness. Workflows and profiles live in the operator
    # directory (GHOSTDRIVER_OPERATOR_DIR), never in a repository; these
    # commands are how they are listed and run.
    listing = sub.add_parser("list-workflows",
                             help="List the workflows in the operator directory")
    listing.add_argument("--operator-dir", default=None,
                         help=f"Overrides {ENV_VAR}")
    run = sub.add_parser(
        "run-workflow",
        help=(
            "Run one workflow from the operator directory against a running "
            "target, under an interference watch, and write a report back."
        ),
    )
    run.add_argument("name", help="Workflow name (workflows/<name>.json)")
    run.add_argument("--pid", type=int, required=True,
                     help="The target to attach to; the workflow names none")
    run.add_argument("--operator-dir", default=None,
                     help=f"Overrides {ENV_VAR}")

    trace = sub.add_parser(
        "trace",
        help=(
            "Show what tool calls sessions made, from the trace files under "
            "the operator directory's logs/ (newest file by default)."
        ),
    )
    trace.add_argument("--tail", type=int, default=40, help="Last N calls (default 40)")
    trace.add_argument("--session", default=None, help="Only this session id")
    trace.add_argument("--all-files", action="store_true",
                       help="Every trace file, not just the newest")
    trace.add_argument("--operator-dir", default=None, help=f"Overrides {ENV_VAR}")

    check = sub.add_parser(
        "check-profile",
        help=("Read a profile document back and say what the tool will make of it: "
              "denylist names and places, sensitivity notes, busy indicator, safe "
              "controls; warns about keys it does not read."),
    )
    check.add_argument("profile", help="A bare name under the operator directory, or a path")
    check.add_argument("--operator-dir", default=None, help=f"Overrides {ENV_VAR}")

    return parser


def _main_tree(pid: int):
    from .backends import current
    enumerate_process = current().enumerate_process

    trees = enumerate_process(pid)
    tree = select_main_tree(trees)
    if tree is None:
        print(f"error: pid {pid} has no windows on this desktop", file=sys.stderr)
        return None
    return tree


def _trees(pid: int, all_windows: bool):
    """The trees a command should work over.

    One tree is the right default: it is the window the user is looking at,
    and it keeps a locator from matching something not on screen. But this
    toolkit family puts every menu, dropdown, lookup list and modal dialog
    in its *own* top-level window, so a caller restricted to the main tree
    cannot reach the control it most needs -- measured on a real target,
    48% of the process's windows sat outside it, including every dialog.
    `--all-windows` reaches them.
    """
    from .backends import current
    enumerate_process = current().enumerate_process

    trees = enumerate_process(pid)
    if not trees:
        print(f"error: pid {pid} has no windows on this desktop", file=sys.stderr)
        return None
    if all_windows:
        # Largest first, so the main window's matches lead the output.
        return sorted(trees, key=lambda t: -sum(1 for _ in t.walk()))
    return [select_main_tree(trees)]


def cmd_list_targets() -> int:
    import psutil

    from .backends import current
    top_level_windows = current().top_level_windows

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
    all_windows: bool = False,
) -> int:
    """Summarize the target's window tree, or every one of its windows.

    `max_nodes` is a budget for the whole command, not for each window.
    Spending it per window would make the output grow with however many
    windows a process happens to own -- 185 on a measured target -- which
    defeats the one thing this command exists to guarantee. The main window
    is described first and takes what it needs; the rest share what is
    left, and any window that could not be reached is counted rather than
    dropped in silence.
    """
    from .backends import current
    top_level_state = current().top_level_state
    from .modality import find_modal_blocks

    trees = _trees(pid, all_windows)
    if trees is None:
        return 2

    # Said first. An agent orienting itself on an unfamiliar screen needs to
    # know the window is disabled before it reads a single control, or it
    # will plan against a UI that cannot answer it.
    blocked_handles: dict[int, str] = {}
    blocks, unexplained = find_modal_blocks(top_level_state(pid))
    for block in blocks:
        print(f"BLOCKED: {block.describe()}")
        blocked_handles[block.dialog.handle] = "dialog holding another window"
    for item in unexplained:
        print(
            f"BLOCKED: {item.blocked.text or item.blocked.class_name} is "
            "disabled with no visible dialog to account for it"
        )
    if blocks or unexplained:
        print()

    remaining = max_nodes
    described = 0
    omitted = 0
    totals = {"nodes": 0, "elided": 0, "below_depth": 0}
    truncated = False
    locators: list[str] = []

    not_visible = 0
    for index, tree in enumerate(trees):
        if all_windows and not show_all and not tree.visible:
            # summarize() always emits the root, so without this every
            # hidden pooled form in the process earns a heading and a line
            # -- 183 of them on a measured target. The single-window
            # default is exempt: a minimized target has no visible window
            # at all, and describing it is exactly what is wanted then.
            not_visible += 1
            continue
        if remaining <= 0:
            omitted += 1
            continue

        summary = summarize(
            tree,
            max_depth=depth,
            visible_only=not show_all,
            max_nodes=remaining,
            collapse_threshold=collapse_threshold,
        )
        if not summary.node_count:
            # Nothing survived the visibility filter. Not worth a heading.
            continue

        if all_windows:
            role = "main window" if index == 0 else "other top-level window"
            if tree.handle in blocked_handles:
                role = blocked_handles[tree.handle]
            caption = f' "{tree.text}"' if tree.text else ""
            if described:
                print()
            print(
                f"=== {tree.class_name}{caption}  [{role}]  "
                f"visible={tree.visible}"
            )
        print(summary.text)

        described += 1
        remaining -= summary.node_count
        totals["nodes"] += summary.node_count
        totals["elided"] += summary.elided_nodes
        totals["below_depth"] += summary.depth_elided_nodes
        truncated = truncated or summary.truncated
        for locator in summary.suggested_locators:
            if locator not in locators:
                locators.append(locator)

    if not described:
        print("nothing to describe: no window has visible content")
        if not show_all:
            print("  add --all to include hidden windows")
        return 0

    print()
    scope = f"{described} window(s), " if all_windows else ""
    print(
        f"{scope}{totals['nodes']} nodes shown, "
        f"truncated={truncated}, elided={totals['elided']}, "
        f"below-depth={totals['below_depth']}"
    )
    if totals["below_depth"]:
        # Named separately from `elided` because the remedy differs:
        # this is --depth, not --collapse-threshold.
        print(
            f"  {totals['below_depth']} nodes lie below --depth "
            f"{depth}; raise it to see them"
        )
    if omitted:
        print(
            f"  {omitted} further window(s) not described: the "
            f"--max-nodes budget of {max_nodes} was spent"
        )
    if not_visible:
        print(
            f"  {not_visible} window(s) skipped as not visible; add --all "
            "to include them"
        )
    if not all_windows:
        # The same trap `find` warns about. A dialog is a separate
        # top-level window, so the screen an operator is looking at may not
        # be the one described here.
        print(
            "  only the main window was described; add --all-windows for "
            "dialogs, menus and dropdowns"
        )
    if locators:
        print()
        print("Suggested locators:")
        for locator in locators[:30]:
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


def cmd_find(pid: int, expr: str, all_windows: bool = False) -> int:
    locator = _parse_locator(expr)
    if locator is None:
        return 2
    trees = _trees(pid, all_windows)
    if trees is None:
        return 2
    matches = [n for tree in trees for n in resolve(tree, locator)]
    if not matches:
        print("no matches", file=sys.stderr)
        if not all_windows:
            # Menus, dropdowns, lookups and modal dialogs are separate
            # top-level windows in some toolkits. Saying so costs one line
            # and saves a caller concluding the control does not exist.
            print(
                "hint: only the main window was searched; add "
                "--all-windows to include dialogs, menus and dropdowns",
                file=sys.stderr,
            )
        return 1
    for node in matches:
        print(
            f"0x{node.handle:08X}  {node.class_name:<32} "
            f"visible={node.visible!s:<5} "
            f"responsive={node.responsive!s:<5} "
            f"rect={node.rect}  {node.text!r}"
        )
    print(f"\n{len(matches)} match(es)")
    return 0


def cmd_read(pid: int, expr: str, all_windows: bool = False) -> int:
    locator = _parse_locator(expr)
    if locator is None:
        return 2
    trees = _trees(pid, all_windows)
    if trees is None:
        return 2
    matches = [n for tree in trees for n in resolve(tree, locator)]
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
        try:
            outcome = document.save(out)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"profile written to {out}")
        # Said out loud, because the previous behaviour was to silently
        # take the curated policy with it and the person re-probing is
        # exactly the person who would not think to check.
        if outcome["preserved"]:
            print("kept from the existing file: "
                  + ", ".join(outcome["preserved"]))
        print(f"matched_profile={document.matched_profile} "
              f"toolkit={document.toolkit.get('inferred')} "
              f"uia={document.uia.get('verdict')} "
              f"windows={document.window_count}")
    else:
        print(payload)
    return 0


def cmd_surfaces(
    pid: int, show_all: bool, changed_from: str | None,
    all_windows: bool = False,
) -> int:
    from .backends import current
    region_evidence = current().region_evidence
    from .surface import (
        map_digest,
        needs_other_mechanism,
        summarize_access,
        summarize_kinds,
        surface_map,
    )

    trees = _trees(pid, all_windows)
    if trees is None:
        return 2

    regions = [
        r
        for tree in trees
        for r in surface_map(tree, region_evidence, visible_only=not show_all)
    ]
    digest = map_digest(regions)

    # Said first, and unconditionally. Which mechanism drives a region is
    # academic while the window is disabled: every one of them will fail,
    # and the caller needs to deal with the dialog before anything else.
    from .backends import current
    top_level_state = current().top_level_state
    from .modality import find_modal_blocks

    blocks, unexplained = find_modal_blocks(top_level_state(pid))
    for block in blocks:
        print(f"BLOCKED: {block.describe()} -- deal with it before driving "
              "anything else")
    for item in unexplained:
        print(
            f"BLOCKED: {item.blocked.text or item.blocked.class_name!r} is "
            "disabled with no visible dialog to account for it"
        )
    if blocks or unexplained:
        print()

    counts = summarize_kinds(regions)
    print("regions by kind: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    # The half that moves. `kind` says what the target is made of; this says
    # what is readable at this moment, and an engine waking changes one and
    # not the other.
    reach = summarize_access(regions)
    print("readable via   : " + ", ".join(f"{k}={v}" for k, v in reach.items()))
    print(f"shape digest   : {digest}")

    # Only the regions a caller has to do something about. Listing the
    # native ones would bury them: they are the overwhelming majority and
    # they are the case that already works.
    other = needs_other_mechanism(regions)
    if other:
        print()
        print(f"{len(other)} region(s) need a mechanism other than "
              "window messages:")
        for region in sorted(other, key=lambda r: -r.area):
            left, top, right, bottom = region.rect
            print(
                f"  {region.kind.value:12s} via {region.access.value:16s} "
                f"{region.class_name:26s} "
                f"({left}, {top}, {right}, {bottom})  {region.area}px"
            )
            print(f"      {region.reason}")
    else:
        print()
        print("every visible region is reachable by window messages")

    if changed_from is not None and changed_from != digest:
        print(
            f"CHANGED: shape digest was {changed_from}, now {digest}. "
            "A region changed kind, or a new kind appeared -- an approach "
            "that worked before may not now.",
            file=sys.stderr,
        )
        return 4
    return 0


def cmd_modals(pid: int) -> int:
    """Report blocking state.

    Exits 5 when the target is held. A caller that retries a click into a
    disabled window will retry forever, so this is worth an exit code
    rather than a line of prose.
    """
    from .backends import current
    top_level_state = current().top_level_state
    from .modality import find_modal_blocks

    state = top_level_state(pid)
    if not state:
        print(f"error: pid {pid} has no windows on this desktop", file=sys.stderr)
        return 2

    blocks, unexplained = find_modal_blocks(state)
    if not blocks and not unexplained:
        print(f"not blocked: {len(state)} top-level window(s), none disabled")
        return 0

    for block in blocks:
        print(f"BLOCKED: {block.describe()}")
        print(
            f"  dialog 0x{block.dialog.handle:08X} "
            f"{block.dialog.class_name}  "
            f"holds 0x{block.blocked.handle:08X} {block.blocked.class_name}"
        )
    for item in unexplained:
        print(
            f"BLOCKED: 0x{item.blocked.handle:08X} "
            f"{item.blocked.class_name} "
            f"{item.blocked.text!r} is disabled, and no visible dialog "
            "accounts for it"
        )
        print(
            "  a dialog may be off-screen, on another desktop, or owned by "
            "a thread that has stopped pumping"
        )
    return 5


def cmd_restore(pid: int) -> int:
    # Imported here, like every other backend use in this module, so the CLI
    # stays importable on a host with no Windows backend.
    from .backends import current
    winapi = current().winapi
    from .backends import current
    restore_process = current().restore_process

    result = restore_process(pid)
    if not result.restored:
        print(f"nothing to restore: pid {pid} has no minimized windows")
        return 0

    print(f"un-minimized {len(result.restored)} window(s): "
          + ", ".join(f"0x{h:08X}" for h in result.restored))
    if result.newly_visible:
        for hwnd in result.newly_visible:
            left, top, right, bottom = winapi.window_rect(hwnd)
            print(f"  now on screen: 0x{hwnd:08X}  {winapi.class_name(hwnd)}  "
                  f"({left}, {top}, {right}, {bottom})")
    else:
        # Worth saying plainly rather than reporting success: the owner came
        # back but the application did not re-show a form, so there may
        # still be nothing to read.
        print("  no additional window became visible within the settle "
              "timeout")

    # Reported every run, not assumed. This command exists precisely because
    # the obvious implementation of it steals focus.
    if result.took_foreground:
        print(f"  WARNING: foreground changed "
              f"(0x{result.foreground_before:08X} -> "
              f"0x{result.foreground_after:08X})")
    else:
        print("  foreground unchanged")
    return 0


#: Keys attach and the tools consume: policy and measurement a person curates.
CURATED_PROFILE_KEYS = {
    "matched_profile", "denylist", "input_sensitivity", "busy_indicator",
    "safe_controls", "grid_strategy", "grid_evidence", "actuation_map", "focus_behavior",
    "posted_click_only", "hover_before_click", "notes", "text_is_label",
    "menus_by_keyboard", "insert_first",
}
RETIRED_PROFILE_KEYS = {
    "environment_allowlist": "no longer read: which targets may be driven is "
                             "decided at attach, by the person (R1, R1a)",
}


def cmd_check_profile(profile: str, operator_dir: str | None = None) -> int:
    """Load a profile the way attach does, and print what it holds."""
    import json as _json
    from pathlib import Path

    from .model.result import GhostdriverError
    from .operator import profile_location
    from .session import Profile

    if operator_dir:
        os.environ[ENV_VAR] = operator_dir
    location = Path(profile_location(profile))
    try:
        loaded = Profile.load(location)
    except GhostdriverError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 2
    document = _json.loads(location.read_text(encoding="utf-8"))
    print(f"profile         : {location}")
    print(f"matched_profile : {loaded.matched_profile}")
    print(f"denylist        : {len(loaded.denylist)} name(s), {len(loaded.deny_regions)} place(s)")
    for name in loaded.denylist:
        print(f"  name   {name}")
    for place in loaded.deny_regions:
        r = place["region"]
        print(f"  place  within {place['within']!r} at ({r['left']},{r['top']})-({r['right']},{r['bottom']})"
              + (f" -- {place['note']}" if place.get("note") else ""))
    print(f"sensitivity     : {len(loaded.sensitivity.notes)} note(s)")
    busy = loaded.busy_indicator
    if not busy:
        print("busy_indicator  : none (actuation results will not say still_arriving; "
              "wait_idle waits for the surface to hold still, weaker evidence)")
    elif busy.get("locator"):
        print(f"busy_indicator  : locator {busy['locator']!r}")
    else:
        r = busy.get("region") or {}
        print(f"busy_indicator  : region ({r.get('left')},{r.get('top')})-({r.get('right')},{r.get('bottom')}) ink_above {busy.get('ink_above', 0.02)}")
    print(f"safe_controls   : {len(loaded.safe_controls)}")
    # The class-level hints (D#122, D#133, D#141, D#189, D#207, D#137): said
    # here, so a profile's author can see the tool read what they declared.
    for label, patterns in (("posted_only     ", loaded.posted_click_only),
                            ("hover_first     ", loaded.hover_before_click),
                            ("insert_first    ", loaded.insert_first),
                            ("text_is_label   ", loaded.text_is_label)):
        if patterns:
            print(f"{label}: {', '.join(patterns)}")
    if loaded.menus_by_keyboard:
        print("menus           : chosen by the menu's keyboard route first")
    if loaded.notes:
        print(f"notes           : {len(loaded.notes)} class(es): {', '.join(loaded.notes)}")
    from .probe.profile import ProfileDocument

    # The probe writes evidence keys (Phase1Profile.OBSERVED) the tools do not
    # read but a re-probe preserves; those are informational, not mistakes.
    evidence = set(ProfileDocument.OBSERVED) | {"_comment"}
    known = CURATED_PROFILE_KEYS | evidence
    kept = [k for k in document if k in ProfileDocument.OBSERVED]
    if kept:
        print(f"probe evidence  : {len(kept)} key(s) the probe wrote, kept but not read")
    for key in document:
        if key in RETIRED_PROFILE_KEYS:
            print(f"warning: {key} is {RETIRED_PROFILE_KEYS[key]}")
        elif key not in known:
            print(f"warning: unknown key {key!r}; not read, and not something a "
                  "probe writes -- a typo?")
    return 0


def cmd_trace(tail: int, session: str | None, all_files: bool,
              operator_dir: str | None = None) -> int:
    """Print recent tool calls from the trace, one line each."""
    from .trace import describe, read

    try:
        folder = OperatorDir.resolve(operator_dir)
    except OperatorDirError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    files = sorted((folder.root / "logs").glob("ghostdriver-*.jsonl"),
                   key=lambda f: f.stat().st_mtime)
    if not files:
        print(f"no trace files under {folder.root / 'logs'} (is {ENV_VAR} set for the server?)")
        return 0
    chosen = files if all_files else files[-1:]
    events: list[dict] = []
    for f in chosen:
        events.extend(read(f, session_id=session))
    events.sort(key=lambda e: e.get("at", 0))
    for event in events[-tail:]:
        print(describe(event))
    print(f"-- {len(events[-tail:])} of {len(events)} call(s) from {', '.join(f.name for f in chosen)}")
    return 0


def cmd_list_workflows(operator_dir: str | None = None) -> int:
    try:
        folder = OperatorDir.resolve(operator_dir)
    except OperatorDirError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    names = folder.list_workflows()
    if not names:
        print(f"no workflows in {folder.workflows}")
        return 0
    for name in names:
        print(name)
    return 0


def cmd_run_workflow(name: str, pid: int, operator_dir: str | None = None) -> int:
    """Run a workflow, print the verdict, write the report; exit 0 only on pass."""
    import time

    from .session import SessionManager
    from .tools import Toolbox
    from .workflow import Workflow, WorkflowError, run_workflow

    try:
        folder = OperatorDir.resolve(operator_dir)
        workflow = Workflow.load(folder.workflow_path(name))
    except (OperatorDirError, WorkflowError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    from .backends import current
    InterferenceWatch = current().InterferenceWatch

    profile_path = (str(folder.profile_path(workflow.profile))
                    if workflow.profile else None)
    report = run_workflow(
        Toolbox(SessionManager()), workflow, pid=pid,
        watch=InterferenceWatch(pid, family=lambda: [pid, *_descendants(pid)]),
        profile_path=profile_path,
    )
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(report.started_at))
    written = folder.write_report(workflow.name, stamp, report.to_dict())

    print(f"{workflow.name}: {report.verdict}"
          f" ({sum(1 for s in report.steps if s.ok)}/{len(workflow.steps)} steps)")
    for step in report.steps:
        mark = "ok  " if step.ok else "FAIL"
        print(f"  {mark} {step.index} {step.tool} {step.elapsed_ms}ms"
              + (f"  -- {step.note}" if step.note else ""))
        for failure in step.failures:
            print(f"       {failure}")
    if report.error:
        print(f"  error: {report.error}")
    if report.interference:
        kinds = sorted({e["kind"] for e in report.interference})
        print(f"  interference: {len(report.interference)} event(s): {', '.join(kinds)}")
    print(f"  report: {written}")
    return 0 if report.passed else 1


def _use_utf8(stream) -> None:
    """Force UTF-8 on an output stream, tolerating streams that cannot.

    Windows hands a console-codepage encoder to stdout. Under the common
    OEM codepage 437 the em dash in a collapsed-run marker raises
    UnicodeEncodeError and takes the whole command down; under cp1252 it
    survives but emits cp1252 bytes, so a client decoding this output as
    UTF-8 -- which any MCP client will -- gets mojibake. The encoding of
    this tool's output is a property of the tool, not of whichever console
    it happens to be attached to.
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="backslashreplace")
    except (OSError, ValueError):
        # A detached or otherwise unreconfigurable stream. Not worth
        # failing the command over.
        pass


def main(argv: list[str] | None = None) -> int:
    """Every command, with the one failure they all share handled once.

    A platform with no backend refuses at the first contract call, and that
    refusal is careful: it names what is missing and where to read about it.
    Letting it escape turned every command into a stack trace on Linux, which
    is the opposite of what `test_unknown_pid_reports_error_not_traceback`
    asks for -- and that test could not catch this, because it is Windows-only
    and the refusal only fires where there is no backend.

    Caught here rather than in each command: there are twelve of them and the
    failure is the platform's, not any one command's.
    """
    from .backends import UnsupportedPlatform

    try:
        return _dispatch(argv)
    except UnsupportedPlatform as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _dispatch(argv: list[str] | None = None) -> int:
    _use_utf8(sys.stdout)
    _use_utf8(sys.stderr)
    args = build_parser().parse_args(argv)
    if not args.command:
        print("error: a subcommand is required", file=sys.stderr)
        return 2
    if args.command == "list-targets":
        return cmd_list_targets()
    if args.command == "describe":
        return cmd_describe(
            args.pid, args.depth, args.max_nodes, args.all,
            args.collapse_threshold, args.all_windows,
        )
    if args.command == "find":
        return cmd_find(args.pid, args.locator, args.all_windows)
    if args.command == "read":
        return cmd_read(args.pid, args.locator, args.all_windows)
    if args.command == "probe":
        return cmd_probe(args.pid, args.out)
    if args.command == "restore":
        return cmd_restore(args.pid)
    if args.command == "modals":
        return cmd_modals(args.pid)
    if args.command == "surfaces":
        return cmd_surfaces(
            args.pid, args.all, args.changed_from, args.all_windows
        )
    if args.command == "list-workflows":
        return cmd_list_workflows(getattr(args, "operator_dir", None))
    if args.command == "check-profile":
        return cmd_check_profile(args.profile, args.operator_dir)
    if args.command == "trace":
        return cmd_trace(args.tail, args.session, args.all_files, args.operator_dir)
    if args.command == "run-workflow":
        return cmd_run_workflow(args.name, args.pid, args.operator_dir)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


def _descendants(pid: int) -> list[int]:
    """The processes the target spawned, through the backend (R5)."""
    from .backends import current

    try:
        return list(current().descendants(pid))
    except Exception:
        return []
