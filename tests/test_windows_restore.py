"""Restoring a minimized target without disturbing the desktop.

`restore` is the one command that changes what is on screen, so what it
must *not* do is as much a part of its contract as what it does.
"""

import ctypes
from ctypes import wintypes

import pytest

from tests.conftest import on_windows

pytestmark = on_windows


def _style(hwnd: int) -> int:
    u = ctypes.WinDLL("user32")
    u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.GetWindowLongW.restype = ctypes.c_long
    return u.GetWindowLongW(wintypes.HWND(hwnd), -16) & 0xFFFFFFFF


WS_VISIBLE = 0x10000000
WS_MINIMIZE = 0x20000000


def test_the_fixture_starts_minimized_with_its_form_hidden(minimized_target):
    """Guards the premise: without this state the rest proves nothing."""
    _, owner, form, decoy = minimized_target
    assert _style(owner) & WS_MINIMIZE
    assert not _style(form) & WS_VISIBLE
    assert not _style(decoy) & WS_VISIBLE


def test_restores_the_owner_and_the_application_puts_its_form_back(
    minimized_target,
):
    from ghostdriver.backends.windows.restore import restore_process

    pid, owner, form, _ = minimized_target
    result = restore_process(pid)

    assert owner in result.restored
    assert not _style(owner) & WS_MINIMIZE
    assert _style(form) & WS_VISIBLE, (
        "the application did not re-show the form it hid"
    )
    assert form in result.newly_visible


def test_leaves_hidden_windows_the_application_kept_back(minimized_target):
    """The reason restore un-minimizes the owner and nothing else.

    A real target owns many hidden windows -- dialogs, pooled forms -- and
    only the application knows which belong on screen. A restore that
    un-hid owned windows itself would surface every one of them.
    """
    from ghostdriver.backends.windows.restore import restore_process

    pid, _, _, decoy = minimized_target
    restore_process(pid)

    assert not _style(decoy) & WS_VISIBLE, (
        "restore un-hid a window the application deliberately kept hidden"
    )


def test_does_not_take_the_foreground(minimized_target):
    from ghostdriver.backends.windows.restore import restore_process

    pid, _, _, _ = minimized_target
    before = ctypes.WinDLL("user32").GetForegroundWindow()
    result = restore_process(pid)

    assert not result.took_foreground
    assert ctypes.WinDLL("user32").GetForegroundWindow() == before


def test_is_a_no_op_when_nothing_is_minimized(minimized_target):
    """Safe to call before a read without checking first."""
    from ghostdriver.backends.windows.restore import restore_process

    pid, _, _, _ = minimized_target
    restore_process(pid)
    again = restore_process(pid)

    assert again.restored == ()
    assert not again.took_foreground


def test_a_restored_target_becomes_readable(minimized_target):
    """The point of the command: a hidden tree cannot be read.

    Before restoring, the form carries no WS_VISIBLE and a visible-only
    locator finds nothing; afterwards the same locator resolves.
    """
    from ghostdriver.backends.windows.enumerate import build_tree
    from ghostdriver.backends.windows.restore import restore_process
    from ghostdriver.model.locator import Locator
    from ghostdriver.resolve import resolve

    pid, _, form, _ = minimized_target
    visible_form = Locator(class_name="GhostdriverFormClass", visible=True)

    assert resolve(build_tree(form), visible_form) == []

    restore_process(pid)
    assert len(resolve(build_tree(form), visible_form)) == 1


# --- a target that answers only the taskbar's restore command (#234) -------------

@pytest.mark.parametrize("minimized_target", [True], indirect=True)
def test_a_vcl_style_target_comes_back_on_the_restore_command(minimized_target):
    """A Delphi client re-shows its forms only on the system command a
    taskbar click sends; the no-activate show alone brought nothing back."""
    from ghostdriver.backends.windows.restore import restore_process

    pid, owner, form, decoy = minimized_target
    result = restore_process(pid)

    assert owner in result.restored
    assert form in result.newly_visible, result
    assert result.route == "restore_command"
    assert "restore command a taskbar click sends" in result.note
    assert not _style(decoy) & WS_VISIBLE, "what the application kept back stays back"


def test_an_ordinary_target_needs_no_fallback(minimized_target):
    from ghostdriver.backends.windows.restore import restore_process

    result = restore_process(minimized_target[0])

    assert result.route == "" and result.newly_visible
