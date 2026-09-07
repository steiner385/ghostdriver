"""One X connection, and the handful of facts the watches ask of it.

The watches poll -- whether the target is on screen, whether it holds the
front, where the pointer is -- and they poll often. Asking `xprop` per sample
would spawn two processes per poll, so this keeps a real connection open and
answers from it.

Every fact here was measured before it was coded:

* **Hidden, not unmapped.** A compositing window manager leaves an iconified
  window `IsViewable`, so map state does not move and `_NET_WM_STATE_HIDDEN`
  is the signal (D#13).
* **Un-hiding focuses.** There is no route that reveals a window without
  activating it, so `restore` hands over the foreground by necessity rather
  than by choice (D#14).
"""

from __future__ import annotations

import contextlib
import threading
from typing import Any

_LOCK = threading.Lock()
_DISPLAY: Any = None


def _display() -> Any:
    """The shared connection, opened once.

    Not per-call: opening an X connection costs a round trip, and a watch
    that opened one per sample would spend more time connecting than looking.
    """
    global _DISPLAY
    with _LOCK:
        if _DISPLAY is None:
            from Xlib import display

            _DISPLAY = display.Display()
        return _DISPLAY


def _atom(name: str) -> int:
    return _display().intern_atom(name)


def _prop(window: Any, name: str) -> Any:
    with contextlib.suppress(Exception):
        got = window.get_full_property(_atom(name), 0)
        if got is not None:
            return got.value
    return None


def _root() -> Any:
    return _display().screen().root


def window_pid(xid: int) -> int | None:
    """The process behind a window, from `_NET_WM_PID`."""
    with contextlib.suppress(Exception):
        value = _prop(_display().create_resource_object("window", xid), "_NET_WM_PID")
        if value:
            return int(value[0])
    return None


def is_hidden(xid: int) -> bool:
    """Whether the window manager considers this window put away.

    `_NET_WM_STATE_HIDDEN`, not map state: under a compositor an iconified
    window stays `IsViewable` and asking the Windows question answers wrongly
    (D#13).
    """
    with contextlib.suppress(Exception):
        window = _display().create_resource_object("window", xid)
        states = _prop(window, "_NET_WM_STATE") or []
        return _atom("_NET_WM_STATE_HIDDEN") in list(states)
    return False


def exists(xid: int) -> bool:
    """Whether the window is still there -- the counterpart of `IsWindow`."""
    try:
        _display().create_resource_object("window", xid).get_attributes()
        return True
    except Exception:
        return False


def client_windows() -> list[int]:
    """Every managed top-level, from `_NET_CLIENT_LIST`.

    This comes from the *window manager*, not the X server, which is why a
    bare `Xvfb` has none of it (D75) and why the nested display runs one.
    """
    return [int(x) for x in (_prop(_root(), "_NET_CLIENT_LIST") or [])]


def active_window() -> int | None:
    """The focused top-level, or None when nothing holds the front."""
    value = _prop(_root(), "_NET_ACTIVE_WINDOW")
    if not value or not int(value[0]):
        return None
    return int(value[0])


def foreground_pid() -> int:
    """The process holding the front, or 0. The shape `InterferenceWatch`
    expects, so 0 means "nothing" rather than raising."""
    xid = active_window()
    if xid is None:
        return 0
    return window_pid(xid) or 0


def cursor() -> tuple[int, int]:
    """Where the pointer is, in root coordinates."""
    with contextlib.suppress(Exception):
        pointer = _root().query_pointer()
        return (pointer.root_x, pointer.root_y)
    return (0, 0)


def iconify(xid: int) -> None:
    """Put a window away without activating it.

    A `WM_CHANGE_STATE` client message to the root, which is what ICCCM
    specifies and what `xdotool windowminimize` sends -- so this is the call
    D#13 actually measured as non-activating. Unmapping the window directly
    would go around the window manager, which then has no idea the window is
    iconic and will not report `_NET_WM_STATE_HIDDEN`.

    There is no counterpart that *un*-hides quietly: restoring is activating
    (D#14).
    """
    from Xlib import X, Xutil

    display = _display()
    window = display.create_resource_object("window", xid)
    with contextlib.suppress(Exception):
        event = _protocol_event(window, _atom("WM_CHANGE_STATE"),
                                [Xutil.IconicState, 0, 0, 0, 0])
        _root().send_event(
            event,
            event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask,
        )
        display.sync()


def _protocol_event(window: Any, message_type: int, data: list[int]) -> Any:
    from Xlib import protocol

    return protocol.event.ClientMessage(
        window=window, client_type=message_type, data=(32, data),
    )
