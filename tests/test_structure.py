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
KNOWN_UNWIRED: dict[str, str] = {}


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
        if parts & {".git", ".venv", "venv", "__pycache__", ".pytest_cache"}:
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
                                "linux_atspi_probe.py"}

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

#: `### D73.` / `### R5.` -- the log's two numbered series. D is a decision,
#: R a revision of an earlier one.
_NUMBERED = re.compile(r"^### ([DR])(\d+)\.", re.M)


def _series(kind):
    text = DECISIONS.read_text(encoding="utf-8")
    return [int(n) for k, n in _NUMBERED.findall(text) if k == kind]


@pytest.mark.parametrize("kind", ["D", "R"])
def test_the_decision_log_gives_each_number_to_one_entry(kind):
    """Two sessions on two machines both reached for D76 within the same
    minute, because the log is numbered by hand and nothing checked. One of
    them had to be renumbered after the fact, on a branch that had already
    been pushed.

    This fails on the *branch* that duplicates, before a merge is attempted,
    which is the only cheap moment to fix it: after the merge the number is
    in two commit messages, in whatever referred to it, and in anyone's
    checkout.
    """
    numbers = _series(kind)
    seen, repeated = set(), []
    for n in numbers:
        (repeated.append(n) if n in seen else None)
        seen.add(n)
    assert not repeated, (
        f"{kind}{repeated[0]} is used twice in docs/DECISIONS.md. Two sessions "
        f"probably allocated it in parallel; renumber the one that has not "
        f"merged yet -- the merged one keeps the number -- and say so in the "
        f"entry, the way D77 does. All duplicates: "
        + ", ".join(f"{kind}{n}" for n in repeated)
    )


@pytest.mark.parametrize("kind", ["D", "R"])
def test_the_decision_log_skips_no_numbers(kind):
    """A gap means an entry was renumbered or dropped and its old number never
    reused. That is worth catching for the same reason the log leaves what it
    overturned in place: the reader who goes looking for the missing number
    should find something, not a hole."""
    numbers = _series(kind)
    highest, count = max(numbers), len(set(numbers))
    missing = sorted(set(range(1, highest + 1)) - set(numbers))
    if not missing:
        return

    # One mistyped high number would otherwise report every number under it as
    # missing, burying the actual cause. Say the likely cause first.
    shown = ", ".join(f"{kind}{n}" for n in missing[:5])
    if len(missing) > 5:
        shown += f", and {len(missing) - 5} more"
    hint = (
        f"the highest is {kind}{highest} but there are only {count} entries, "
        f"so {kind}{highest} is more likely a typo than {len(missing)} lost "
        f"decisions -- check it first. "
    ) if highest > count + 1 else ""
    raise AssertionError(
        f"docs/DECISIONS.md skips {shown}. {hint}"
        f"Either restore the entry, or give the free number to the next one "
        f"rather than adding to the end."
    )


def test_the_decision_log_is_not_required_to_be_in_order():
    """Deliberately asserting the *absence* of a rule, because the obvious
    next guard would be wrong and someone will want to add it.

    The log is not sorted and must not be forced to be: the 2026-09-02
    revision section holds D42-D48 and sits *after* the iteration that
    reached D73, so file order descends on purpose. What matters is that a
    number identifies one entry, not where it sits.
    """
    numbers = _series("D")
    assert numbers != sorted(numbers), (
        "the decision log now happens to be in ascending order. That is fine, "
        "but do not add a test requiring it -- see this test's docstring."
    )
