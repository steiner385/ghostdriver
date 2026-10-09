"""The contract's "raw platform API", for the few callers that need one fact.

`CONTRACT` carries `winapi` for the handful of places the neutral layer wants
a class name or a foreground handle and nothing more. The name is a Win32 one
and it is wrong here; renaming it changes a contract name Windows shares, so
it is left alone rather than smuggled into a Linux slice. Worth doing, and
worth doing as its own `env: both` change.

**This is deliberately partial.** Thirteen distinct names are reached through
`current().winapi` from the tool layer -- coordinate conversion, display
scale, foreground control -- and almost all of them belong to slice 4
(acting) and slice 6 (assessment). Wiring them here to make one tool work
would be building against measurements that have not been taken, which is
what `docs/LINUX.md` exists to prevent.

So this answers the two names `restore` needs and refuses the rest **by
name**, with the same explanation the backend gives. A caller reaching for
`display_scale` gets told it is not built yet, rather than an `AttributeError`
from three modules down.
"""

from __future__ import annotations

from typing import Any

from .. import UnsupportedPlatform
from . import display, session_type

#: What is answered. Everything else in `winapi` refuses.
_WIRED = ("class_name", "is_visible_style", "foreground_window",
          "resolve_live_window", "is_hung", "is_minimized")


def resolve_live_window(pid: int) -> int:
    """The window to drive live, if the target is the foreground *now* (D#111).

    The "operator-present live actuation" gate: a real keystroke may be sent
    only into a window of the target the operator is already looking at. So
    this returns the active window when it belongs to `pid` -- correlated
    through the tree, because a sandboxed target's windows carry no pid
    (D#101) -- and 0 otherwise, which the caller reports as "bring the window
    you want driven to the front and attach again". Enumerating first is what
    populates the pid<->window attribution the check reads.
    """
    from . import display, tree

    tree.enumerate_process(pid)
    fg = display.active_window() or 0
    return fg if fg and fg in display.windows_of(pid) else 0


def class_name(xid: int) -> str:
    """The window's class, from `WM_CLASS`.

    The closest thing X has to a Win32 window class, and it is what
    `WM_CLASS` is for: the instance and class names an application
    registers. Elsewhere on this backend `class_name` carries the accessible
    *role* (D#40b) because the subject is an accessible; here the subject is
    an X window, and the window manager's answer is the honest one.

    On a Wayland desktop there is no `WM_CLASS` to read, and `list_targets`
    asks this of every window it counts -- refusing would refuse the listing
    itself (final review, #215). An empty class is what an uncorrelated
    handle already answered on X11.
    """
    if session_type.display_server() == "wayland":
        return ""
    return display.window_class(xid)


def is_visible_style(xid: int) -> bool:
    """Whether the window manager has *not* put this window away.

    The Windows counterpart reads `WS_VISIBLE` off the window itself rather
    than `IsWindowVisible`, to tell a form hidden by its application from
    one merely behind something. The equivalent distinction here is
    `_NET_WM_STATE_HIDDEN`, and for the same reason it is not map state: a
    compositing window manager leaves an iconified window `IsViewable`
    (D#13).
    """
    return not display.is_hidden(xid)


def is_hung(handle: int) -> bool:
    """Never "hung", and that is a measurement rather than a stub.

    There is no `IsHungAppWindow` here. A frozen application is caught by
    the read deadline instead (D#9), which is why `top_level_state` reports
    `hung=False` for every window -- this gives `describe` the same answer
    rather than failing every call on Linux (found verifying #215).
    """
    return False


def is_minimized(handle: int) -> bool:
    """Whether the frame holding `handle` is put away, for `attach`'s hint.

    On X11 that is `_NET_WM_STATE_HIDDEN` on the frame's X window (D#13).
    Where no X window can be found -- an uncorrelated frame, or a Wayland
    desktop, where nothing has measured minimized state yet (W4) -- the
    answer is False, which `attach` reads as "no hint", not as a claim. It
    was refused outright, which made `attach` fail on every Linux desktop
    (final review, #215).
    """
    if session_type.display_server() == "wayland":
        return False
    from . import tree

    xid = tree.frame_xid_of(handle)
    return xid is not None and display.is_hidden(xid)


def foreground_window() -> int:
    """The focused top-level, or 0 when nothing holds the front."""
    return display.active_window() or 0


def __getattr__(name: str) -> Any:
    """Refuse an unbuilt name by name, rather than raising AttributeError.

    Errors are results that explain themselves (D10), and that applies to a
    backend's own gaps as much as to a tool's.
    """
    raise UnsupportedPlatform(
        f"winapi.{name} is not implemented on Linux yet. This shim answers "
        + ", ".join(_WIRED)
        + " -- what `restore` needs. Coordinate conversion, display scale "
        "and foreground control belong to #40 slices 4 and 6, and are not "
        "built because the measurements behind them have not been taken. "
        "docs/LINUX.md tracks what has been measured and what has not."
    )
