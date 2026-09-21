"""One process, one accessibility bus, for as long as it lives.

Measured for `HiddenDesktop` (#40 slice 5b), not assumed: `Atspi.init()` is
idempotent at the C library level, so a second call against a different
`AT_SPI_BUS_ADDRESS` does not reconnect -- it silently keeps answering from
the first bus it ever reached. Nor does `Atspi.exit()` give a clean second
chance; it tears down the library's internal state (measured:
`g_hash_table_insert_internal: assertion 'hash_table != NULL' failed` on the
very next call) rather than freeing it for reuse. And a forked child
inherits the same live connection regardless of its own environment --
measured against two real nested buses, a forked child that switched every
environment variable still reported the parent's bus's application, not its
own. This is a property of the vendor library every Linux contract call
already depends on (`tree.py`), not something slice 5b introduced; it only
introduced the second bus that makes the limit visible.

So a process either talks to the operator's own accessibility bus, or to
one nested display's, never both and never in sequence -- the claim, once
made, is for the rest of the process's life; there is no release that would
mean anything, because the connection it names cannot be handed back
either. `display.py` and `tree.py` claim `OPERATOR_DESKTOP` the first time
either opens a connection. `HiddenDesktop.run` claims its own name for the
duration of the call it wraps, via `desktop()`, so the same choke points
correctly recognise the hidden desktop's own driving of its target as the
claim it already holds, rather than a second, conflicting one.

**Why this also carries an environment, not just a name.** The ambient
`os.environ["DISPLAY"]` is the operator's; swapping it process-wide for the
duration of a call would race any other thread reading it for its own
first connection (a `MinimizedWatch` or `InterferenceWatch` sampling an
unrelated, ordinary session concurrently). `register()` instead hands
`display.py` the exact `DISPLAY` string to pass `Xlib.display.Display()`
explicitly, keyed by claimant, so no ambient variable ever needs to change.
AT-SPI has no such explicit-argument escape -- `Atspi.init()` only reads
environment -- but it needs none: once a claim is made, the process can
never open a second bus anyway (see above), so `AT_SPI_BUS_ADDRESS` and
`DBUS_SESSION_BUS_ADDRESS` are set once, permanently, the first time
`tree.py` claims, rather than swapped and restored around every call.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator
from contextvars import ContextVar

_LOCK = threading.Lock()
_owner: str | None = None
_current: ContextVar[str | None] = ContextVar("ghostdriver_desktop_context", default=None)
_environments: dict[str, dict[str, str]] = {}

#: What every ordinary (non-nested) call claims the process for, when no
#: `desktop()` context says otherwise.
OPERATOR_DESKTOP = "the operator's own desktop"


class AlreadyClaimed(RuntimeError):
    """This process already talks to a different accessibility bus."""


def effective_owner() -> str:
    """Who a call right now claims the process for: the innermost `desktop()`
    context if one is active, else the operator's own desktop."""
    return _current.get() or OPERATOR_DESKTOP


def claim() -> None:
    """Claim the process for `effective_owner()`, or confirm it already is.

    Raises if someone else got there first. Called from every choke point
    that is about to touch the shared accessibility connection -- `display.
    _display()` and `tree._applications()` -- before it does, so a second
    claimant is refused loudly rather than left to read from the first
    claimant's bus without knowing it.
    """
    global _owner
    owner = effective_owner()
    with _LOCK:
        if _owner is None:
            _owner = owner
            return
        if _owner != owner:
            raise AlreadyClaimed(
                f"this process already talks to {_owner}'s accessibility "
                f"bus; {owner} cannot also use it. AT-SPI supports one bus "
                "connection per process for its whole life (see "
                "desktop_claim.py's docstring for the measurement), so "
                "driving both means two processes."
            )


def claimed_by() -> str | None:
    return _owner


def register(name: str, **env: str) -> None:
    """Record the environment `name` reaches its target through.

    `HiddenDesktop.prepare` calls this with its `DISPLAY`,
    `DBUS_SESSION_BUS_ADDRESS` and `AT_SPI_BUS_ADDRESS` before starting
    anything, so the choke points that need one of these values can look it
    up by claimant instead of reading the ambient (operator's) environment.
    """
    _environments[name] = dict(env)


def environment_for(owner: str) -> dict[str, str]:
    """What `register` recorded for `owner`, or empty for the operator's own
    desktop, which has none to record -- it is whatever the process already
    inherited."""
    return _environments.get(owner, {})


@contextlib.contextmanager
def desktop(name: str) -> Iterator[None]:
    """Mark every call inside the block as belonging to `name`.

    `HiddenDesktop.run` wraps every marshalled call in this, so the same
    `display.py` / `tree.py` functions the rest of the backend already uses
    correctly recognise the hidden desktop's own driving of its target as
    the claim it holds -- not a second, conflicting one.
    """
    token = _current.set(name)
    try:
        yield
    finally:
        _current.reset(token)
