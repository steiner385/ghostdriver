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
from . import display

#: What is answered. Everything else in `winapi` refuses.
_WIRED = ("class_name", "is_visible_style", "foreground_window")


def class_name(xid: int) -> str:
    """The window's class, from `WM_CLASS`.

    The closest thing X has to a Win32 window class, and it is what
    `WM_CLASS` is for: the instance and class names an application
    registers. Elsewhere on this backend `class_name` carries the accessible
    *role* (D#40b) because the subject is an accessible; here the subject is
    an X window, and the window manager's answer is the honest one.
    """
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
