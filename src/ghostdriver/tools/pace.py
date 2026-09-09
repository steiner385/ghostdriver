"""A fixed dwell, and the honesty about what it is not (D#76).

A deliberate exception to this server's rule against arbitrary sleeps
(D45). Where a target declares a `busy_indicator`, `wait_idle` waits on the
screen itself and is the right tool; where a control's arrival can be
named, `wait_for` is. `pace` is for the gap before either is available -- a
hybrid loop was otherwise abusing `wait_for` against a locator built never
to match, as an N-second timer, which is one wasted call and a lie about
what is being waited for. This is the honest primitive for that dwell, and
its result points at the better tool so the stopgap does not quietly become
the habit.
"""

import time

from ..model.result import ErrorKind, GhostdriverError
from .core import _error, _ToolboxCore

#: A pace dwell is clamped here: a fixed wait is a stopgap, and a very long
#: one is more likely a mistake than an intent.
PACE_MAX_S = 120.0

_BETTER_TOOL = (
    "a fixed dwell, not a measurement. If this target shows it is busy, "
    "declare a busy_indicator in its profile and use wait_idle; if a "
    "control's arrival can be named, use wait_for -- both wait on the target "
    "rather than the clock."
)


class PaceTools(_ToolboxCore):
    """Dwell for a fixed time, when nothing better can be waited on."""

    #: Exposed on the class so a test can shorten it without waiting the cap.
    PACE_MAX_S = PACE_MAX_S

    def pace(self, session_id: str, seconds: float) -> dict:
        """Dwell for `seconds`, then return. Clamped to `PACE_MAX_S`.

        The stopgap for a hybrid loop with no `busy_indicator` to wait on;
        the result names the better tool, because a fixed wait is a guess
        about the target rather than a reading of it.
        """
        try:
            self.sessions.authorize(session_id, "pace")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        try:
            wanted = float(seconds)
        except (TypeError, ValueError):
            return _error(ErrorKind.NOT_ACTIONABLE,
                          f"seconds must be a number, not {seconds!r}")
        if wanted <= 0:
            return _error(ErrorKind.NOT_ACTIONABLE,
                          "seconds must be positive; there is nothing to wait")

        capped = min(wanted, self.PACE_MAX_S)
        started = time.monotonic()
        time.sleep(capped)
        waited_ms = int((time.monotonic() - started) * 1000)

        note = _BETTER_TOOL
        result: dict = {"ok": True, "waited_ms": waited_ms, "requested_s": wanted}
        if capped < wanted:
            result["capped_to_s"] = self.PACE_MAX_S
            note = f"clamped to {self.PACE_MAX_S:g}s (asked {wanted:g}). " + note
        result["note"] = note
        return result
