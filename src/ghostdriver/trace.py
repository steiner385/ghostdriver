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
    if event.get("phase") == "began":
        event = {**event, "ok": None, "result": "began"}
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


def lost_session_hint(session_id: str) -> str | None:
    """What the trace knows about a session id nobody has open.

    A server restart takes its sessions with it and the next call is the
    first anyone hears of it. The trace outlives the server, so the call
    can at least be told which run opened the session, against what, and
    how to open another one (D65).
    """
    from .operator import ENV_VAR, OperatorDir, OperatorDirError

    if not os.environ.get(ENV_VAR):
        return None
    try:
        logs = OperatorDir.resolve().root / "logs"
    except OperatorDirError:
        return None
    files = sorted(logs.glob("ghostdriver-*.jsonl"), key=lambda f: f.stat().st_mtime,
                   reverse=True)
    for path in files:
        events = read(path, session_id=session_id)
        unfinished = ""
        if events and events[-1].get("phase") == "began":
            last = events[-1]
            ask = (last.get("args") or {}).get("ask")
            unfinished = (f" That run was in {last['tool']} when it went"
                          + (f" (the ask: {ask!r})" if ask else "")
                          + "; the person may still be acting on it.")
        for event in events:
            if event.get("tool") != "attach" or not event.get("ok"):
                continue
            args = event.get("args") or {}
            when = time.strftime("%H:%M:%S", time.localtime(event.get("at", 0)))
            pid, tier = args.get("pid"), args.get("tier")
            if path.name.endswith(f"-{os.getpid()}.jsonl"):
                return (f"session {session_id!r} was opened at {when} by this server "
                        f"run against pid {pid} and is no longer open: released, or "
                        "its target gone")
            return (f"session {session_id!r} was opened at {when} by an earlier "
                    f"server run (trace {path.name}) against pid {pid} at tier "
                    f"{tier!r}; that server is gone and its sessions with it. "
                    f"attach(pid={pid}, tier={tier!r}) opens a new one; the "
                    "approval is kept while that process lives." + unfinished)
    return None


def scale_report(events: list[dict]) -> list[str]:
    """How `describe` fared at the sizes it actually met (#227, Gate 3).

    One line per traced describe that recorded its numbers, largest tree
    first, then a line saying what the largest was. Calls traced before
    the numbers were kept are counted, not guessed at.
    """
    rows, unmeasured = [], 0
    for event in events:
        if event.get("tool") != "describe" or event.get("phase") or not event.get("ok"):
            continue
        result = event.get("result") or {}
        if "windows_total" not in result:
            unmeasured += 1
            continue
        rows.append((result["windows_total"], result.get("nodes_shown", 0),
                     result.get("tree_chars", 0), bool(result.get("truncated")),
                     result.get("elided_by_collapsing", 0), result.get("below_depth", 0),
                     event.get("elapsed_ms") or 0, (event.get("args") or {}).get("max_nodes", 200),
                     bool(result.get("within"))))
    rows.sort(reverse=True)
    lines = [f"{'windows':>8} {'shown':>6} {'chars':>6} {'trunc':>5} {'collapsed':>9} "
             f"{'below':>6} {'ms':>6} {'max_nodes':>9}  scope"]
    for total, shown, chars, truncated, elided, below, ms, asked, within in rows:
        lines.append(f"{total:>8} {shown:>6} {chars:>6} {'yes' if truncated else 'no':>5} "
                     f"{elided:>9} {below:>6} {ms:>6} {asked:>9}  {'within' if within else 'whole'}")
    if rows:
        top = rows[0]
        lines.append(f"-- {len(rows)} describe call(s) measured; the largest tree held "
                     f"{top[0]} windows and came back as {top[2]} characters "
                     f"({'truncated, and said so' if top[3] else 'whole'})")
    else:
        lines = ["-- no describe call in this trace recorded its numbers"]
    if unmeasured:
        lines.append(f"-- {unmeasured} earlier describe call(s) were traced before the numbers were kept")
    return lines
