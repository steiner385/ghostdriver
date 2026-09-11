"""The tool surface, as plain functions returning plain data.

Deliberately separate from the MCP binding. The protocol layer is a thin
adapter over this; everything that could be wrong — a tier not enforced, a
result that blows a context budget, an error that says nothing useful — is
wrong here, and can be tested here without a protocol client.

Two rules shape every result.

**Locators, not handles.** A handle is valid only for the enumeration that
produced it: the OS recycles them, and one held across a call answers about
a window that no longer exists. Every element carries a locator that can be
re-resolved instead. Handles are still reported, marked ephemeral, because
they are what makes two same-captioned controls distinguishable in a single
result — but nothing should store one.

**Results are for an agent's context, not a file.** A target with ~1,100
windows can answer almost any query with more than a caller can read.
Everything that can return many rows caps them and says what it capped.
"""

import functools
import inspect
import time

from ..backends import AccessibilityUnavailable
from ..model.result import ErrorKind
from .actuation import ActuationTools
from .batch import BatchTools
from .core import MAX_ELEMENTS, SENSITIVE_HINT, _element, _error
from .discovery import DiscoveryTools
from .human import HumanTools
from .launch import LaunchTools
from .learning import LearningTools
from .lifecycle import LifecycleTools
from .macro import MacroTools
from .pace import PaceTools
from .recording import capture_step
from .screen import ScreenTools
from .seek import SeekTools
from .set_value import SetValueTools
from .status import StatusTools

__all__ = ["MAX_ELEMENTS", "SENSITIVE_HINT", "Toolbox", "_element", "_error"]


class Toolbox(LifecycleTools, LaunchTools, DiscoveryTools, StatusTools, ActuationTools,
              SetValueTools, HumanTools, LearningTools, SeekTools, ScreenTools,
              BatchTools, PaceTools, MacroTools):
    """Every tool, over one session manager.

    One class, so a caller holds one object; one module per family, so a
    reader opens the file named for what they are looking at. The
    dataclass fields and every shared helper live on `_ToolboxCore`.
    """


#: Tools that wait: their start is traced, not only their end.
LONG_WAITS = frozenset({"await_human", "wait_for"})


def _traced_and_reporting(fn, *, session_tool: bool):
    """Record every call in the trace; append watchdog events to session tools.

    Two things done in one wrapper because they need the same seam: the
    place a result passes on its way out. The trace is what lets a call
    made in another session be read afterwards -- tool, arguments, outcome,
    error, elapsed -- which is how a report like "it could not click the
    link" arrives with the call it tried. Watchdog events ride on session
    tools because the event is the product (D49) and a caller should not
    have to know which tool to ask; `release` reports its own.
    """
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        started = time.monotonic()
        try:
            bound = signature.bind_partial(self, *args, **kwargs).arguments
            bound.pop("self", None)
        except TypeError:
            bound = {"args": list(args), **kwargs}
        session_id = bound.get("session_id") if session_tool else None
        result = None
        if fn.__name__ in LONG_WAITS:
            # Recorded on the way in as well: a server that dies during a
            # wait leaves no result, and the next run can at least say what
            # the person was in the middle of (D66).
            self._tracer().record({"tool": fn.__name__, "phase": "began",
                                   "session_id": session_id, "args": dict(bound)})
        try:
            result = fn(self, *args, **kwargs)
            if session_tool and isinstance(result, dict) and fn.__name__ != "release":
                watch = self._watches.get(session_id)
                if watch is not None:
                    events = watch.drain()
                    if events:
                        result["watchdog_events"] = events
                    if watch.suspended_reason:
                        result["watchdog_suspended"] = watch.suspended_reason
                # If this session is recording (#88), buffer the call as a
                # macro step. The dict lookup is the whole cost when it is
                # not -- the common case -- so it rides here on every call.
                if self._recordings:
                    recording = self._recordings.get(session_id)
                    if recording is not None:
                        step = capture_step(fn.__name__, bound, result)
                        if step is not None:
                            recording["steps"].append(step)
            return result
        except AccessibilityUnavailable as exc:
            # The platform is supported and its accessibility service is not
            # running -- a headless box, a container, a session with no
            # DISPLAY. Ordinary, and something a caller can act on, so it
            # leaves as a result rather than an exception (D10).
            #
            # Caught here rather than in each tool because every tool that
            # reaches the tree can raise it, and the alternative to catching
            # it at all used to be the process aborting outright (#58).
            result = _error(ErrorKind.NOT_ACTIONABLE, str(exc))
            return result
        except Exception as exc:
            self._tracer().record({
                "tool": fn.__name__, "session_id": session_id, "args": dict(bound),
                "ok": False, "error_kind": "exception",
                "error_message": f"{type(exc).__name__}: {exc}",
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            })
            raise
        finally:
            if result is not None:
                trace = self._tracer()
                if trace.enabled:
                    error = result.get("error") if isinstance(result, dict) else None
                    trace.record({
                        "tool": fn.__name__,
                        "session_id": (result.get("session_id") if isinstance(result, dict)
                                       and "session_id" in result else session_id),
                        "args": dict(bound),
                        "ok": bool(result.get("ok")) if isinstance(result, dict) else None,
                        "error_kind": (error or {}).get("kind") if error else None,
                        "error_message": (error or {}).get("message") if error else None,
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                        "watchdog_events": (len(result.get("watchdog_events", []))
                                            if isinstance(result, dict) else 0),
                        "result": _result_summary(result),
                    })
    return wrapper


def _result_summary(result):
    """The parts of a result worth keeping in a trace line."""
    if not isinstance(result, dict):
        return None
    keep = ("verified", "tier_used", "tiers_attempted", "match_count", "display",
            "isolation", "released", "blocked", "left_minimized", "needs_consent",
            "total", "waited_ms", "expected", "button", "modifiers", "at", "count",
            "route", "grid_strategy", "sample_lines", "written", "focus",
            "open_sessions_stopped", "length", "empty", "saved_to", "timeout_s",
            "found", "row_count", "pages_read", "reached_end", "advanced",
            "delivered_to", "hit_container", "warning", "until_change",
            "still_arriving", "idle", "polls", "outside_container",
            "took_foreground", "physical_rect")
    return {k: result[k] for k in keep if k in result}


for _name, _fn in inspect.getmembers(Toolbox, inspect.isfunction):
    if _name.startswith("_"):
        continue
    _params = list(inspect.signature(_fn).parameters)[1:]
    setattr(Toolbox, _name, _traced_and_reporting(
        _fn, session_tool=bool(_params) and _params[0] == "session_id"))
