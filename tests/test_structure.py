"""Every module in the package is reachable from something that ships.

Twice in one session a draft module was left beside the real one --
`isolation.py` next to `isolate.py`, `desktop.py` next to
`hidden_desktop.py` -- imported by nothing, tested by nothing, and caught
only on review. This turns that review catch into a red test: a module
nobody imports is either dead or a stray, and both are worth a look.

Reachability is transitive from the entry points, over the source tree
alone. "Imported by something" is not enough: two dead modules that import
each other would vouch for one another. A module that only a test imports
is not shipped code with a purpose; it is a test helper in the wrong place,
or dead code kept alive by its own test.

The allowlist below is for code that is validated but not yet wired, with
the reason stated. It is meant to shrink; every entry is a debt this test
keeps visible rather than a permission to forget it.
"""

import ast
import re
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "src" / "ghostdriver"
PACKAGE = "ghostdriver"

#: Reached by something other than an import: console scripts, `python -m`,
#: and the packages themselves.
ENTRY_POINTS = {
    "ghostdriver",
    "ghostdriver.cli",           # [project.scripts] ghostdriver
    "ghostdriver.mcp_server",    # [project.scripts] ghostdriver-mcp, python -m
}

#: Validated by tests, unreachable from any entry point, and known to be,
#: with the reason beside each entry. Meant to be empty. Its first run
#: found the `minimized` isolation strategy unwired (D49 built it, D52
#: wired only hidden_desktop); B0 wired it and emptied the list.
KNOWN_UNWIRED: dict[str, str] = {
}


def _module_name(path: Path) -> str:
    rel = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _all_modules() -> dict[str, Path]:
    return {_module_name(p): p for p in PACKAGE_ROOT.rglob("*.py")}


