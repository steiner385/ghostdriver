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
from pathlib import Path

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
