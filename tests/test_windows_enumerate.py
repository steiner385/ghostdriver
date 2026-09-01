import pytest

from tests.conftest import on_windows

pytestmark = on_windows


@pytest.mark.usefixtures("tk_target")
def test_finds_top_level_window_for_pid(tk_target):
    from ghostdriver.backends.windows.enumerate import top_level_windows
    assert len(top_level_windows(tk_target)) >= 1


def test_builds_a_tree_with_children(tk_target):
    from ghostdriver.backends.windows.enumerate import (
        top_level_windows, build_tree,
    )
    tree = build_tree(top_level_windows(tk_target)[0])
    assert tree.children, "expected the Tk window to have child controls"
    assert tree.pid == tk_target


def test_tree_nodes_carry_class_and_rect(tk_target):
    from ghostdriver.backends.windows.enumerate import enumerate_process
    nodes = list(enumerate_process(tk_target)[0].walk())
    assert all(n.class_name for n in nodes)
    for n in nodes:
        left, top, right, bottom = n.rect
        assert right >= left and bottom >= top


def test_children_are_direct_not_flattened(tk_target):
    """A grandchild must hang off its parent, never off the root.

    EnumChildWindows returns every descendant flattened. Under that
    implementation the nested button becomes a direct child of the top-level
    window, ancestor chains collapse, and `within` scoping silently stops
    working. Depth alone cannot catch it; this checks placement.
    """
    from ghostdriver.backends.windows.enumerate import enumerate_process
    tree = enumerate_process(tk_target)[0]
    direct = {c.handle for c in tree.children}
    grandchildren = {
        g.handle for c in tree.children for g in c.children
    }
    assert grandchildren, "fixture must nest at least one control two levels down"
    assert not (grandchildren & direct), (
        "a grandchild appeared among the root's direct children — "
        "the walk is flattening the tree"
    )
    assert tree.depth() >= 3


def test_enumeration_is_stable_across_two_calls(tk_target):
    from ghostdriver.backends.windows.enumerate import enumerate_process
    first = [n.class_name for n in enumerate_process(tk_target)[0].walk()]
    second = [n.class_name for n in enumerate_process(tk_target)[0].walk()]
    assert first == second


def test_unknown_pid_yields_no_windows():
    from ghostdriver.backends.windows.enumerate import enumerate_process
    assert enumerate_process(999_999) == []