def _imported_by(path: Path, this_module: str) -> set[str]:
    """Absolute module names this file imports, relative ones resolved.

    `from a.b import c` names both `a.b` and `a.b.c`, because `c` may be a
    submodule rather than an attribute; the extra candidate is harmless.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    is_package = path.name == "__init__.py"
    package = this_module if is_package else this_module.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                prefix = ".".join(base)
                target = f"{prefix}.{node.module}" if node.module else prefix
            else:
                target = node.module or ""
            found.add(target)
            for alias in node.names:
                found.add(f"{target}.{alias.name}")
    return found


def _reachable(modules: dict[str, Path]) -> set[str]:
    """Closure over imports starting from the entry points."""
    edges = {name: _imported_by(path, name) for name, path in modules.items()}
    reached: set[str] = set()
    frontier = list(ENTRY_POINTS)
    while frontier:
        name = frontier.pop()
        if name in reached:
            continue
        reached.add(name)
        # Importing a submodule imports every package above it.
        parts = name.split(".")
        frontier.extend(".".join(parts[:i]) for i in range(1, len(parts)))
        frontier.extend(edges.get(name, ()))
    return reached


def test_every_module_is_reachable_from_an_entry_point():
    modules = _all_modules()
    reached = _reachable(modules)

    orphans = sorted(m for m in modules if m not in reached and m not in KNOWN_UNWIRED)
    assert not orphans, (
        "modules no entry point reaches (a stray draft, or dead code): "
        + ", ".join(orphans)
    )


def test_the_known_unwired_list_is_still_true():
    """An entry that became reachable is a debt paid; take it off the list."""
    modules = _all_modules()
    reached = _reachable(modules)

    stale = sorted(m for m in KNOWN_UNWIRED if m in reached or m not in modules)
    assert not stale, "no longer unwired (or gone); remove from KNOWN_UNWIRED: " + ", ".join(stale)


# --- nothing target-shaped in the source tree ---------------------------------

REPO = PACKAGE_ROOT.parent.parent

#: The one profile document that may live here: it names no target.
ALLOWED_PROFILES = {REPO / "docs" / "example-profile.json"}


def test_the_source_tree_holds_no_profile_workflow_or_report():
    """Target knowledge lives in the operator directory and nowhere else.
    .gitignore already refuses profile files; this refuses them, and the
    other shapes the operator directory holds, before a commit is even
    attempted -- and it fails on a file that .gitignore would have let
    through under a different name."""
    offenders = []
    for path in REPO.rglob("*"):
        parts = {p.lower() for p in path.relative_to(REPO).parts}
        # `.github` is repository metadata -- CI workflows, issue templates --
        # not the product's target knowledge. Its `workflows` directory is
        # GitHub Actions, categorically not the saved-automation kind this
        # guard keeps out of the tree, so the whole subtree is out of scope.
        if parts & {".git", ".github", ".venv", "venv", "__pycache__", ".pytest_cache"}:
            continue
        name = path.name.lower()
        if path.is_file() and "profile" in name and name.endswith(".json") \
                and path not in ALLOWED_PROFILES:
            offenders.append(path)
        if path.is_dir() and name in {"workflows", "reports", "profiles"}:
            offenders.append(path)
    assert not offenders, (
        "target-shaped files in the source tree; they belong in the operator "
        "directory (GHOSTDRIVER_OPERATOR_DIR): "
        + ", ".join(str(p.relative_to(REPO)) for p in offenders)
    )


# --- the tool modules stay readable -------------------------------------------

TOOL_MODULE_LIMIT = 400


def test_no_tool_module_outgrows_the_limit_the_split_set():
    """A2 split a 1,767-line tools.py so a reader opens the file named for
    what they are looking at; this keeps each file that size. A module
    over the limit wants a split, not a bigger limit."""
    over = {
        p.name: sum(1 for _ in p.open(encoding="utf-8"))
        for p in (PACKAGE_ROOT / "tools").glob("*.py")
        if sum(1 for _ in p.open(encoding="utf-8")) > TOOL_MODULE_LIMIT
    }
    assert not over, f"tool modules over {TOOL_MODULE_LIMIT} lines: {over}"


# --- a test module imports on any host ----------------------------------------

TESTS = Path(__file__).resolve().parent

#: Run as subprocesses (`python -m tests.fixtureapp`, `... .fixtureapp_gtk`)
#: and never imported by the test process, so each is its platform's toolkit at
#: module scope on purpose.
IMPORT_TIME_PLATFORM_ALLOWED = {"fixtureapp.py", "fixtureapp_gtk.py",
                                "linux_atspi_probe.py",
                                "linux_timeout_probe.py",
                                "linux_tier1_probe.py",
                                "linux_reading_probe.py",
                                "linux_watch_probe.py",
                                "linux_modality_probe.py",
                                "linux_xid_probe.py"}

#: Test modules that check **platform-neutral policy** and must therefore
#: run on every platform. A gate on one of these does not skip a Windows
#: test; it leaves a neutral promise verified on one platform only, which is
#: how `test_tool_contracts.py` came to check "a released session refuses
#: every tool" nowhere but Windows (#39).
#:
#: Adding to this list is cheap. Taking something off it means deciding the
#: policy is not neutral after all, which is a decision worth writing down.
MUST_RUN_EVERYWHERE = {"test_tool_contracts.py", "test_modality.py",
                       "test_disturbance.py", "test_backends.py",
                       "test_mcp_dependency.py"}


def _module_level_gate(path) -> str | None:
    """The platform gate applied to a whole module, if there is one.

    `pytestmark = [on_windows, ...]` -- an assignment at module scope. A
    decorator on a single test is *not* this: a module may legitimately hold
    one Windows-only test beside neutral ones, and `test_backends.py` does.

    Matched by AST rather than by searching for the name, because the name
    also appears in prose explaining why a gate was removed, and in
    `test_on_windows_every_contract_name_resolves_to_something_real` -- a
    test whose subject really is the Windows backend. Both were false
    positives on the first attempt at this guard.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "pytestmark"
                   for t in node.targets):
            continue
        for name in ast.walk(node.value):
            if isinstance(name, ast.Name) and name.id in ("on_windows", "on_linux"):
                return name.id
    return None


def test_neutral_policy_tests_are_not_gated_to_one_platform():
    """A neutral promise checked on one platform is not checked.

    This is the wider half of #39. The narrow half was two guards gated on
    the very condition they existed to detect; this is the same failure at
    a different scale -- 370 of 897 test functions behind a module-level
    `on_windows`, including a file describing itself as "the contract every
    tool honours", whose refusal tests took a Win32 target purely because
    that was the fixture that existed.

    The fix those tests got is the one to copy: they open a session through
    `SessionManager` rather than the `attach` tool, so no backend is
    involved and the gate is exercised where the gate lives.
    """
    offenders = {}
    for name in sorted(MUST_RUN_EVERYWHERE):
        path = TESTS / name
        if not path.exists():
            offenders[name] = "listed here but missing"
            continue
        gate = _module_level_gate(path)
        if gate:
            offenders[name] = f"whole module gated with {gate}"
    assert not offenders, (
        "these check platform-neutral policy and must run everywhere, but "
        "are gated to one platform: " + ", ".join(
            f"{n} ({why})" for n, why in sorted(offenders.items()))
    )


