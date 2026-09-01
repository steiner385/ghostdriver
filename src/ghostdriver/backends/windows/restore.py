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
from dataclasses import dataclass

from . import winapi
from .enumerate import top_level_windows


@dataclass(frozen=True, slots=True)
class RestoreResult:
    """What `restore_process` did, and what it cost.

    `foreground_before`/`foreground_after` are recorded so that the
    non-interference claim is measured on every call rather than asserted
    once in a test and assumed forever after.
    """

    restored: tuple[int, ...]
    visible_before: tuple[int, ...]
    visible_after: tuple[int, ...]
    foreground_before: int
    foreground_after: int

    @property
    def took_foreground(self) -> bool:
        return self.foreground_before != self.foreground_after

    @property
    def newly_visible(self) -> tuple[int, ...]:
        before = set(self.visible_before)
        return tuple(h for h in self.visible_after if h not in before)


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


def restore_process(pid: int, settle_timeout: float = SETTLE_TIMEOUT) -> RestoreResult:
    """Un-minimize every minimized top-level window of `pid`.

    Returns without acting when nothing is minimized, so calling this
    before a read is safe and idempotent.
    """
    foreground_before = winapi.foreground_window()
    visible_before = _visible_top_level(pid)

    minimized = tuple(h for h in top_level_windows(pid) if winapi.is_minimized(h))
    for hwnd in minimized:
        winapi.show_no_activate(hwnd)

    visible_after = visible_before
    if minimized:
        deadline = time.monotonic() + settle_timeout
        while True:
            visible_after = _visible_top_level(pid)
            if set(visible_after) - set(visible_before):
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)

    return RestoreResult(
        restored=minimized,
        visible_before=visible_before,
        visible_after=visible_after,
        foreground_before=foreground_before,
        foreground_after=winapi.foreground_window(),
    )
