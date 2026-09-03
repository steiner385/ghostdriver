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


def _on_screen_window(pid: int) -> int | None:
    """A visible, non-minimized top-level window of `pid`, if any.

    The window the escape put in front of a person -- what the capture
    should show. Preferring an owned popup (a modal) over the shell is not
    worth the machinery; the first on-screen window is the one to photograph.
    """
    for hwnd in top_level_windows(pid):
        if winapi.user32.IsWindowVisible(wintypes.HWND(hwnd)) and                 not winapi.is_minimized(hwnd):
            return hwnd
    return None


def sample(pid: int, now: Callable[[], float]) -> Observation:
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
    on_screen = False
    for hwnd in top_level_windows(pid):
        if winapi.user32.IsWindowVisible(wintypes.HWND(hwnd)) and                 not winapi.is_minimized(hwnd):
            on_screen = True
            break
    foreground = winapi.foreground_window()
    target_front = (
        bool(foreground)
        and winapi.window_pid(foreground) == pid
        and not winapi.is_minimized(foreground)
    )
    return Observation(
        at=now(),
        target_on_screen=on_screen,
        target_is_foreground=target_front,
    )


def enforce(pid: int, main_hwnd: int, action: Action,
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
    winapi.minimize_no_activate(main_hwnd)


def watch_once(pid: int, main_hwnd: int, dog: Watchdog) -> Action:
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