#: Modules that exist on one platform only. `ctypes.WinDLL` raises
#: AttributeError off Windows; `gi` and `pyatspi` are simply absent off a
#: Linux desktop. Both directions are named so the guard is symmetric -- the
#: Linux backend must not do to Windows what four modules did to Linux (D74).
PLATFORM_MODULES = {"gi", "pyatspi", "Xlib"}


def _module_scope(tree):
    """Statements that run at import: the module body, and the bodies of the
    `if`/`try` it nests -- but not a function or class body, which does not
    run until something calls it."""
    stack, out = list(tree.body), []
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        out.append(node)
        for field in ("body", "orelse", "finalbody", "handlers"):
            stack.extend(getattr(node, field, []) or [])
    return out


def _binds_a_platform(node):
    """A platform binding: `ctypes.WinDLL(...)`/`ctypes.windll`, or an import of
    a backend subpackage -- which binds one for you, transitively."""
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr in {"WinDLL", "windll"}:
            return "ctypes." + child.attr
        if isinstance(child, ast.ImportFrom):
            module = child.module or ""
            if module.startswith(f"{PACKAGE}.backends."):
                return module
            if module.split(".")[0] in PLATFORM_MODULES:
                return module
        if isinstance(child, ast.Import):
            for alias in child.names:
                if alias.name.startswith(f"{PACKAGE}.backends."):
                    return alias.name
                if alias.name.split(".")[0] in PLATFORM_MODULES:
                    return alias.name
    return None


def test_no_test_module_binds_a_platform_at_import_time():
    """`pytestmark = on_windows` skips the *tests*; it does not stop the
    *module* running. A module that binds Win32 at import raises during
    collection -- and a collection error is not a skip, it aborts the whole
    run, so four such modules took the entire suite down on Linux and hid
    the ~470 tests that had nothing to do with Windows.

    The rule was already the practice -- conftest keeps its Win32 in strings
    run only in the subprocess, and the windows test modules call WinDLL
    inside their functions -- but it lived in two comments, so nothing
    failed when four modules did it the other way. D60's lesson: a promise
    that lives only in prose is one a later change breaks without noticing.

    Stated per-platform rather than per-symptom, so the Linux backend cannot
    do the mirror image of this to Windows.
    """
    offenders = {}
    for path in sorted(TESTS.glob("*.py")):
        if path.name in IMPORT_TIME_PLATFORM_ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in _module_scope(tree):
            found = _binds_a_platform(node)
            if found:
                offenders.setdefault(path.name, (found, node.lineno))
                break
    assert not offenders, (
        "test modules bind a platform at import time, which is a collection "
        "error rather than a skip and takes the whole run down on another "
        "host. Move the binding inside the function that uses it, the way "
        "tests/test_windows_actuate.py does: "
        + ", ".join(f"{n} ({w} at line {ln})" for n, (w, ln) in sorted(offenders.items()))
    )


# --- the decision log numbers each entry once ---------------------------------

DECISIONS = REPO / "docs" / "DECISIONS.md"

#: The frozen series. `### D73.` / `### R5.`, numbered from a counter, kept
#: because several hundred references across the source tree point at them.
_SEQUENTIAL = re.compile(r"^### ([DR])(\d+)\.", re.M)

#: The live series. `### D#34.` -- numbered from the issue the decision came
#: out of, so GitHub allocates it and two branches cannot pick the same one.
#: A trailing letter (`D#34a`) splits one issue that produced two decisions,
#: and is part of the identifier: D#34a and D#34b are different, and a bare
#: D#34 twice is still a duplicate.
_BY_ISSUE = re.compile(r"^### D#(\d+[a-z]?)\.", re.M)

#: Where the counter stopped. Nothing may extend it.
LAST_SEQUENTIAL_DECISION = 77


def _text():
    return DECISIONS.read_text(encoding="utf-8")


def _series(kind):
    return [int(n) for k, n in _SEQUENTIAL.findall(_text()) if k == kind]


