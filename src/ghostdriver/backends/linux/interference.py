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


class InterferenceWatch(_Watch):
    def __init__(self, pid: int, *,
                 family: Callable[[], list[int]] | None = None,
                 foreground_pid: Callable[[], int] = display.foreground_pid,
                 cursor: Callable[[], tuple[int, int]] = display.cursor,
                 now: Callable[[], float] = time.time):
        super().__init__(pid, foreground_pid=foreground_pid, cursor=cursor,
                         family=family, now=now, poll_s=0.05)
