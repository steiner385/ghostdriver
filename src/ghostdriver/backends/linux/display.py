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


def windows_of(pid: int) -> list[int]:
    """Every managed top-level belonging to `pid`, in client-list order.

    The counterpart of Win32 `top_level_windows`, and deliberately *not*
    routed through AT-SPI: a modal is a window-manager fact, and the
    accessibility tree does not carry one (D#12).
    """
    return [x for x in client_windows() if window_pid(x) == pid]


def window_name(xid: int) -> str:
    """`_NET_WM_NAME`, falling back to `WM_NAME`.

    The EWMH property is UTF-8 and the ICCCM one is Latin-1, and a GTK
    application sets both. Preferring the first is what keeps a non-ASCII
    title readable.
    """
    for prop in ("_NET_WM_NAME", "WM_NAME"):
        value = _prop(_display().create_resource_object("window", xid), prop)
        if value:
            with contextlib.suppress(Exception):
                if isinstance(value, bytes):
                    return value.decode("utf-8", "replace")
                return str(value)
    return ""


def window_class(xid: int) -> str:
    """The application's class, from `WM_CLASS`.

    Two NUL-terminated strings -- the instance name, then the class name --
    and the second is the one that identifies the application.
    """
    value = _prop(_display().create_resource_object("window", xid), "WM_CLASS")
    if not value:
        return ""
    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
    parts = [p for p in text.split("\x00") if p]
    return parts[-1] if parts else ""


def is_modal(xid: int) -> bool:
    """Whether the window declares itself modal.

    This is the whole of the Linux modality signal. Nothing goes disabled --
    the owner keeps `SENSITIVE` for the modal's entire life -- so a driver
    that does not read this cannot tell a held application from a working
    one (D#12).
    """
    with contextlib.suppress(Exception):
        window = _display().create_resource_object("window", xid)
        states = _prop(window, "_NET_WM_STATE") or []
        return _atom("_NET_WM_STATE_MODAL") in list(states)
    return False


def transient_for(xid: int) -> int:
    """The window this one is transient for, or 0.

    `WM_TRANSIENT_FOR` is what a modal names its owner with, and it maps
    straight onto the `owner` field `TopLevel` already carries -- so on this
    platform ownership is *stated* rather than derived, which is a better
    position than Windows (D#12).
    """
    with contextlib.suppress(Exception):
        window = _display().create_resource_object("window", xid)
        value = _prop(window, "WM_TRANSIENT_FOR")
        if value:
            return int(value[0])
    return 0


def geometry(xid: int) -> tuple[int, int, int, int]:
    """The window's size, as `(0, 0, width, height)`.

    Size only, and the zeros are deliberate. AT-SPI reports a top-level
    frame at the origin under GTK4/X11 -- measured 0,0 for both the main
    window and a modal that X placed at (259, 275) -- so a position taken
    from one layer cannot be compared with a position from the other. Size
    is the part both agree on, exactly, and it is the part this backend
    uses to tell two frames of one process apart.
    """
    with contextlib.suppress(Exception):
        got = _display().create_resource_object("window", xid).get_geometry()
        return (0, 0, got.width, got.height)
    return (0, 0, 0, 0)


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


def activate(xid: int) -> None:
    """Un-hide a window, which also focuses it. There is no other version.

    `_NET_ACTIVE_WINDOW`, because D#14 measured that it is the only route
    that works: a bare `XMapWindow` leaves `_NET_WM_STATE_HIDDEN` in place
    and does nothing at all -- not half a restore, nothing -- while an
    activation restores and focuses in the same motion.

    So this is deliberately not called `restore`. Naming it for the
    un-hiding half would hide the foreground change inside it, and on this
    window manager the foreground change is not separable (D#14). The only
    caller is `restore_process`, which exists to hand the window back to the
    person and is the one place a focus change is legitimate (D4).

    Source indication 2 -- "a pager" -- rather than 1, "an application".
    A window manager applies focus-stealing prevention to applications and
    honours pagers, and this is acting on the operator's explicit request.
    """
    from Xlib import X

    display = _display()
    window = display.create_resource_object("window", xid)
    with contextlib.suppress(Exception):
        event = _protocol_event(
            window, _atom("_NET_ACTIVE_WINDOW"), [2, X.CurrentTime, 0, 0, 0]
        )
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
