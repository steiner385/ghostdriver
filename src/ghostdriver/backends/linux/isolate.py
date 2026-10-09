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
from ...model.window import select_main_tree
from . import display, tree
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


def sample(pid: int, now: Callable[[], float],
           family: list[int] | None = None) -> Observation:
    """One read of whether the target is on screen, and holding the front.

    On-screen scans every managed top-level of the process family, not just
    the main one, because the escape that matters most is a modal raised as a
    *new* window while the main window stays put away.
    """
    family = family if family is not None else _family(pid)
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


def enforce(pid: int, main_xid: int, action: Action, dog: Watchdog,
            family: list[int] | None = None) -> None:
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

    for xid in _family_windows(family if family is not None else _family(pid)):
        if not display.is_hidden(xid):
            display.iconify(xid)


def watch_once(pid: int, main_xid: int, dog: Watchdog,
               family: list[int] | None = None) -> Action:
    """Sample once and act on what the watchdog decides.

    `main_xid` is passed in rather than re-resolved, for the reason the
    Windows watch gives: resolution picks the tree with the most *visible*
    nodes, and putting the target away hides its nodes -- so re-resolving
    after a minimize flips to whatever is still on screen, and the watch
    would read the target as escaped on every sample forever.
    """
    action = dog.observe(sample(pid, dog.now, family))
    enforce(pid, main_xid, action, dog, family)
    return action


class MinimizedWatch:
    """Keep a target put away, and say every time it got out.

    The guarantee is observational rather than structural (spec 7.2), which
    is the whole reason this exists: one trial of "it stayed minimized" says
    nothing about the next modal.
    """

    def __init__(self, pid: int, *,
                 now: Callable[[], float] = time.monotonic,
                 family: Callable[[], list[int]] | None = None,
                 poll_s: float = POLL_S,
                 main_xid: int | None = None) -> None:
        """The contract's shape, the one `tools/lifecycle.py` builds: the
        Windows class's `(pid, *, now, family)`. It took `(pid, main_xid)`,
        so `attach(isolation="minimized")` raised TypeError on Linux (#218).

        `main_xid` stays as a keyword for a caller that already knows the
        window -- the L6 probe does. Otherwise `start` finds it.
        """
        from . import session_type
        session_type.require_x11("the minimized watch")
        self.pid = pid
        #: The current process family, asked each poll so a helper process
        #: that appears later is watched too (R5, D71). None: descendants.
        self.family = family
        self.main_xid = main_xid
        #: The main window's *tree* handle -- what the tool layer locks its
        #: reads onto (`core._trees`). On this backend that is an AT-SPI
        #: handle, not the xid the watch itself works in.
        self.main_hwnd: int | None = None
        #: True when *this watch* put the window away, reported at release.
        self.put_away = False
        self.dog = Watchdog(now=now)
        self._poll_s = poll_s
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    #: How long to wait for the window manager to act on an iconify request.
    #: Putting a window away is a *message* here, not a call: `iconify`
    #: returns as soon as it is sent, and `_NET_WM_STATE_HIDDEN` appears
    #: whenever the window manager gets round to it. Windows' equivalent is
    #: synchronous, so nothing on that side has to wait -- and code written
    #: from the Windows shape reads the state back too early and sees the
    #: window still out. Measured failing exactly that way under load.
    SETTLE_S = 3.0

    def start(self) -> None:
        """Put the target away and confirm it went, before watching begins.

        `start` promising the state it is there to keep is the whole point:
        a caller that gets a watch back and finds the target still on screen
        has no way to tell "not yet" from "never".
        """
        if self.main_xid is None:
            self.main_xid = self._find_main_xid()
        if not display.exists(self.main_xid):
            raise WatchError(f"window {self.main_xid:#x} is gone; nothing to watch")
        if not display.is_hidden(self.main_xid):
            display.iconify(self.main_xid)
            self.put_away = True
            if not self._await_hidden():
                raise WatchError(
                    f"window {self.main_xid:#x} did not go away within "
                    f"{self.SETTLE_S:.0f}s of being asked. Iconifying is a "
                    "message to the window manager, so this means it declined "
                    "or never answered, not that the request failed to send."
                )
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _find_main_xid(self) -> int:
        """The main window, chosen as the Windows watch chooses it (by
        visible nodes), and the X window behind its frame."""
        main = select_main_tree(tree.enumerate_process(self.pid))
        if main is None:
            raise WatchError("the target has no window to keep minimized")
        self.main_hwnd = main.handle
        xid = tree.frame_xid_of(main.handle)
        if xid is None:
            raise WatchError(
                "could not find the X window behind the target's main window "
                "(its frame matched no managed window, or more than one), so "
                "there is nothing this watch could put away")
        return xid

    def _await_hidden(self) -> bool:
        assert self.main_xid is not None  # set by start() before this runs
        deadline = time.monotonic() + self.SETTLE_S
        while time.monotonic() < deadline:
            if display.is_hidden(self.main_xid):
                return True
            time.sleep(0.05)
        return display.is_hidden(self.main_xid)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def events(self) -> list[dict]:
        with self._lock:
            return [event.to_dict() for event in self.dog.events]

    def drain(self) -> list[dict]:
        """Every event since the last drain, as data (the tool layer's
        per-call `watchdog_events`)."""
        with self._lock:
            return [event.to_dict() for event in self.dog.drain()]

    @property
    def suspended_reason(self) -> str:
        return self.dog.suspended_reason

    def _pids(self) -> list[int] | None:
        if self.family is None:
            return None
        try:
            pids = list(self.family())
        except Exception:  # a failed process snapshot: the target alone this poll
            return [self.pid]
        return pids if self.pid in pids else [self.pid, *pids]

    def _run(self) -> None:
        assert self.main_xid is not None
        while not self._stop.is_set():
            if not display.exists(self.main_xid):
                break
            with self._lock:
                watch_once(self.pid, self.main_xid, self.dog, self._pids())
            self._stop.wait(self._poll_s)
