"""A session that keeps its target minimized, through the tool layer.

The `minimized` strategy was proven as a backend (D49) and then never wired
into `attach` -- found by the stray-module guard in Phase A. This proves
the wiring: attach puts the target away without taking anyone's focus, the
ordinary tools keep reading the window that was locked, a window the target
raises is caught, photographed and reported on the next result, and release
leaves the window minimized -- because, measured, every way of un-minimizing
a window activates it, and this tool never takes the operator's focus.

Fixtures are shown on-screen so "on screen" means something, and they are
non-activating, so nothing here can take the operator's focus -- the
session-long focus guard would fail the run if it did.
"""

import json
import subprocess
import sys
import time

import psutil
import pytest

from ghostdriver.policy import ConsentSource
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox
from tests.conftest import on_windows

pytestmark = [on_windows, pytest.mark.slow]
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


@pytest.fixture
def target():
    proc, handles = start()
    yield handles
    stop(proc, handles)


@pytest.fixture
def modal_target():
    """Raises its own modal 1.5s after starting -- the escape that matters.
    Late enough that attach (and the watchdog's first poll) is done first on
    a loaded machine; a modal already up when the watch starts is no escape."""
    proc, handles = start()
    yield handles
    stop(proc, handles)


@pytest.fixture
def box():
    tb = Toolbox(SessionManager())
    yield tb
    for sid in list(tb._watches):
        tb.release(sid)


def attached(box, pid, *, isolation="minimized", tier="interactive"):
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    result = box.attach(pid, tier=tier, isolation=isolation)
    assert result["ok"], result
    return result


def foreground_pid():
    from ghostdriver.backends.windows import winapi
    hwnd = winapi.foreground_window()
    return winapi.window_pid(hwnd) if hwnd else 0



def raise_modal(handles):
    """Ask the fixture to raise its modal now: after the watch is up, so the
    escape is a transition the watchdog sees, never a race with a timer."""
    import ctypes
    from ctypes import wintypes

    from tests.fixtureapp import WM_FIXTURE_RAISE_MODAL

    ctypes.windll.user32.PostMessageW(wintypes.HWND(handles["main"]), WM_FIXTURE_RAISE_MODAL, 0, 0)

def minimized(hwnd):
    from ghostdriver.backends.windows import winapi
    return winapi.is_minimized(hwnd)


def wait_for_watchdog_events(call, timeout_s=15.0):
    """Poll `call` until the watchdog has reported its escape, or the deadline
    passes (#66).

    The watch runs on its own thread: it catches the escape, captures and
    restores the window, then queues the event to ride on the *next* tool
    result. A fixed `sleep` raced that -- enough polls on a dev box, not
    always on a slower CI runner, where the single read landed before the
    event was queued. Waiting for it is not a retry that hides a flake: an
    empty result means nothing is queued yet, so it consumes nothing, and the
    first result that carries events is still the one and only report -- the
    "reported once, the next call carries nothing" contract downstream holds.
    """
    deadline = time.monotonic() + timeout_s
    result = call()
    while not result.get("watchdog_events") and time.monotonic() < deadline:
        time.sleep(0.1)
        result = call()
    return result


# --- attach ---------------------------------------------------------------

def test_attaching_minimized_puts_the_target_away_without_taking_focus(box, target):

    result = attached(box, target["pid"])
    time.sleep(0.3)

    assert result["isolation"] == "minimized"
    assert "watchdog_events" in result["note"]
    assert minimized(target["main"]), "the target was put away"
    assert foreground_pid() != target["pid"], "and it took nobody's focus"


def test_an_ordinary_session_reports_isolation_none(box, target):
    result = attached(box, target["pid"], isolation="none")

    assert result["isolation"] == "none"
    assert not minimized(target["main"])


def test_an_unknown_isolation_is_refused_by_name(box, target):
    box.sessions.record_grant(target["pid"], allowed=True,
                              source=ConsentSource.ELICITED)

    result = box.attach(target["pid"], isolation="teleport")

    assert not result["ok"]
    assert result["error"]["kind"] == "not_actionable"
    assert "minimized" in result["error"]["message"]


# --- the tools keep working on the locked window ---------------------------

