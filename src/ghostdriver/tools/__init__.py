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

from .actuation import ActuationTools
from .core import MAX_ELEMENTS, SENSITIVE_HINT, _element, _error
from .discovery import DiscoveryTools
from .human import HumanTools
from .learning import LearningTools
from .lifecycle import LifecycleTools
from .status import StatusTools

__all__ = ["MAX_ELEMENTS", "SENSITIVE_HINT", "Toolbox", "_element", "_error"]


class Toolbox(LifecycleTools, DiscoveryTools, StatusTools, ActuationTools,
              HumanTools, LearningTools):
    """Every tool, over one session manager.

    One class, so a caller holds one object; one module per family, so a
    reader opens the file named for what they are looking at. The
    dataclass fields and every shared helper live on `_ToolboxCore`.
    """


def _reporting_watchdog_events(fn):
    """Append what the minimized watchdog saw to any session tool's result.

    The event is the product (D49): a caller should not have to know which
    tool to ask. So every tool that takes a session id reports, on its own
    result, whatever the watchdog recorded since the last call -- `describe`
    as readily as `click`. `release` reports its own, because by the time
    it returns the watch is gone.
    """
    @functools.wraps(fn)
    def wrapper(self, session_id, *args, **kwargs):
        result = fn(self, session_id, *args, **kwargs)
        watch = self._watches.get(session_id)
        if watch is not None and isinstance(result, dict):
            events = watch.drain()
            if events:
                result["watchdog_events"] = events
            if watch.suspended_reason:
                result["watchdog_suspended"] = watch.suspended_reason
        return result
    return wrapper


for _name, _fn in inspect.getmembers(Toolbox, inspect.isfunction):
    if _name.startswith("_") or _name == "release":
        continue
    _params = list(inspect.signature(_fn).parameters)[1:]
    if _params and _params[0] == "session_id":
        setattr(Toolbox, _name, _reporting_watchdog_events(_fn))
