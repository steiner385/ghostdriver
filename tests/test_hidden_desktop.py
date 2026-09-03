"""hidden_desktop against the fixture: the guarantee is structural.

Not gated behind GHOSTDRIVER_ALLOW_FOCUS_TESTS, and that is the point --
these launch a target and drive it without ever touching the operator's
desktop, so unlike the minimized tests they cannot disturb anyone. That is
the whole reason the strategy exists.
"""

import ctypes
import sys
from ctypes import wintypes

import pytest

from tests.conftest import on_windows

pytestmark = on_windows

user32 = ctypes.WinDLL("user32", use_last_error=True)


def fixture_command():
    return [sys.executable, "-u", "-m", "tests.fixtureapp", "--onscreen"]


@pytest.fixture
def desktop():
    from ghostdriver.backends.windows.hidden_desktop import HiddenDesktop

    dt = HiddenDesktop(name="ghostdriver-test")
    dt.prepare()
    try:
        yield dt
    finally:
        dt.teardown()


# --- the boundary holds both ways ----------------------------------------

def test_a_target_launched_here_is_invisible_from_the_input_desktop(desktop):
    """The structural half: a window on a non-input desktop cannot be seen
    -- or stolen to -- from the desktop the operator is using."""
    from ghostdriver.backends.windows.enumerate import top_level_windows

    fg_before = user32.GetForegroundWindow()
    pid = desktop.launch(fixture_command())

    # From this thread -- the Default desktop -- the target does not exist.
    assert top_level_windows(pid) == []
    assert user32.GetForegroundWindow() == fg_before, "foreground never moved"


def test_the_target_is_fully_visible_from_the_bound_thread(desktop):
    """The working half: everything the tool does to a target works, as long
    as it runs on the thread bound to the target's desktop."""
    from ghostdriver.backends.windows.enumerate import (enumerate_process,
                                                        top_level_windows)
    from ghostdriver.model.window import select_main_tree

    pid = desktop.launch(fixture_command())

    windows = desktop.run(lambda: top_level_windows(pid))
    nodes = desktop.run(
        lambda: sum(1 for _ in select_main_tree(enumerate_process(pid)).walk()))

    assert len(windows) > 0, "the bound thread sees the target"
    assert nodes >= 50, "and its whole tree"


def test_reading_from_the_wrong_thread_sees_nothing(desktop):
    """The rule the strategy is built around, shown as a contrast: the same
    call that works through `run` returns nothing off the bound thread."""
    from ghostdriver.backends.windows.enumerate import top_level_windows

    pid = desktop.launch(fixture_command())

    on_thread = desktop.run(lambda: len(top_level_windows(pid)))
    off_thread = len(top_level_windows(pid))

    assert on_thread > 0 and off_thread == 0


# --- actuation and capture work through the worker -----------------------

def test_a_click_registers_through_the_bound_thread(desktop):
    from ghostdriver.backends.windows.enumerate import enumerate_process
    from ghostdriver.backends.windows.input import click
    from ghostdriver.backends.windows.text import read_window_text
    from ghostdriver.model.window import select_main_tree

    pid = desktop.launch(fixture_command())

    def act_and_read():
        tree = select_main_tree(enumerate_process(pid))
        button = next(n for n in tree.walk()
                      if n.class_name == "GhostFixtureCommandButton"
                      and n.text == "Expand All")
        status = next(n for n in tree.walk()
                      if n.class_name == "Static" and "clicks=" in (n.text or ""))
        before = read_window_text(status.handle)
        click(button.handle)
        import time
        time.sleep(0.3)
        return before, read_window_text(status.handle)

    before, after = desktop.run(act_and_read)
    assert "clicks=0" in before
    assert "last=Expand All" in after, "the click landed on the hidden desktop"


def test_capture_through_the_bound_thread_is_a_real_png(desktop):
    from ghostdriver.backends.windows.capture import capture_window
    from ghostdriver.backends.windows.enumerate import enumerate_process
    from ghostdriver.model.window import select_main_tree

    pid = desktop.launch(fixture_command())

    def shoot():
        tree = select_main_tree(enumerate_process(pid))
        return capture_window(tree.handle)

    png, w, h = desktop.run(shoot)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert w > 0 and h > 0


# --- the honest limits ---------------------------------------------------

def test_attaching_to_a_running_process_is_refused(desktop):
    """A window's desktop is fixed at creation, so a target already running
    on the input desktop cannot be moved. Launch-only, and it says so."""
    from ghostdriver.backends.windows.hidden_desktop import Unsupported

    with pytest.raises(Unsupported, match="cannot adopt a running process"):
        desktop.attach(1234)


def test_teardown_leaves_no_target_behind(desktop):
    """A launched target is the strategy's to clean up; a stranded process
    on a hidden desktop is invisible and so especially easy to leak."""
    import psutil

    pid = desktop.launch(fixture_command())
    assert psutil.pid_exists(pid)

    desktop.teardown()
    import time
    time.sleep(0.5)
    # The launcher and its child are both gone.
    assert not psutil.pid_exists(pid) or not psutil.Process(pid).is_running()
