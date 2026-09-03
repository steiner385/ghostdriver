"""Did anything on the operator's desktop get disturbed during a run?

Two questions, polled on a thread for the life of a workflow run:

- did the target take the foreground -- the promise the tool exists to
  keep, so one such event fails the run whatever the steps said;
- did the cursor move -- which the tool never does, so movement is either
  the operator at the keyboard or something worth knowing about, and is
  reported rather than judged.

The predicates are injectable so the recording logic is tested with a fed
sequence rather than by disturbing a real desktop.
"""

import ctypes
import threading
import time
from collections.abc import Callable
from ctypes import wintypes

from . import winapi

POLL_S = 0.02


def _cursor() -> tuple[int, int]:
    point = wintypes.POINT()
    winapi.user32.GetCursorPos(ctypes.byref(point))
    return (point.x, point.y)


def _foreground_pid() -> int:
    hwnd = winapi.foreground_window()
    return winapi.window_pid(hwnd) if hwnd else 0


class InterferenceWatch:
    def __init__(self, pid: int, *,
                 foreground_pid: Callable[[], int] = _foreground_pid,
                 cursor: Callable[[], tuple[int, int]] = _cursor,
                 now: Callable[[], float] = time.time):
        self.pid = pid
        self._foreground_pid = foreground_pid
        self._cursor = cursor
        self._now = now
        self._events: list[dict] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name=f"interference-watch-{self.pid}")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def events(self) -> list[dict]:
        return list(self._events)

    def observe(self, foreground_pid: int, cursor: tuple[int, int],
                last_foreground: int, last_cursor: tuple[int, int]) -> None:
        """One poll step, separated so it can be fed."""
        if foreground_pid == self.pid and last_foreground != self.pid:
            self._events.append({
                "kind": "foreground_taken", "at": self._now(),
                "detail": "a window of the target became the foreground window",
            })
        if cursor != last_cursor:
            self._events.append({
                "kind": "cursor_moved", "at": self._now(),
                "from": list(last_cursor), "to": list(cursor),
                "detail": "the cursor moved; this tool never moves it",
            })

    def _run(self) -> None:
        last_foreground = self._foreground_pid()
        last_cursor = self._cursor()
        while not self._stop.is_set():
            foreground, cursor = self._foreground_pid(), self._cursor()
            self.observe(foreground, cursor, last_foreground, last_cursor)
            last_foreground, last_cursor = foreground, cursor
            self._stop.wait(POLL_S)
