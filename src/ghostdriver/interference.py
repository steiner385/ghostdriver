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
                 cursor: Callable[[], tuple[int, int]] | None,
                 family: Callable[[], list[int]] | None = None,
                 now: Callable[[], float] = time.time,
                 poll_s: float = POLL_S):
        self.pid = pid
        #: The process family to watch for, asked each poll (R5, D71).
        self._family = family
        self._foreground_pid = foreground_pid
        #: None where the pointer cannot be read -- a Wayland desktop has no
        #: global pointer query (W5). The foreground half still runs, and
        #: `watches_pointer` says the other half did not (#225).
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

    @property
    def unwatched(self) -> str:
        """What this watch cannot see, said in a sentence; "" when nothing."""
        return "" if self.watches_pointer else POINTER_UNWATCHED

    @property
    def watches_pointer(self) -> bool:
        """Whether pointer movement is watched at all. When it is not, no
        `cursor_moved` event means nothing about the pointer, and a result
        must say so rather than let the silence read as stillness."""
        return self._cursor is not None

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

    def observe(self, foreground_pid: int, cursor: tuple[int, int] | None,
                last_foreground: int, last_cursor: tuple[int, int] | None) -> None:
        """One poll step, separated so it can be fed."""
        family = self.family_now()
        if foreground_pid in family and last_foreground not in family:
            who = ("the target" if foreground_pid == self.pid
                   else f"a process the target spawned (pid {foreground_pid})")
            self._events.append({
                "kind": "foreground_taken", "at": self._now(), "pid": foreground_pid,
                "detail": f"a window of {who} became the foreground window",
            })
        if cursor is not None and last_cursor is not None and cursor != last_cursor:
            self._events.append({
                "kind": "cursor_moved", "at": self._now(),
                "from": list(last_cursor), "to": list(cursor),
                "detail": "the cursor moved; this tool never moves it",
            })

    def _run(self) -> None:
        sample_cursor = self._cursor
        last_foreground = self._foreground_pid()
        last_cursor = sample_cursor() if sample_cursor else None
        while not self._stop.is_set():
            foreground = self._foreground_pid()
            cursor = sample_cursor() if sample_cursor else None
            self.observe(foreground, cursor, last_foreground, last_cursor)
            last_foreground, last_cursor = foreground, cursor
            self._stop.wait(self._poll_s)


#: Said in a result when the pointer half of the watch could not run.
POINTER_UNWATCHED = (
    "the pointer: this desktop gives no way to read it (Wayland, W5), so "
    "pointer movement was not watched -- no cursor_moved event means "
    "nothing either way"
)


def watch_fields(watch, events: list[dict]) -> dict:
    """The fields a result carries about its watch: what it saw, and what it
    could not see. A watch without a pointer must say so, or an empty event
    list reads as "the pointer never moved" (#225)."""
    fields: dict = {"interference": events} if events else {}
    if getattr(watch, "unwatched", ""):
        fields["interference_unwatched"] = watch.unwatched
    return fields
