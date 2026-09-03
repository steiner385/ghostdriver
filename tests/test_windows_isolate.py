"""The minimized watchdog against a real window.

The policy is proven in test_isolation.py; this proves the backend halves it
depends on -- sampling foreground and minimized state, minimizing without
activation, capturing before re-minimizing -- behave against an actual
process.

Two of these deliberately provoke the fixture into taking the foreground, so
they are opt-in behind GHOSTDRIVER_ALLOW_FOCUS_TESTS. Everything else in the
suite leaves the desktop alone; these cannot, because a foreground grab is
the thing under test.
"""

import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

import psutil
import pytest

from tests.conftest import on_windows

pytestmark = on_windows

focus_test = pytest.mark.skipif(
    os.environ.get("GHOSTDRIVER_ALLOW_FOCUS_TESTS") != "1",
    reason=("provokes and corrects a foreground grab, so it is opt-in: set "
            "GHOSTDRIVER_ALLOW_FOCUS_TESTS=1 to run it"),
)


def start(*args):
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp", "--onscreen", *args],
        stdout=subprocess.PIPE, text=True)
    handles = json.loads(proc.stdout.readline())
    time.sleep(0.4)
    return proc, handles


def stop(proc, handles):
    if handles["pid"] != proc.pid:
        try:
            psutil.Process(handles["pid"]).terminate()
        except psutil.Error:
            pass
    proc.terminate()
    proc.wait(timeout=5)


def cursor():
    point = wintypes.POINT()
    ctypes.WinDLL("user32").GetCursorPos(ctypes.byref(point))
    return (point.x, point.y)


# --- the backend primitives, not focus-provoking -------------------------

def test_minimize_no_activate_puts_the_window_away_without_taking_focus():
    from ghostdriver.backends.windows import winapi
    from ghostdriver.backends.windows.isolate import _main_window

    proc, handles = start()
    try:
        before = winapi.foreground_window()
        main = _main_window(handles["pid"])
        assert main and not winapi.is_minimized(main)

        winapi.minimize_no_activate(main)
        time.sleep(0.3)

        assert winapi.is_minimized(main), "it minimized"
        assert winapi.foreground_window() == before, "and took nobody's focus"
    finally:
        stop(proc, handles)


def test_sample_reports_whether_the_target_is_on_screen():
    from ghostdriver.backends.windows import winapi
    from ghostdriver.backends.windows.isolate import _main_window, sample

    proc, handles = start()
    try:
        main = _main_window(handles["pid"])
        clock = lambda: 1.0  # noqa: E731

        seen = sample(handles["pid"], clock)
        assert seen.target_on_screen is True
        assert seen.at == 1.0

        winapi.minimize_no_activate(main)
        time.sleep(0.3)
        assert sample(handles["pid"], clock).target_on_screen is False
    finally:
        stop(proc, handles)


def test_guard_on_a_quiet_target_reports_nothing():
    """A target that stays put produces no events -- silence has to mean
    silence, or the operator learns to ignore the log."""
    from ghostdriver.backends.windows.isolate import guard

    proc, handles = start()
    try:
        events = guard(handles["pid"], duration_s=1.0, interval_s=0.1)
        assert events == []
    finally:
        stop(proc, handles)


# --- the whole point: a grab is caught, captured, and undone -------------

@focus_test
def test_a_modal_raised_while_minimized_is_caught_and_captured():
    """The escape that matters, end to end: a background app raises a window
    while minimized. The watchdog should see it come on screen, photograph
    it -- section 7.2's free modal detector -- and put the target back.

    A modal, not SetForegroundWindow: measured, a background process calling
    SetForegroundWindow on its own minimized window does not un-minimize it
    (Windows restricts the call), so it never comes on screen and is not an
    escape at all. A raised window is the real thing.
    """
    from ghostdriver.backends.windows.isolate import guard

    png_magic = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
    before_cursor = cursor()
    proc, handles = start("--modal-after", "700")
    try:
        events = guard(handles["pid"], duration_s=3.0, interval_s=0.1)

        escapes = [e for e in events
                   if e.kind in ("unexpected_foreground", "unexpected_restore")]
        assert escapes, f"the modal should have been caught; saw {events}"
        captured = [e for e in escapes if e.capture_png]
        assert captured, "and at least one escape photographed before hiding"
        assert captured[0].capture_png[:8] == png_magic
        assert cursor() == before_cursor, "the driver moved no cursor"
    finally:
        stop(proc, handles)


@focus_test
def test_the_watchdog_keeps_the_main_window_minimized_and_does_not_flail():
    """The housekeeping half. A modal it cannot dismiss will keep the target
    on screen, so the watchdog must put the main window back and then lose
    gracefully rather than spinning -- capping its events, not emitting one
    per poll for three seconds."""
    from ghostdriver.backends.windows import winapi
    from ghostdriver.backends.windows.isolate import _main_window, guard

    proc, handles = start("--modal-after", "500")
    try:
        main = _main_window(handles["pid"])
        events = guard(handles["pid"], duration_s=3.0, interval_s=0.05)

        assert winapi.is_minimized(main), "the main window was put back"
        # Three seconds at 50ms is 60 polls; a sane watchdog does not turn
        # that into 60 events.
        assert len(events) < 12, f"should not flail: {len(events)} events"
        assert any(e.kind == "watchdog_suspended" for e in events) or             len([e for e in events if e.capture_png]) >= 1,             "it either captured the modal or stood down, not neither"
    finally:
        stop(proc, handles)
