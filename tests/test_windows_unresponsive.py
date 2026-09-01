"""The one branch nothing else reaches: a control that does not answer.

`read_window_text` returns "" for a control that answered and has no text,
and None for one that never answered. Everything else in this suite -- and
every control on every real target measured so far -- answers, so without a
deliberately silent target this distinction is only ever asserted in the
direction that happens to work.

It is load-bearing. An unresponsive control reports empty text that is
*unknown*, not confirmed blank. A caller that collapses the two will state
that a field is empty when the target simply never replied.
"""

import pytest

from tests.conftest import on_windows

pytestmark = on_windows


def test_a_silent_control_reports_no_answer_not_empty_text(silent_target):
    from ghostdriver.backends.windows.text import read_window_text

    _, hwnd = silent_target
    assert read_window_text(hwnd, timeout_ms=200) is None


def test_the_window_is_otherwise_entirely_normal(silent_target):
    """Distinguishes "did not answer" from "is not there".

    Class and rect come from the kernel, not from the window's own thread,
    so they read back fine. Only the message-based read times out -- which
    is exactly the shape of a hung target, and why the tool must not treat
    silence as absence.
    """
    from ghostdriver.backends.windows import winapi
    from ghostdriver.backends.windows.enumerate import top_level_windows

    pid, hwnd = silent_target
    assert hwnd in top_level_windows(pid)
    assert winapi.class_name(hwnd) == "GhostdriverSilentClass"
    left, top, right, bottom = winapi.window_rect(hwnd)
    assert right > left and bottom > top


def test_the_tree_marks_the_node_unresponsive(silent_target):
    from ghostdriver.backends.windows.enumerate import build_tree

    _, hwnd = silent_target
    node = build_tree(hwnd)

    assert node.responsive is False
    assert node.text == "", "unknown text is carried as empty, flagged by responsive"


def test_read_prints_no_answer_rather_than_a_blank_line(silent_target, capsys):
    """The CLI must not render silence as an empty value.

    A blank line is indistinguishable from a control that answered with no
    text, which is the one distinction `responsive` exists to preserve.
    """
    from ghostdriver.cli import NO_ANSWER, cmd_read

    pid, _ = silent_target
    assert cmd_read(pid, "class=GhostdriverSilentClass") == 0

    printed = capsys.readouterr().out
    assert NO_ANSWER in printed


def test_a_responsive_control_is_not_flagged(win32_target):
    """The other direction, so the flag is not simply always False."""
    from ghostdriver.backends.windows.enumerate import build_tree
    from ghostdriver.backends.windows.enumerate import top_level_windows

    hwnd = top_level_windows(win32_target)[0]
    node = build_tree(hwnd)

    assert node.responsive is True
