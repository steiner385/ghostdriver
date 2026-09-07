"""Bring a hidden target back on screen. It will also focus it.

This is the only part of the tool that changes what the person sees, and it
runs only when the operator asks for it by name. Observation -- `describe`,
`find`, `read`, `probe` -- never reaches this module.

**The Windows version's central promise does not hold here.** There,
`show_no_activate` un-minimizes without focusing, so restoring is quiet and
`took_foreground` is normally False. D#14 measured both legitimate routes on
this platform:

| route | what it asks for | hidden after | active after |
|---|---|---|---|
| `XMapWindow` (ICCCM de-iconify) | nothing else | **still hidden** | unchanged |
| `_NET_ACTIVE_WINDOW` (EWMH activate) | focus | **restored** | the restored window |

A bare map does not do half a restore; it does nothing. `_NET_WM_STATE_HIDDEN`
is window-manager-managed and a client may not set it, so those two are the
only ways to ask. Restoring and focusing are one operation, and there is no
version that is not.

That is acceptable *here specifically* and nowhere else. `restore` exists to
hand the window back to the person, and D4 permits it at `read_only` because
it is the operator's escape hatch -- the one place a focus change is what was
asked for. It is also why D55's "nothing ever un-minimizes" is a policy on
Windows and a **necessity** here: an accidental un-hide is an accidental
focus steal, with no gentler failure available (D#13, D#14).

Measured under GNOME Shell only. A window manager honouring focus-stealing
prevention could answer differently, and that is unmeasured.
"""

from __future__ import annotations

import time

from ...model.restore import RestoreResult
from . import display

#: How long to wait for the window manager to act. Iconifying and restoring
#: are *messages* to the window manager rather than calls -- the state moves
#: when it gets round to it, not when the send returns. Slice 5a found the
#: same thing from the other direction, where reading the state back
#: immediately sometimes saw a window still on screen (D#40c).
SETTLE_TIMEOUT = 2.0


def _visible_top_level(pid: int) -> tuple[int, ...]:
    """Managed top-levels of `pid` the window manager has not put away.

    `_NET_WM_STATE_HIDDEN`, not map state: a compositing window manager
    leaves an iconified window `IsViewable`, so asking the Windows question
    answers wrongly here (D#13).
    """
    return tuple(x for x in display.windows_of(pid) if not display.is_hidden(x))


def restore_process(pid: int, settle_timeout: float = SETTLE_TIMEOUT) -> RestoreResult:
    """Un-hide every hidden top-level window of `pid`, focusing the last.

    Returns without acting when nothing is hidden, so calling this before a
    read is safe and idempotent -- and, on this platform, that idempotence
    is load-bearing rather than tidy: a call that acted when it did not need
    to would take the foreground for nothing.
    """
    foreground_before = display.active_window() or 0
    visible_before = _visible_top_level(pid)

    hidden = tuple(x for x in display.windows_of(pid) if display.is_hidden(x))
    for xid in hidden:
        display.activate(xid)

    visible_after = visible_before
    if hidden:
        deadline = time.monotonic() + settle_timeout
        while True:
            visible_after = _visible_top_level(pid)
            if set(visible_after) - set(visible_before):
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)

    return RestoreResult(
        restored=hidden,
        visible_before=visible_before,
        visible_after=visible_after,
        foreground_before=foreground_before,
        foreground_after=display.active_window() or 0,
    )
