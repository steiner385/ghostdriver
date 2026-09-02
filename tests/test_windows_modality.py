"""Modality against a real blocked target."""

import pytest

from tests.conftest import on_windows

pytestmark = on_windows


def test_the_fixture_is_genuinely_blocked(modal_target):
    """Guards the premise: modality is the owner being disabled."""
    import ctypes
    from ctypes import wintypes

    _, main, dialog = modal_target
    u = ctypes.WinDLL("user32")
    assert not u.IsWindowEnabled(wintypes.HWND(main))
    assert u.IsWindowEnabled(wintypes.HWND(dialog))
    assert u.IsWindowVisible(wintypes.HWND(dialog))


def test_the_blocking_dialog_is_found_and_named(modal_target):
    from ghostdriver.backends.windows.modality import top_level_state
    from ghostdriver.modality import find_modal_blocks

    pid, main, dialog = modal_target
    blocks, unexplained = find_modal_blocks(top_level_state(pid))

    assert [b.dialog.handle for b in blocks] == [dialog]
    assert blocks[0].blocked.handle == main
    assert blocks[0].dialog.text == "Confirm Delete Record"
    assert not unexplained


def test_ownership_is_read_from_the_live_window(modal_target):
    """Ownership is invisible to a parent/child walk: an owned window is
    top-level, so nothing in the window tree relates the two."""
    from ghostdriver.backends.windows import winapi

    _, main, dialog = modal_target
    assert winapi.owner_window(dialog) == main
    assert winapi.owner_window(main) == 0


def test_an_unblocked_target_reports_nothing(win32_target):
    """The other direction, so a passing result is not vacuous."""
    from ghostdriver.backends.windows.modality import top_level_state
    from ghostdriver.modality import find_modal_blocks, is_blocked

    state = top_level_state(win32_target)
    assert find_modal_blocks(state) == ([], [])
    assert not is_blocked(state)


def test_the_command_exits_nonzero_while_the_target_is_held(modal_target, capsys):
    """A caller that retries a click into a disabled window retries
    forever, so this is worth an exit code rather than a line of prose."""
    from ghostdriver.cli import cmd_modals

    pid, _, _ = modal_target
    assert cmd_modals(pid) == 5
    out = capsys.readouterr().out
    assert "BLOCKED" in out
    assert "Confirm Delete Record" in out


def test_the_command_exits_zero_when_nothing_is_held(win32_target, capsys):
    from ghostdriver.cli import cmd_modals

    assert cmd_modals(win32_target) == 0
    assert "not blocked" in capsys.readouterr().out


def test_surfaces_leads_with_the_block(modal_target, capsys):
    """Which mechanism drives a region is academic while the window is
    disabled: every one of them will fail."""
    from ghostdriver.cli import cmd_surfaces

    pid, _, _ = modal_target
    cmd_surfaces(pid, show_all=True, changed_from=None, all_windows=True)

    out = capsys.readouterr().out
    assert "BLOCKED" in out
    assert out.index("BLOCKED") < out.index("regions by kind")
