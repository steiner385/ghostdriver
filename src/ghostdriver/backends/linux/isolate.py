"""Driving the minimized-isolation watchdog against a real process.

The same division as the Windows backend, and for the same reason: the policy
in `ghostdriver.isolation` decides, and this samples. `isolation.py` says so
in its own docstring -- "pure policy, fed observations" -- so a second
backend supplies a second sampler rather than a second policy. Nothing here
decides what to do about a flap; it only reports what it saw and carries out
what it was told.

What is different from Windows is only what a sample *is*:

* **On screen** is a window of the family that the window manager has not
  hidden. `_NET_WM_STATE_HIDDEN`, not map state, because a compositor leaves
  an iconified window `IsViewable` (D#13).
* **Foreground** is `_NET_ACTIVE_WINDOW`, whose pid is in the family and
  which is not itself hidden -- so a modal the target raises still counts as
  the target holding the front, exactly as on Windows.
* **Putting it back** is a `WM_CHANGE_STATE` message, measured
  non-activating (D#13). There is deliberately no un-hide: restoring is
  activating (D#14), so an accidental restore here would be an accidental
  focus steal, and D55's "nothing ever un-minimizes" is a necessity rather
  than a policy.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from ...isolation import Action, Event, Observation, Watchdog
from . import display
from .tree import descendants

#: Slower than the Windows poll. A sample here is several X round trips
#: rather than a handful of local calls, and the watchdog is looking for a
#: window flapping into view -- an event with a human-visible duration, not a
#: microsecond one.
POLL_S = 0.1


class WatchError(RuntimeError):
    """The watch could not be established, or could not continue."""


def _family(pid: int) -> list[int]:
    return descendants(pid)


def _family_windows(family: list[int]) -> list[int]:
    return [xid for xid in display.client_windows()
            if display.window_pid(xid) in family]


def sample(pid: int, now: Callable[[], float]) -> Observation:
    """One read of whether the target is on screen, and holding the front.

    On-screen scans every managed top-level of the process family, not just
    the main one, because the escape that matters most is a modal raised as a
    *new* window while the main window stays put away.
    """
    family = _family(pid)
    windows = _family_windows(family)
    on_screen = any(not display.is_hidden(xid) for xid in windows)

    active = display.active_window()
    target_front = (
        active is not None
        and display.window_pid(active) in family
        and not display.is_hidden(active)
    )
    return Observation(
        at=now(),
        target_on_screen=on_screen,
        target_is_foreground=target_front,
    )


def enforce(pid: int, main_xid: int, action: Action, dog: Watchdog) -> None:
    """Carry out what the policy decided.

    The capture happens *before* the window is put away, because the picture
    of what appeared is the product -- `isolation.py` is explicit that "the
    event is the product; re-minimizing is the housekeeping".
    """
    if action is Action.NOTHING:
        return

    if action is Action.CAPTURE_THEN_MINIMIZE:
        from .reading import CaptureError, capture_xid

        picture = None
        try:
            picture, _, _ = capture_xid(main_xid)
        except (CaptureError, OSError):
            picture = None
        if picture is not None and dog.events:
            last = dog.events[-1]
            dog.events[-1] = Event(
                kind=last.kind, at=last.at, after_quiet_s=last.after_quiet_s,
                detail=last.detail, capture_png=picture,
            )

    for xid in _family_windows(_family(pid)):
        if not display.is_hidden(xid):
            display.iconify(xid)


def watch_once(pid: int, main_xid: int, dog: Watchdog) -> Action:
    """Sample once and act on what the watchdog decides.

    `main_xid` is passed in rather than re-resolved, for the reason the
    Windows watch gives: resolution picks the tree with the most *visible*
    nodes, and putting the target away hides its nodes -- so re-resolving
    after a minimize flips to whatever is still on screen, and the watch
    would read the target as escaped on every sample forever.
    """
    action = dog.observe(sample(pid, dog.now))
    enforce(pid, main_xid, action, dog)
    return action


class MinimizedWatch:
    """Keep a target put away, and say every time it got out.

    The guarantee is observational rather than structural (spec 7.2), which
    is the whole reason this exists: one trial of "it stayed minimized" says
    nothing about the next modal.
    """

    def __init__(self, pid: int, main_xid: int, *,
                 now: Callable[[], float] = time.monotonic,
                 poll_s: float = POLL_S) -> None:
        self.pid = pid
        self.main_xid = main_xid
        self.dog = Watchdog(now=now)
        self._poll_s = poll_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not display.exists(self.main_xid):
            raise WatchError(f"window {self.main_xid:#x} is gone; nothing to watch")
        if not display.is_hidden(self.main_xid):
            display.iconify(self.main_xid)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def events(self) -> list[dict]:
        return [event.to_dict() for event in self.dog.events]

    def _run(self) -> None:
        while not self._stop.is_set():
            if not display.exists(self.main_xid):
                break
            watch_once(self.pid, self.main_xid, self.dog)
            self._stop.wait(self._poll_s)
