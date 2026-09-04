"""The watches follow the process tree (D71).

R5 made consent and sessions cover a process family; the minimized-session
watchdog and the workflow interference watch still sampled the target pid
alone. A helper process's window on screen is the application escaping;
a helper taking the foreground is the target taking it.
"""

import json
import subprocess
import sys
import time

import psutil
import pytest

from ghostdriver.backends.windows.interference import InterferenceWatch
from ghostdriver.consent import ConsentStore
from ghostdriver.policy import ConsentSource
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox
from tests.conftest import on_windows

# --- the interference watch, fed a sequence ------------------------------------------

def test_a_helper_taking_the_foreground_is_the_target_taking_it():
    clock = iter(range(100))
    watch = InterferenceWatch(10, family=lambda: [10, 42], now=lambda: next(clock),
                              foreground_pid=lambda: 0, cursor=lambda: (0, 0))

    watch.observe(42, (0, 0), last_foreground=7, last_cursor=(0, 0))

    events = watch.events()
    assert len(events) == 1 and events[0]["kind"] == "foreground_taken"
    assert events[0]["pid"] == 42 and "spawned" in events[0]["detail"]


def test_moving_between_family_members_is_not_a_new_taking():
    clock = iter(range(100))
    watch = InterferenceWatch(10, family=lambda: [10, 42], now=lambda: next(clock),
                              foreground_pid=lambda: 0, cursor=lambda: (0, 0))

    watch.observe(10, (0, 0), last_foreground=42, last_cursor=(0, 0))

    assert watch.events() == []


def test_a_failing_family_snapshot_falls_back_to_the_target_alone():
    def boom():
        raise OSError("no snapshot")

    watch = InterferenceWatch(10, family=boom, foreground_pid=lambda: 0, cursor=lambda: (0, 0))

    assert watch.family_now() == [10]


# --- the watchdog, against a child process window on screen ----------------------------

def start(*args):
    proc = subprocess.Popen([sys.executable, "-u", "-m", "tests.fixtureapp", *args],
                            stdout=subprocess.PIPE, text=True)
    handles = json.loads(proc.stdout.readline())
    time.sleep(0.4)
    return proc, handles


def stop(proc, *pids):
    for pid in pids:
        try:
            psutil.Process(pid).terminate()
        except psutil.Error:
            pass
    proc.terminate()
    proc.wait(timeout=5)


@pytest.mark.slow
@on_windows
def test_a_child_process_window_on_screen_is_caught_photographed_and_put_away():
    """The parent spawns a child fixture on request, shown on screen; under the
    minimized strategy the watchdog, following the tree, treats it as the
    application escaping."""
    from ghostdriver.backends.windows import winapi
    from ghostdriver.backends.windows.enumerate import top_level_windows

    proc, handles = start("--child-onscreen")
    box = Toolbox(SessionManager(store=ConsentStore(None)))
    child_pid = None
    try:
        box.sessions.record_grant(handles["pid"], allowed=True, source=ConsentSource.ELICITED)
        attached = box.attach(handles["pid"], tier="interactive", isolation="minimized")
        assert attached["ok"], attached
        session = attached["session_id"]

        import ctypes
        from ctypes import wintypes

        from tests.fixtureapp import WM_FIXTURE_SPAWN_CHILD

        ctypes.windll.user32.PostMessageW(wintypes.HWND(handles["main"]), WM_FIXTURE_SPAWN_CHILD, 0, 0)
        child_pid = json.loads(proc.stdout.readline())["child"]
        time.sleep(1.5)  # the child's window comes up; give the watchdog polls
        result = box.modals(session)

        events = result.get("watchdog_events") or []
        assert events, f"the child's window should be an escape; got {result}"
        assert any(e.get("captured") for e in events), "and it was photographed"
        child_windows = [h for h in top_level_windows(child_pid)
                         if winapi.user32.IsWindowVisible(h)]
        assert all(winapi.is_minimized(h) for h in child_windows), "and put away"
        assert winapi.window_pid(winapi.foreground_window()) not in (handles["pid"], child_pid)
    finally:
        for sid in list(box._watches):
            box.release(sid)
        stop(proc, handles["pid"], *( [child_pid] if child_pid else [] ))
