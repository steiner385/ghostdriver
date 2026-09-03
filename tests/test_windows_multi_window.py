"""Reaching windows that are not the main one.

A toolkit that puts menus, dropdowns, lookup lists and modal dialogs in
their own top-level windows leaves a single-tree caller unable to see the
control it most needs. Measured on a real target: 48% of the process's
windows sat outside the main tree, including every dialog.

The `minimized_target` fixture has exactly this shape -- an owner window
and two owned top-level forms -- so it can prove the difference without
depending on any particular application.
"""


from tests.conftest import on_windows

pytestmark = on_windows


def test_the_fixture_really_has_windows_outside_the_main_tree(minimized_target):
    """Guards the premise. Without it the rest proves nothing."""
    from ghostdriver.backends.windows.enumerate import enumerate_process
    from ghostdriver.model.window import select_main_tree

    pid, _, _, _ = minimized_target
    trees = enumerate_process(pid)
    main = select_main_tree(trees)

    assert len(trees) >= 3, "owner plus two owned forms"
    total = sum(1 for t in trees for _ in t.walk())
    assert total > sum(1 for _ in main.walk())


def test_all_windows_reaches_forms_the_main_tree_cannot(minimized_target):
    from ghostdriver.cli import _trees
    from ghostdriver.model.locator import Locator
    from ghostdriver.resolve import resolve

    pid, _, _, _ = minimized_target
    form_class = Locator(class_name="GhostdriverFormClass", visible=None)

    main_only = [
        n for t in _trees(pid, False) for n in resolve(t, form_class)
    ]
    every = [
        n for t in _trees(pid, True) for n in resolve(t, form_class)
    ]

    assert len(every) > len(main_only)
    assert len(every) == 2, "the form and the decoy are both owned top-level"


def test_find_says_what_it_did_not_search(minimized_target, capsys):
    """A bare "no matches" invites the wrong conclusion.

    The control may exist in a dialog that was never looked at, and a
    caller told only "no matches" concludes it is absent.
    """
    from ghostdriver.cli import cmd_find

    pid, _, _, _ = minimized_target
    assert cmd_find(pid, "class=GhostdriverDoesNotExist") == 1

    err = capsys.readouterr().err
    assert "--all-windows" in err


def test_the_default_stays_the_main_window(minimized_target):
    """Widening by default would let a locator match a pooled form that is
    not on screen, which is its own kind of wrong answer."""
    from ghostdriver.cli import _trees

    pid, _, _, _ = minimized_target
    assert len(_trees(pid, False)) == 1
    assert len(_trees(pid, True)) >= 3
