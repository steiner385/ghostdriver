"""The backend boundary: one registry, one contract, no platform imports above it.

A Linux backend has exactly one seam to fill -- the contract -- and the
tool layer never names a platform. The boundary is checked mechanically,
because a boundary that lives only in convention is crossed by the first
convenient import.
"""

import ast
import sys
from pathlib import Path

import pytest

from ghostdriver.backends import CONTRACT, UnsupportedPlatform, current, load

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "src" / "ghostdriver"


def test_the_contract_names_are_unique_and_non_empty():
    assert len(CONTRACT) == len(set(CONTRACT)) and len(CONTRACT) >= 25


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows backend")
def test_on_windows_every_contract_name_resolves_to_something_real():
    backend = current()

    assert backend.platform == "win32"
    for name in CONTRACT:
        assert getattr(backend, name) is not None, name


def test_a_name_outside_the_contract_is_an_attribute_error_not_a_lookup():
    with pytest.raises(AttributeError, match="contract has no"):
        _ = load("linux").teleport
    if sys.platform == "win32":
        with pytest.raises(AttributeError, match="contract has no"):
            _ = current().teleport


def test_linux_answers_what_is_wired_and_refuses_the_rest_by_name():
    """This asserted that Linux refuses *every* contract name, which was true
    while nothing was built and became wrong the moment slice 1 landed (#40).

    Rewritten to the thing that stays true as the backend fills in: whatever
    is wired is callable, everything else refuses, and the refusal still says
    where to read about the gap. Nothing here hard-codes which names are in
    which group, so the next slice does not have to edit this test -- it only
    has to be honest in `_WIRED`.
    """
    backend = load("linux")
    assert backend.platform == "linux"

    wired, refused = [], []
    for name in CONTRACT:
        try:
            getattr(backend, name)
        except UnsupportedPlatform as exc:
            assert "docs/LINUX.md" in str(exc), name
            refused.append(name)
        else:
            wired.append(name)

    assert wired, "nothing is wired; slice 1 of #40 should have landed"
    assert refused, "everything is wired; this test and #40 are both done"
    assert set(wired).isdisjoint(refused)


def test_the_window_tree_is_the_part_that_is_wired():
    """Names the slice, so that wiring something by accident is visible."""
    backend = load("linux")
    for name in ("enumerate_process", "top_level_windows", "direct_children",
                 "process_facts", "descendants", "parent_map"):
        assert callable(getattr(backend, name)), name


def test_an_unknown_platform_is_refused_by_name():
    with pytest.raises(UnsupportedPlatform, match="darwin"):
        load("darwin")


def test_the_specification_exists_and_covers_the_contract():
    """Every contract name appears in the Linux specification's table, so a
    name added to the contract without a Linux plan is noticed."""
    spec = (PACKAGE_ROOT.parent.parent / "docs" / "LINUX.md").read_text(encoding="utf-8")

    missing = [name for name in CONTRACT if f"`{name}`" not in spec]
    assert not missing, f"contract names without a row in docs/LINUX.md: {missing}"


def test_nothing_above_the_backends_package_imports_a_platform_package():
    """The line the boundary is: `backends.windows` and `backends.linux`
    are imported by the registry and by nothing else."""
    offenders = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        if "backends" in path.relative_to(PACKAGE_ROOT).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                target = node.module
                if node.level:
                    target = "." * node.level + target
                if "backends.windows" in target or "backends.linux" in target:
                    offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "backends.windows" in alias.name or "backends.linux" in alias.name:
                        offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno}")
    assert not offenders, "platform packages imported above the boundary: " + ", ".join(offenders)
