"""Driving the minimized-isolation watchdog against a real process.

The policy in `ghostdriver.isolation` decides; this samples, captures, and
minimizes. Split that way so the deciding is testable without a desktop and
so a module about focus cannot touch focus except through these two named
calls.

Nothing here activates a window. `minimize_no_activate` puts the target away
without pulling whatever is behind it to the front, and `capture_window`
reads pixels through `PrintWindow` without bringing the target forward. A
watchdog that grabbed focus to prevent focus theft would be the disease it
treats.
"""

import threading
import time
from collections.abc import Callable
from ctypes import wintypes

from ...isolation import Action, Event, Observation, Watchdog
from ...model.window import select_main_tree
from . import winapi
from .capture import CaptureError, capture_window
from .enumerate import enumerate_process, top_level_windows


def _main_window(pid: int) -> int | None:
    tree = select_main_tree(enumerate_process(pid))
    return tree.handle if tree else None


def _family(pid) -> list[int]:
    """A pid, or the pids of a process family (target first), as a list.

    An application is a process tree (R5): a browser's file dialog lives in
    a helper process, and an escape from *that* process is the application
    escaping. Every sampler here takes either form.
    """
    return [pid] if isinstance(pid, int) else list(pid)


def _on_screen_window(pid) -> int | None:
    """A visible, non-minimized top-level window of the family, if any.

    The window the escape put in front of a person -- what the capture
    should show. Preferring an owned popup (a modal) over the shell is not
    worth the machinery; the first on-screen window is the one to photograph.
    """
    for member in _family(pid):
        for hwnd in top_level_windows(member):
            if winapi.user32.IsWindowVisible(wintypes.HWND(hwnd)) and \
                    not winapi.is_minimized(hwnd):
                return hwnd
    return None


def sample(pid, now: Callable[[], float]) -> Observation:
    """One read of whether the target is on screen, and holding the front.

    On-screen scans every top-level window of the process, not just the
    main one, because the escape that matters most is a modal raised as a
    *new* window while the main window stays minimized. A window counts as
    on screen when it is visible and not itself minimized.

    Foreground is a desktop fact -- is the frontmost window a non-minimized
    window of ours -- asked of the actual foreground window's pid. A modal
    the target raises is a different window of the same process, and that
    still counts as the target holding the front.
    """
    family = _family(pid)
    on_screen = _on_screen_window(family) is not None
    foreground = winapi.foreground_window()
    target_front = (
        bool(foreground)
        and winapi.window_pid(foreground) in family
        and not winapi.is_minimized(foreground)
    )
    return Observation(
        at=now(),
        target_on_screen=on_screen,
        target_is_foreground=target_front,
    )


def enforce(pid, main_hwnd: int, action: Action,
            dog: Watchdog) -> None:
    """Carry out one watchdog decision, and hand back any capture it wanted.

    A capture failure is swallowed to a note on the event rather than
    raised: the point of the action is to get the target off screen, and
    failing to photograph it first must not stop that happening.
    """
    if action is Action.NOTHING:
        return
    if action is Action.CAPTURE_THEN_MINIMIZE:
        # Photograph what is actually on screen, which is not the main
        # window: the escape that matters is usually a *modal*, a different
        # window, and the main window is minimized at this point so
        # capturing it would fail anyway. Find the window a person can see.
        target = _on_screen_window(pid) or main_hwnd
        try:
            png, _, _ = capture_window(target)
            dog.attach_capture(png)
        except CaptureError:
            pass
        if target != main_hwnd and winapi.window_pid(target) != winapi.window_pid(main_hwnd):
            # A helper process's window is not put away by minimizing its
            # parent's main window, as an owned modal is; put it away itself.
            winapi.minimize_no_activate(target)
    winapi.minimize_no_activate(main_hwnd)


def watch_once(pid, main_hwnd: int, dog: Watchdog) -> Action:
    """Sample the target once and act on what the watchdog decides.

    The main window handle is passed in, not re-resolved. Resolution picks
    the tree with the most *visible* nodes, and minimizing the target hides
    its nodes -- so re-resolving after a minimize flips to a proxy window
    that is not minimized, and the watchdog would read the target as having
    escaped on every sample forever. The handle is locked once, while the
    window is still on screen and unambiguous, and kept.

    Returns the action taken, so a caller polling this in a loop can see
    activity without draining the event log every time.
    """
    action = dog.observe(sample(pid, dog.now))
    enforce(pid, main_hwnd, action, dog)
    return action


