"""Bring a minimized target back on screen without taking the foreground.

This is the only part of the tool that changes what the user sees, and it
runs only when the operator asks for it by name. Observation --
`describe`, `find`, `read`, `probe` -- never reaches this module.

The whole design rests on one observation about how applications minimize.
A toolkit that minimizes to a taskbar proxy (the VCL/Delphi pattern, and
the one a Profile L1 target exhibits) does two things at once: it minimizes
a small owner window that stands for the application, and it *hides* the
real forms. Only the application knows which of its many hidden windows
were on screen at the time -- on a real target, nine hidden windows were
owned by the minimized proxy, of which exactly one belonged on screen and
the rest were dialogs and pooled forms it deliberately keeps hidden.

So this module does not try to work that out. It un-minimizes the owner and
stops there. The application's own restore path re-shows exactly the forms
it hid, because it is the only party that knows. Guessing would put
dialogs on the user's screen that the application had every intention of
keeping hidden.
"""

import time

from ...model.restore import RestoreResult
from . import winapi
from .enumerate import top_level_windows

#: Re-exported, not re-defined. The type moved to the neutral model so the
#: Linux backend could name what it returns (D#40a's move, for `ProcessFacts`);
#: this keeps `from .restore import RestoreResult` working for everything
#: that already imported it from here.
__all__ = ["RestoreResult", "restore_process"]


def _visible_top_level(pid: int) -> tuple[int, ...]:
    """Top-level windows of `pid` carrying WS_VISIBLE themselves.

    The style bit rather than IsWindowVisible: a form owned by a minimized
    proxy is hidden outright, and reading the whole ancestor chain would
    conflate that with a form the application is merely keeping back.
    """
    return tuple(h for h in top_level_windows(pid) if winapi.is_visible_style(h))


#: How long to wait for the target to re-show its own forms. The
#: application does that on its own thread in response to being
#: un-minimized, so it has not happened yet when ShowWindow returns; reading
#: the visible set immediately would report the restore as having done
#: nothing.
SETTLE_TIMEOUT = 2.0

#: The system command a taskbar click sends to a minimized window.
WM_SYSCOMMAND = 0x0112
SC_RESTORE = 0xF120


def restore_process(pid: int, settle_timeout: float = SETTLE_TIMEOUT) -> RestoreResult:
    """Un-minimize every minimized top-level window of `pid`.

    Returns without acting when nothing is minimized, so calling this
    before a read is safe and idempotent.

    **Two requests, the second only when the first brought nothing back
    (#234).** The first is the no-activate show this module was built on.
    A classic Delphi application does not answer it: its forms come back
    through the toolkit's own restore, which runs on the system command a
    taskbar click sends, not on the window being shown -- so a restore
    reported "none came back" until the operator clicked the taskbar. The
    second request is that command, posted to the windows that were
    minimized. It may take the foreground, as a taskbar click does; the
    result says whether it did.
    """
    foreground_before = winapi.foreground_window()
    visible_before = _visible_top_level(pid)

    minimized = tuple(h for h in top_level_windows(pid) if winapi.is_minimized(h))
    for hwnd in minimized:
        winapi.show_no_activate(hwnd)

    visible_after = _settle(pid, visible_before, settle_timeout) if minimized else visible_before
    route = ""
    if minimized and not set(visible_after) - set(visible_before):
        route = "restore_command"
        for hwnd in minimized:
            winapi.user32.PostMessageW(hwnd, WM_SYSCOMMAND, SC_RESTORE, 0)
        visible_after = _settle(pid, visible_before, settle_timeout)

    return RestoreResult(
        restored=minimized,
        visible_before=visible_before,
        visible_after=visible_after,
        foreground_before=foreground_before,
        foreground_after=winapi.foreground_window(),
        route=route,
    )


def _settle(pid: int, visible_before: tuple[int, ...], timeout: float) -> tuple[int, ...]:
    """The visible set once something new appears, or at the deadline. The
    application re-shows its forms on its own thread, after the request
    returns, so an immediate read would report nothing."""
    deadline = time.monotonic() + timeout
    while True:
        visible = _visible_top_level(pid)
        if set(visible) - set(visible_before) or time.monotonic() >= deadline:
            return visible
        time.sleep(0.05)
