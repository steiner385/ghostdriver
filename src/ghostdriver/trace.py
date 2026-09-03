"""A trace of every tool call, written where the operator can read it.

Each session launches its own server over stdio and, until this, that
process kept no record: every call, argument and result vanished with the
session unless the model happened to paste them into chat. So a report
like "the tool could not click the link" arrived without the call it had
tried. The trace is one JSON line per tool call -- when, which session,
which tool, the arguments, the outcome, the error kind, how long it took,
and any watchdog events -- appended to a file under the operator
directory's `logs/`, one file per server process per day.

On only when the operator directory is configured (it is the one place
target knowledge is allowed to land), and off with GHOSTDRIVER_TRACE=0;
GHOSTDRIVER_TRACE=<path> names a file instead. Pixels are left out and
long values trimmed: the trace is for reading, not for replaying.
"""

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

ENV_VAR = "GHOSTDRIVER_TRACE"
MAX_STRING = 2000
MAX_ITEMS = 50


def trimmed(value: Any) -> Any:
    """`value` with pixels left out and long strings and lists cut short."""
    if isinstance(value, dict):
        return {k: ("<png omitted>" if k == "base64" else trimmed(v)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        head = [trimmed(v) for v in value[:MAX_ITEMS]]
        if len(value) > MAX_ITEMS:
            head.append(f"<{len(value) - MAX_ITEMS} more omitted>")
        return head
    if isinstance(value, str) and len(value) > MAX_STRING:
        return value[:MAX_STRING] + f"<{len(value) - MAX_STRING} more chars omitted>"
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return repr(value)[:MAX_STRING]


class Trace:
    """Appends one JSON line per event to `path`; a no-op when `path` is None."""

    def __init__(self, path: Path | None):
        self.path = path
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.path is not None

    @classmethod
    def from_environment(cls) -> "Trace":
        """Where the trace goes, from the environment; nowhere if unconfigured.

        A misconfigured operator directory is not a reason to fail a tool
        call, so every failure here means "no trace", never an exception.
        """
        setting = os.environ.get(ENV_VAR, "")
        if setting.strip() in ("0", "off", "false", "no"):
            return cls(None)
        if setting.strip():
            return cls(Path(setting).expanduser())
        try:
            from .operator import OperatorDir

            folder = OperatorDir.resolve()
        except Exception:
            return cls(None)
        stamp = time.strftime("%Y%m%d")
        return cls(folder.root / "logs" / f"ghostdriver-{stamp}-{os.getpid()}.jsonl")

    def record(self, event: dict) -> None:
        if self.path is None:
            return
        line = json.dumps({"at": time.time(), **trimmed(event)}, default=str)
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError:
            # A trace that cannot be written must not stop the call it traces.
            return


def read(path: Path, *, tail: int | None = None, session_id: str | None = None) -> list[dict]:
    """Events from one trace file, oldest first; filtered and tailed."""
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if session_id and event.get("session_id") != session_id:
            continue
        events.append(event)
    return events[-tail:] if tail else events


def describe(event: dict) -> str:
    """One line a person can read: time, session, tool, outcome, elapsed."""
    when = time.strftime("%H:%M:%S", time.localtime(event.get("at", 0)))
    session = (event.get("session_id") or "-")[:12]
    tool = event.get("tool", "?")
    outcome = "ok" if event.get("ok") else f"FAIL {event.get('error_kind') or ''}".rstrip()
    elapsed = event.get("elapsed_ms")
    args = event.get("args") or {}
    shown = ", ".join(f"{k}={json.dumps(v)}" for k, v in args.items() if k != "session_id")
    extra = ""
    if event.get("watchdog_events"):
        extra += f"  watchdog={event['watchdog_events']}"
    if event.get("error_message"):
        extra += f"  -- {event['error_message'][:160]}"
    return f"{when} {session} {tool:<24} {outcome:<22} {elapsed or 0:>6}ms  {shown[:200]}{extra}"
