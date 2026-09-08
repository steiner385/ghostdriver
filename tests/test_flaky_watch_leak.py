"""Issue #4: the leaked-watch mechanism behind the capture/restore flakes.

Both intermittent failures are "a fresh target window got minimized
mid-test." The only thing in the suite that minimizes windows is a
MinimizedWatch, and the only way one touches an *unrelated* window is if
it is still running against a pid the OS has since reused for that fresh
window. D73 stops a watch once the window it locked onto is gone, which
closes that door. This proves it end to end, deterministically, against
a real fresh window -- so a regression of the guard fails here rather
than as a one-in-hundreds flake somewhere else.
"""

import json
import subprocess
import sys
import threading
import time

import psutil

from tests.conftest import on_windows

pytestmark = on_windows


def start():
    proc = subprocess.Popen([sys.executable, "-m", "tests.fixtureapp"],
                            stdout=subprocess.PIPE, text=True)
    handles = json.loads(proc.stdout.readline())
    time.sleep(0.4)
    return proc, handles


def stop(proc, pid):
    try:
        psutil.Process(pid).terminate()
    except psutil.Error:
        pass
    proc.terminate()
    proc.wait(timeout=5)


@on_windows
def test_a_watch_locked_to_a_dead_window_never_minimizes_a_reused_pids_window():
    from ghostdriver.backends.windows import winapi
    from ghostdriver.backends.windows.isolate import MinimizedWatch

    # A live target -- stands in for the process the OS handed the reused pid.
    live_proc, live = start()
    # A second target we kill, so its window handle is a valid-looking but
    # dead handle: what a leaked watch holds after its own process exited.
    dead_proc, dead = start()
    dead_hwnd = dead["main"]
    stop(dead_proc, dead["pid"])
    deadline = time.monotonic() + 5
    while winapi.user32.IsWindow(winapi.wintypes.HWND(dead_hwnd)) and time.monotonic() < deadline:
        time.sleep(0.05)

    try:
        assert not winapi.is_minimized(live["main"]), "the live window starts up"

        # The leak: a watch whose pid is the (reused) live pid, still holding
        # the dead process's window handle. Driven directly, bypassing start()
        # so nothing legitimately minimizes the live window first.
        watch = MinimizedWatch(live["pid"])
        watch.main_hwnd = dead_hwnd
        watch._thread = threading.Thread(target=watch._run, daemon=True)
        watch._thread.start()
        time.sleep(0.6)  # several poll intervals

        assert not watch._thread.is_alive(), (
            "the watch must stop once its locked window is gone (D73)")
        assert not winapi.is_minimized(live["main"]), (
            "the leaked watch must never minimize the reused pid's fresh window "
            "-- that is the capture/restore flake of issue #4")
    finally:
        watch.stop()
        stop(live_proc, live["pid"])


def test_the_fixture_detector_names_a_leaked_watch_on_this_pid():
    """The instrumentation the win32_target guard uses: a live watch thread
    against a given pid is found by name, so the next real occurrence is
    diagnosed rather than inferred (issue #4)."""
    from tests.conftest import _leaked_watch_for, _live_watchers

    pid = 424242
    assert _leaked_watch_for(pid) is None

    stop_flag = threading.Event()
    t = threading.Thread(target=stop_flag.wait, name=f"minimized-watch-{pid}", daemon=True)
    t.start()
    try:
        assert _leaked_watch_for(pid) == f"minimized-watch-{pid}"
        assert f"minimized-watch-{pid}" in _live_watchers()
    finally:
        stop_flag.set()
        t.join(timeout=2)

    assert _leaked_watch_for(pid) is None