def test_the_tools_read_and_act_on_the_locked_window_while_minimized(box, target):
    session = attached(box, target["pid"])["session_id"]
    time.sleep(0.3)

    described = box.describe(session)
    assert described["ok"] and described["windows"], described

    before = box.read(session, 'class=Static text="/clicks=/"')
    assert before["ok"] and before["values"][0]["text"].startswith("clicks=0")

    clicked = box.click(
        session, 'class=GhostFixtureCommandButton text="Expand All"',
        expect={"locator": 'class=Static text="/clicks=1 last=Expand All/"'})
    assert clicked["ok"], clicked
    assert clicked["verified"] == "effect"
    assert minimized(target["main"]), "and it stayed put throughout"


# --- the whole point: an escape is caught, photographed, reported -----------

def test_a_window_the_target_raises_is_caught_captured_and_reported(
        box, modal_target):
    session = attached(box, modal_target["pid"])["session_id"]

    raise_modal(modal_target)
    result = wait_for_watchdog_events(lambda: box.modals(session))

    assert result["ok"], result
    events = result.get("watchdog_events")
    assert events, f"the escape should be on the next result; got {result}"
    kinds = {e["kind"] for e in events}
    if "watchdog_suspended" in kinds:
        # The graceful-loss path: the raised window flapped past the limit,
        # so the watchdog stood down rather than fight the desktop, and only
        # reports. A valid outcome -- the same "captured or stood down, not
        # neither" contract test_windows_isolate asserts -- and the one a
        # slower machine is likelier to take, since more flaps land inside
        # the window before it can put each away.
        assert any(e.get("detail") for e in events
                   if e["kind"] == "watchdog_suspended"), "a stood-down watch says why"
    else:
        assert kinds <= {"unexpected_restore", "unexpected_foreground"}, events
        assert any(e["captured"] for e in events), "and it was photographed"
        assert minimized(modal_target["main"]), "and the target was put back"
        assert foreground_pid() != modal_target["pid"], "without taking the foreground"

    # Reported once: the next call carries nothing new.
    again = box.modals(session)
    assert "watchdog_events" not in again


def test_events_ride_on_whichever_tool_is_called_next(box, modal_target):
    """The event is the product; a caller should not have to know which
    tool to ask. `describe` reports it as readily as `modals` would."""
    session = attached(box, modal_target["pid"])["session_id"]
    raise_modal(modal_target)

    result = wait_for_watchdog_events(lambda: box.describe(session))

    assert result["ok"]
    assert result.get("watchdog_events"), result.keys()


# --- restore and release -------------------------------------------------

def test_restore_is_refused_while_the_session_keeps_the_target_minimized(
        box, target):
    session = attached(box, target["pid"])["session_id"]

    result = box.restore(session)

    assert not result["ok"]
    assert result["error"]["kind"] == "not_actionable"
    assert "release" in result["error"]["message"].lower()


def test_release_leaves_the_window_minimized_and_says_so(box, target):
    """Un-minimizing would activate it (MinimizedWatch.stop documents the
    measurement), so release leaves it and tells the operator whose
    doing the minimized state is."""
    session = attached(box, target["pid"])["session_id"]
    time.sleep(0.3)
    assert minimized(target["main"])

    result = box.release(session)
    time.sleep(0.3)

    assert result["ok"] and result["left_minimized"] is True
    assert result["minimized_by_this_session"] is True
    assert "taskbar" in result["note"]
    assert minimized(target["main"]), "still minimized"
    assert foreground_pid() != target["pid"], "and nothing came forward"


def test_release_leaves_a_target_that_was_already_minimized_alone(box, target):
    from ghostdriver.backends.windows import winapi

    winapi.minimize_no_activate(target["main"])
    time.sleep(0.3)
    session = attached(box, target["pid"])["session_id"]

    result = box.release(session)
    time.sleep(0.3)

    assert result["ok"] and result["minimized_by_this_session"] is False
    assert minimized(target["main"]), "left as found: minimized"


def test_release_reports_what_the_watchdog_saw_last(box, modal_target):
    session = attached(box, modal_target["pid"])["session_id"]
    raise_modal(modal_target)
    # The modal comes at 600ms and the watchdog polls at 100ms; on a loaded
    # machine either can be late, so wait for the event itself, bounded.
    watch = box._watches[session]
    deadline = time.monotonic() + 6.0
    while not watch.dog.events and time.monotonic() < deadline:
        time.sleep(0.1)

    result = box.release(session)

    assert result["ok"]
    assert result.get("watchdog_events"), "an escape nobody asked about yet"
