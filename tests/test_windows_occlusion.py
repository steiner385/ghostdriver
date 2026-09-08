"""#61: find flags a window that is not clickable where its rect says.

A rect is where a window *would* paint, not whether a person can see it now.
An occluded or minimized window reports a perfectly plausible rect, and a
click posted to it may land on the glass in front -- the field report's two
blind clicks. `find` now carries `obscured` on a match whose window is
minimized or whose centre is covered by another program's window, and
nothing at all otherwise (the `actionable`-only-when-False discipline).

The real desktop is never disturbed to test this. A fixture may not raise a
covering window -- the focus guard forbids it, and the operator is at the
keyboard -- so the covered case feeds the z-order reader (`window_from_point`)
a real foreign window handle instead, leaving `class_name`/`window_pid` real
so the class and process-tree checks run against a genuine window. Minimizing
is non-activating and is done for real.
"""

import subprocess
import sys
import time

import psutil

from ghostdriver.consent import ConsentStore
from ghostdriver.policy import ConsentSource, Tier
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox
from tests.conftest import on_windows

pytestmark = on_windows

TARGET = "class=GhostdriverTestClass"


def session_for(pid):
    box = Toolbox(SessionManager(store=ConsentStore(None)))
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    return box, box.sessions.attach(pid, command_line=["win32"],
                                    tier=Tier.INTERACTIVE).session_id


def tops(pid):
    from ghostdriver.backends.windows.enumerate import top_level_windows
    return top_level_windows(pid)


def start_win32():
    """A second native window, in its own process -- a real foreign handle to
    stand in front of the target in the covered case."""
    from tests.conftest import _WIN32_APP
    proc = subprocess.Popen([sys.executable, "-c", _WIN32_APP],
                            stdout=subprocess.PIPE, text=True)
    pid = int(proc.stdout.readline().strip())
    deadline = time.time() + 10
    while time.time() < deadline and not tops(pid):
        time.sleep(0.1)
    return proc, pid


def stop_win32(proc, pid):
    try:
        psutil.Process(pid).terminate()
    except psutil.Error:
        pass
    proc.terminate()
    proc.wait(timeout=5)


def matches(box, session):
    result = box.find(session, TARGET)
    assert result["ok"] and result["elements"], result
    return result["elements"]


def test_a_minimized_window_is_flagged_and_says_why(win32_target):
    from ghostdriver.backends.windows import winapi

    box, session = session_for(win32_target)
    winapi.minimize_no_activate(tops(win32_target)[0])

    els = matches(box, session)

    assert all(e["obscured"]["state"] == "minimized" for e in els), els
    assert all("restore" in e["obscured"]["note"] for e in els)


def test_a_window_that_owns_its_centre_carries_no_flag(win32_target, monkeypatch):
    from ghostdriver.backends.windows import winapi

    box, session = session_for(win32_target)
    root = tops(win32_target)[0]
    # The window owns the pixel at its own centre: the ordinary visible case.
    monkeypatch.setattr(winapi, "window_from_point", lambda x, y: root)

    els = matches(box, session)

    assert all("obscured" not in e for e in els), els


def test_a_foreign_window_over_the_centre_is_flagged_covered(win32_target, monkeypatch):
    from ghostdriver.backends.windows import winapi

    box, session = session_for(win32_target)
    other_proc, other_pid = start_win32()
    try:
        foreign = tops(other_pid)[0]
        assert winapi.window_pid(foreign) != win32_target
        monkeypatch.setattr(winapi, "window_from_point", lambda x, y: foreign)

        els = matches(box, session)

        assert all(e["obscured"]["state"] == "covered" for e in els), els
        assert all(e["obscured"]["by"]["class"] == "GhostdriverTestClass" for e in els)
        assert all("centre" in e["obscured"]["note"] for e in els)
    finally:
        stop_win32(other_proc, other_pid)
