"""Did anything on the operator's desktop get disturbed during a run?

The logic lives in `ghostdriver.interference` now (D#111 lifted it, as D#40c
said it wanted): this module supplies the two Win32 samplers and keeps the
class importable from where it always was.
"""

import ctypes
import time
from collections.abc import Callable
from ctypes import wintypes

from ...interference import POLL_S
from ...interference import InterferenceWatch as _Watch
from . import winapi

__all__ = ["POLL_S", "InterferenceWatch"]


def _cursor() -> tuple[int, int]:
    point = wintypes.POINT()
    winapi.user32.GetCursorPos(ctypes.byref(point))
    return (point.x, point.y)


def _foreground_pid() -> int:
    hwnd = winapi.foreground_window()
    return winapi.window_pid(hwnd) if hwnd else 0


class InterferenceWatch(_Watch):
    def __init__(self, pid: int, *,
                 family: Callable[[], list[int]] | None = None,
                 foreground_pid: Callable[[], int] = _foreground_pid,
                 cursor: Callable[[], tuple[int, int]] = _cursor,
                 now: Callable[[], float] = time.time):
        super().__init__(pid, foreground_pid=foreground_pid, cursor=cursor,
                         family=family, now=now)