def test_no_new_decision_extends_the_frozen_counter():
    """The rule that makes the change stick, rather than relying on everyone
    remembering it.

    A hand-kept counter cannot be made safe: every branch reads the highest
    number before any branch writes one, so two sessions that start together
    pick the same number and both are right. It happened three times in a
    day. Issue numbers are handed out by GitHub once, so the question does
    not arise -- but only if new entries actually use them, which is what
    this checks.
    """
    over = sorted(n for n in _series("D") if n > LAST_SEQUENTIAL_DECISION)
    assert not over, (
        "docs/DECISIONS.md has "
        + ", ".join(f"D{n}" for n in over)
        + f", but the sequential series is frozen at D{LAST_SEQUENTIAL_DECISION}. "
        "Number a new decision from the issue it came out of -- `### D#34.` "
        "for issue 34 -- and open an issue for it first if it has none."
    )


def test_no_issue_numbered_decision_is_used_twice():
    """One issue, one decision. If an issue genuinely produced two, suffix
    them (`D#34a`, `D#34b`) rather than heading two entries the same, or a
    reader following a reference lands on whichever comes first."""
    numbers = _BY_ISSUE.findall(_text())
    seen, repeated = set(), []
    for n in numbers:
        (repeated.append(n) if n in seen else None)
        seen.add(n)
    assert not repeated, (
        "docs/DECISIONS.md heads two entries D#"
        + ", D#".join(sorted(set(repeated)))
        + ". One issue, one decision -- suffix them D#Na / D#Nb if an issue "
        "really did produce two."
    )


@pytest.mark.parametrize("kind", ["D", "R"])
def test_the_frozen_series_gives_each_number_to_one_entry(kind):
    """Still worth checking, because the frozen entries are what the source
    tree's several hundred references point at. A duplicate there sends a
    reader to the wrong decision."""
    numbers = _series(kind)
    seen, repeated = set(), []
    for n in numbers:
        (repeated.append(n) if n in seen else None)
        seen.add(n)
    assert not repeated, (
        f"{kind}{repeated[0]} heads two entries in docs/DECISIONS.md. These are "
        f"frozen and referenced from source; renumbering one breaks those "
        f"references, so the fix is to merge or retitle the duplicate. "
        "All: " + ", ".join(f"{kind}{n}" for n in repeated)
    )


def test_numbers_may_skip_and_may_arrive_out_of_order():
    """Deliberately asserting the *absence* of two rules, because both look
    like obvious guards and both are wrong.

    Issue numbers skip by nature -- issue 8 and issue 34 with nothing
    between -- and arrive in whatever order the work finished, so neither
    contiguity nor sorting can be required. A contiguity check was written
    and removed the same afternoon: while another branch held a number, this
    checkout was legitimately missing it and the check false-failed.

    The frozen series is not sorted either: the 2026-09-02 revision section
    holds D42-D48 after the iteration that reached D73.
    """
    assert _BY_ISSUE.findall(_text()), "no issue-numbered decisions yet"
    sequential = _series("D")
    assert sequential != sorted(sequential), (
        "the frozen series is now in ascending order. Fine, but do not add a "
        "test requiring it -- see this test's docstring."
    )




# --- nothing ships a half-finished merge --------------------------------------

#: Git's markers. Written split so this file does not trip its own check.
_CONFLICT = tuple("<" * 7), tuple(">" * 7)


def test_no_tracked_file_carries_a_merge_conflict_marker():
    """`git add` does not care whether you finished resolving. Staging a file
    that still has markers and running `rebase --continue` commits them, with
    no warning -- which is exactly how a decision-log entry reached this
    branch cut in half.

    Cheap to check, and it catches the whole class: a resolution that looked
    done, a script whose replacement silently did not match, a bad merge that
    nobody re-read.
    """
    opener, closer = "".join(_CONFLICT[0]), "".join(_CONFLICT[1])
    offenders = []
    for path in REPO.rglob("*"):
        parts = {p.lower() for p in path.relative_to(REPO).parts}
        if parts & {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules"}:
            continue
        if not path.is_file() or path.suffix not in {".py", ".md", ".toml", ".json", ".cfg"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if line.startswith(opener) or line.startswith(closer):
                offenders.append(f"{path.relative_to(REPO)}:{lineno}")
                break
    assert not offenders, (
        "unresolved merge conflict markers are committed in: "
        + ", ".join(offenders)
        + " -- finish the resolution and amend, rather than leaving a file "
        "cut in half."
    )
