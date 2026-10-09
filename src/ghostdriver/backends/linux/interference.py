"""The interference watch's Linux samplers (D#111).

The logic is neutral (`ghostdriver.interference`); this supplies the two
questions it polls -- who holds the front, where the pointer is -- from the
one X connection `display` already keeps open. It matters more here than on
Windows: the live-actuation path (D#111) arms one of these around every
action it takes on the operator's own display, so a foreground change or a
pointer move the synchronous guard misses between its checks is still seen.
"""

import time
from collections.abc import Callable

from ...interference import InterferenceWatch as _Watch
from . import display

#: How often to sample on a Wayland desktop. Each sample walks every
#: application's frames over D-Bus (`tree.active_frame`), so the X poll's
#: 50ms would be hundreds of bus calls a second; a foreground change lasts
#: far longer than this.
WAYLAND_POLL_S = 0.25


def _wayland_foreground_pid() -> int:
    """The pid holding the front on a Wayland desktop, from AT-SPI's
    `STATE_ACTIVE` (W1, D#221), or 0 when nothing does."""
    from . import tree

    active = tree.active_frame()
    return active[0] if active else 0


class InterferenceWatch(_Watch):
    def __init__(self, pid: int, *,
                 family: Callable[[], list[int]] | None = None,
                 foreground_pid: Callable[[], int] | None = None,
                 cursor: Callable[[], tuple[int, int]] | None = None,
                 now: Callable[[], float] = time.time):
        """On X11, both samplers read X, as before. On a Wayland desktop
        the foreground comes from AT-SPI and the pointer is not watched --
        there is no global pointer query (W5) -- which the watch says
        (`watches_pointer`) rather than letting silence read as stillness.
        It used to refuse there, and refused macro replay with it (#225)."""
        from . import session_type
        if session_type.display_server() == "wayland":
            super().__init__(pid, foreground_pid=foreground_pid or _wayland_foreground_pid,
                             cursor=cursor, family=family, now=now,
                             poll_s=WAYLAND_POLL_S)
            return
        super().__init__(pid, foreground_pid=foreground_pid or display.foreground_pid,
                         cursor=cursor or display.cursor,
                         family=family, now=now, poll_s=0.05)
