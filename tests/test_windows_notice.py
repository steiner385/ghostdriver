"""The operator notice: on screen, on top, and never in the way.

The one thing this tool ever puts on the operator's screen. It has to be
visible without being intrusive, which on Windows means: topmost, so a
full-screen application does not hide it; a tool window, so it is not in
the taskbar; and never activated -- not on show, and not on click.
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

from ghostdriver.policy import ConsentSource
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox
from tests.conftest import on_windows, user32

pytestmark = on_windows

GWL_EXSTYLE = -20
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x8, 0x80, 0x08000000


def notice_windows():
    import os

    from ghostdriver.backends.windows import winapi
    from ghostdriver.backends.windows.enumerate import top_level_windows
    from ghostdriver.backends.windows.notice import CLASS_NAME

    return [h for h in top_level_windows(os.getpid()) if winapi.class_name(h) == CLASS_NAME]


def _pid_of(hwnd):
    pid = wintypes.DWORD(0)
    user32().GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return pid.value


def exstyle(hwnd):
    return user32().GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)


def test_the_notice_is_visible_topmost_and_never_activated():
    from ghostdriver.backends.windows.notice import OperatorNotice

    before = user32().GetForegroundWindow()
    with OperatorNotice("Please sign in to the application, then leave it open.") as shown:
        assert shown.hwnd, "the window was created"
        assert user32().IsWindowVisible(wintypes.HWND(shown.hwnd))
        flags = exstyle(shown.hwnd)
        assert flags & WS_EX_TOPMOST and flags & WS_EX_TOOLWINDOW and flags & WS_EX_NOACTIVATE
        # The claim is that the *notice* did not become the foreground
        # window; the operator may switch windows of their own meanwhile,
        # and a handle comparison cannot survive that.
        after = user32().GetForegroundWindow()
        assert after != shown.hwnd, "showing it took focus"
        assert after == before or after == 0 or             _pid_of(after) != os.getpid(), "focus went to a window of ours"
        assert notice_windows() == [shown.hwnd]
    time.sleep(0.2)
    assert notice_windows() == [], "and it is gone when the wait ends"


def test_the_notice_carries_the_ask_and_says_it_will_continue_by_itself():
    from ghostdriver.backends.windows.notice import OperatorNotice

    shown = OperatorNotice("Press Ctrl and right-click the status bar.")
    assert "Ctrl and right-click" in shown.text
    assert "continues on its own" in shown.text


# --- through await_human ---------------------------------------------------------

@pytest.fixture
def app():
    proc = subprocess.Popen([sys.executable, "-m", "tests.fixtureapp"],
                            stdout=subprocess.PIPE, text=True)
    handles = json.loads(proc.stdout.readline())
    time.sleep(0.4)
    yield handles
    if handles["pid"] != proc.pid:
        try:
            psutil.Process(handles["pid"]).terminate()
        except psutil.Error:
            pass
    proc.terminate()
    proc.wait(timeout=5)


def session_on(app):
    box = Toolbox(SessionManager())
    box.sessions.record_grant(app["pid"], allowed=True, source=ConsentSource.ELICITED)
    return box, box.attach(app["pid"])["session_id"]


def test_await_human_shows_the_notice_while_it_waits_and_removes_it_after(app):
    """Waited on a condition that never comes, briefly: the notice is on
    screen during the wait and gone afterwards, whatever the outcome."""
    import threading

    box, session = session_on(app)
    seen_during: list = []

    def peek():
        time.sleep(0.5)
        seen_during.extend(notice_windows())

    watcher = threading.Thread(target=peek)
    watcher.start()
    result = box.await_human(session, "Sign in, please.",
                             until={"locator": 'class=Static text="never"'},
                             timeout_s=1.2)
    watcher.join()

    assert result["ok"] is False and result["verified"] is False
    assert len(seen_during) == 1, "the notice was on screen while waiting"
    time.sleep(0.2)
    assert notice_windows() == [], "and removed once the wait ended"


def test_the_notice_can_be_turned_off(app):
    import threading

    box, session = session_on(app)
    seen_during: list = []

    def peek():
        time.sleep(0.4)
        seen_during.extend(notice_windows())

    watcher = threading.Thread(target=peek)
    watcher.start()
    box.await_human(session, "Sign in.", until={"locator": 'class=Static text="never"'},
                    timeout_s=0.9, notice=False)
    watcher.join()

    assert seen_during == []