def guard(pid: int, *, duration_s: float, interval_s: float = 0.1,
          now: Callable[[], float] = time.monotonic,
          sleep: Callable[[float], None] = time.sleep) -> list[Event]:
    """Keep the target minimized for `duration_s`, reporting what it did.

    The minimized strategy in one call, for a test or a short supervised
    run. A long-lived session would instead hold the `Watchdog` and call
    `watch_once` on its own cadence, draining events when it surfaces to the
    operator.

    The target is put away once at the start, so "keep it minimized" does
    not depend on it having been minimized already.
    """
    dog = Watchdog(now=now)
    # Locked once, before the first minimize, for the reason watch_once
    # documents: after minimizing, this window can no longer be picked out
    # by node count.
    main_hwnd = _main_window(pid)
    if main_hwnd is None:
        return []
    if not winapi.is_minimized(main_hwnd):
        winapi.minimize_no_activate(main_hwnd)

    deadline = now() + duration_s
    while now() < deadline:
        watch_once(pid, main_hwnd, dog)
        sleep(interval_s)
    return dog.drain()


class WatchError(RuntimeError):
    """The minimized strategy could not be established on this target."""


class MinimizedWatch:
    """The minimized strategy as a background thread over one session's target.

    `guard` is the strategy for a fixed duration; this is it for the life of
    a session. The main window handle is locked once at start, before the
    first minimize, for the reason `watch_once` documents: after minimizing,
    re-resolving by visible nodes can flip to a proxy window. The same locked
    handle is what the tool layer reads from, so the tools keep seeing the
    window a person was looking at, not whatever is visible now.

    The `Watchdog` is not thread-safe, so every touch of it -- the poll and
    the drain -- is under one lock. Captures ride along on events; the most
    recent one is kept so a caller can ask for it after the event has been
    reported and drained.
    """

    INTERVAL_S = 0.1

    def __init__(self, pid: int, *, now: Callable[[], float] = time.monotonic,
                 family: Callable[[], list[int]] | None = None):
        self.pid = pid
        #: The current process family (target and its descendants), asked
        #: each poll so a helper process that appears later is watched too.
        #: None means the target alone (R5, extended in D71).
        self.family = family
        self.dog = Watchdog(now=now)
        self.main_hwnd: int | None = None
        #: True when *we* minimized it -- reported at release, so the
        #: operator knows the window is minimized because of this session.
        self.put_away = False
        self.last_capture: bytes | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        main = _main_window(self.pid)
        if main is None:
            raise WatchError("the target has no window to keep minimized")
        self.main_hwnd = main
        if not winapi.is_minimized(main):
            winapi.minimize_no_activate(main)
            self.put_away = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"minimized-watch-{self.pid}")
        self._thread.start()

    def _run(self) -> None:
        assert self.main_hwnd is not None
        while not self._stop.is_set():
            try:
                with self._lock:
                    watch_once(self._pids(), self.main_hwnd, self.dog)
            except OSError:
                # A window that vanished between sample and act. The next
                # poll sees the world as it is; one bad poll is not news.
                pass
            self._stop.wait(self.INTERVAL_S)

    def _pids(self) -> list[int]:
        if self.family is None:
            return [self.pid]
        try:
            pids = list(self.family())
        except Exception:  # a process snapshot that failed: the target alone this poll
            return [self.pid]
        return pids if self.pid in pids else [self.pid, *pids]

    def drain(self) -> list[dict]:
        """Every event since the last drain, as data; captures kept aside."""
        with self._lock:
            events = self.dog.drain()
        for event in events:
            if event.capture_png is not None:
                self.last_capture = event.capture_png
        return [e.to_dict() for e in events]

    @property
    def suspended_reason(self) -> str:
        return self.dog.suspended_reason

    def stop(self) -> None:
        """Stop watching. The window stays minimized, deliberately.

        Measured against a plain top-level window, from a process allowed to
        set the foreground (which every process launched from the operator's
        own application is): `ShowWindow(SW_SHOWNOACTIVATE)`,
        `ShowWindowAsync`, `SetWindowPlacement` and `SetWindowPos` with
        `SWP_NOACTIVATE` all un-minimize *and activate* the window, and a
        `LockSetForegroundWindow` around the show only moves the foreground
        somewhere else instead. There is no un-minimize that leaves the
        operator's focus where it was. So this tool never un-minimizes on
        its own: the operator clicks the taskbar when they want the window,
        which costs them nothing and cannot surprise them.
        """
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
