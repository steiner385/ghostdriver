"""The `minimized` isolation strategy, as policy.

Spec section 7: keep the target minimized, and if it restores or foregrounds
itself, put it back -- and say so. The guarantee is observational rather
than structural, which is exactly why the watchdog exists: a single trial
of "it stayed minimized" proves nothing about the next modal.

**The watchdog is a feature, not a mitigation** (section 7.2). A background
application that suddenly demands the foreground is almost always raising
something -- an error box, a confirmation, a session timeout -- and for a
testing tool that is information no assertion would have caught. So the
event is the product; re-minimizing is the housekeeping.

Pure policy. It is fed observations and returns decisions; the sampling,
the capture and the `ShowWindow` call live in the backend. That is what
makes the interesting questions -- when to act, what to report, how not to
flap -- testable without a desktop, and it is what keeps a module about
focus from being able to touch focus by itself.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class Isolation(str, Enum):
    """Which strategy a session runs under."""

    #: The live desktop, no watchdog. Development and debugging only.
    NONE = "none"
    #: Keep the target minimized; re-minimize and report if it surfaces.
    MINIMIZED = "minimized"


@dataclass(frozen=True, slots=True)
class Observation:
    """One sample of the world, taken by the backend."""

    at: float
    #: Any top-level window of the target is visible and not minimized.
    #: This -- not the main window's flag alone -- is the question, because
    #: a background app most often escapes by raising a *new* window (an
    #: error box, a confirmation) while its main window stays minimized.
    #: That is the modal the strategy exists to catch.
    target_on_screen: bool
    #: The window owning the desktop foreground is a non-minimized window of
    #: the target. Distinguishes a window that came back and demanded
    #: attention from one that merely reappeared behind others.
    target_is_foreground: bool


@dataclass(frozen=True, slots=True)
class Event:
    """Something the watchdog saw and did, for the operator and the agent."""

    kind: str
    at: float
    #: Seconds since the target was last observed quiet. Under continuous
    #: polling this is about one poll interval -- it says "it was quiet a
    #: moment ago and is not now", which is what marks a genuine escape.
    #: It is NOT the action-to-grab latency; that is measured sparsely from
    #: a known action, which is phase 2's job, not the watchdog's.
    after_quiet_s: float
    detail: str = ""
    #: Set by the backend when it captured the window before re-minimizing.
    capture_png: bytes | None = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "at": self.at,
            "after_quiet_s": round(self.after_quiet_s, 3),
            "detail": self.detail,
            "captured": self.capture_png is not None,
        }


class Action(str, Enum):
    """What the backend should do after an observation."""

    NOTHING = "nothing"
    #: Capture the window (it is on screen and probably showing something
    #: worth seeing), then minimize it without activating anything else.
    CAPTURE_THEN_MINIMIZE = "capture_then_minimize"
    #: Put the target away to establish the quiet baseline at the start.
    #: No capture: nothing has escaped yet, so there is nothing to photograph.
    MINIMIZE = "minimize"


#: After the watchdog re-minimizes, the target's own restore path may re-show
#: forms for a moment; sampling straight away would see that and act again.
#: A short hold stops the loop, and is far below any grab delay measured.
HOLD_AFTER_ACTION_S = 0.3

#: A target that keeps surfacing faster than this is not raising a dialog,
#: it is fighting the watchdog -- and the watchdog must lose gracefully
#: rather than turn the desktop into a flicker. Beyond this many events in
#: the window, it stops acting and reports that it stopped.
FLAP_LIMIT = 5
FLAP_WINDOW_S = 10.0


@dataclass
class Watchdog:
    """Decides, from observations, when the target has escaped and what to do.

    `now` is injected so the flap window and quiet timing are testable.
    """

    now: Callable[[], float]
    events: list[Event] = field(default_factory=list)
    #: When the target was last seen minimized and not foreground.
    last_quiet_at: float | None = None
    hold_until: float = 0.0
    #: Set when flapping was detected; the watchdog then observes only.
    suspended_reason: str = ""
    _recent: list[float] = field(default_factory=list, repr=False)

    def observe(self, seen: Observation) -> Action:
        # Quiet means nothing of the target is on screen. Foreground
        # ownership is not the question: minimizing without activating
        # anything else leaves the minimized window still owning the
        # foreground handle, so a put-away target can still be "foreground"
        # -- measured against a real window. On-screen is what a person
        # sees, and it is what escape is defined against.
        quiet = not seen.target_on_screen
        if quiet:
            self.last_quiet_at = seen.at
            return Action.NOTHING

        if seen.at < self.hold_until or self.suspended_reason:
            return Action.NOTHING

        # Everything below is a not-quiet target past the debounce hold.
        # Whether it counts as an *escape* depends on one thing: have we
        # ever seen it quiet? A target that starts on screen -- a freshly
        # shown window owns the foreground -- has not escaped from anything,
        # it has simply not been put away yet. Reporting that as a grab
        # would cry wolf on the opening state of every session.
        self._recent = [t for t in self._recent if seen.at - t <= FLAP_WINDOW_S]
        self._recent.append(seen.at)
        self.hold_until = seen.at + HOLD_AFTER_ACTION_S

        # A target that will not stay put -- whether it never quieted or
        # keeps fighting back -- is handled the same way: the watchdog loses
        # gracefully rather than turning the desktop into a flicker.
        if len(self._recent) > FLAP_LIMIT:
            self.suspended_reason = (
                f"could not keep the target minimized ({len(self._recent)} "
                f"attempts in {FLAP_WINDOW_S:.0f}s); the watchdog has stopped "
                "acting so as not to fight it, and is only reporting now"
            )
            self.events.append(Event(
                kind="watchdog_suspended", at=seen.at,
                after_quiet_s=self._since_quiet(seen), detail=self.suspended_reason,
            ))
            return Action.NOTHING

        if self.last_quiet_at is None:
            # No baseline yet: put it away to establish one. Not an escape,
            # so no event and no capture -- the opening minimize is not news.
            return Action.MINIMIZE

        if seen.target_is_foreground:
            self.events.append(Event(
                kind="unexpected_foreground", at=seen.at,
                after_quiet_s=self._since_quiet(seen),
                detail=(
                    "the target took the foreground on its own; a modal is "
                    "the usual reason, so the window was captured before "
                    "being re-minimized"
                ),
            ))
            return Action.CAPTURE_THEN_MINIMIZE

        self.events.append(Event(
            kind="unexpected_restore", at=seen.at,
            after_quiet_s=self._since_quiet(seen),
            detail="a window of the target came on screen without taking the "
                   "foreground; it is captured before being put back, because "
                   "what appeared is the whole question",
        ))
        return Action.CAPTURE_THEN_MINIMIZE

    def _since_quiet(self, seen: Observation) -> float:
        if self.last_quiet_at is None:
            return 0.0
        return seen.at - self.last_quiet_at

    def attach_capture(self, png: bytes | None) -> None:
        """Let the backend hand the capture back to the last event."""
        if not self.events or png is None:
            return
        last = self.events[-1]
        self.events[-1] = Event(
            kind=last.kind, at=last.at, after_quiet_s=last.after_quiet_s,
            detail=last.detail, capture_png=png,
        )

    def drain(self) -> list[Event]:
        out, self.events = self.events, []
        return out
