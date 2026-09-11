"""Did anything on the operator's desktop get disturbed during a run?

Two questions, polled on a thread for the life of a workflow run or one live
action:

- did the target take the foreground -- the promise the tool exists to
  keep, so one such event fails the run whatever the steps said;
- did the cursor move -- which the tool never does, so movement is either
  the operator at the keyboard or something worth knowing about, and is
  reported rather than judged (D28).

**Platform-neutral by construction.** The predicates -- which process holds
the front, where the pointer is, what time it is -- are injected, so the
recording logic is tested with a fed sequence rather than by disturbing a
real desktop, and each backend supplies its own samplers. D#40c named this
as the thing that wanted lifting rather than reimplementing; the Linux live
path (D#111) is what finally needed it, because it arms one of these around
every action it takes on the operator's own display.
"""

import threading
import time
from collections.abc import Callable

POLL_S = 0.02


class InterferenceWatch:
    def __init__(self, pid: int, *,
                 foreground_pid: Callable[[], int],
                 cursor: Callable[[], tuple[int, int]],
                 family: Callable[[], list[int]] | None = None,
                 now: Callable[[], float] = time.time,
                 poll_s: float = POLL_S):
        self.pid = pid
        #: The process family to watch for, asked each poll (R5, D71).
        self._family = family
        self._foreground_pid = foreground_pid
        self._cursor = cursor
        self._now = now
        self._poll_s = poll_s
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

    def family_now(self) -> list[int]:
        """The target and its descendants right now; the target alone when
        no family was given or the snapshot failed."""
        if self._family is None:
            return [self.pid]
        try:
            pids = list(self._family())
        except Exception:
            return [self.pid]
        return pids if self.pid in pids else [self.pid, *pids]

    def observe(self, foreground_pid: int, cursor: tuple[int, int],
                last_foreground: int, last_cursor: tuple[int, int]) -> None:
        """One poll step, separated so it can be fed."""
        family = self.family_now()
        if foreground_pid in family and last_foreground not in family:
            who = ("the target" if foreground_pid == self.pid
                   else f"a process the target spawned (pid {foreground_pid})")
            self._events.append({
                "kind": "foreground_taken", "at": self._now(), "pid": foreground_pid,
                "detail": f"a window of {who} became the foreground window",
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
            self._stop.wait(self._poll_s)
