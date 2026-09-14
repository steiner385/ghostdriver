"""Doing something to a control, and knowing whether it worked.

Two ideas carry this module.

**The tier ladder.** A verb has several implementations at different levels
of the stack, and a profile decides where to start. An accessible target is
driven through the surface it publishes; a Profile L1 target falls to
input-shaped window messages because nothing above that answers. Failures
fall through, and every tier attempted is reported -- an action that
succeeded at tier 3 after tier 1 declined says something a bare "ok" does
not.

**Conditions, because success is not observable by default.** During
reconnaissance a trial was correctly discarded because "the state is X now"
was equally consistent with "the action worked" and "neither the setup nor
the action did anything". For a tool whose purpose is testing, an action
that cannot distinguish success from a no-op manufactures false passes.

So a declared `expect_after` that cannot be verified makes the action
*fail*, and a declared `expect_before` that does not hold means it never
runs. That belongs here rather than in the discipline of whoever writes the
test, because the person writing the test is the person who most wants it to
pass.

**Evidence, separate from the verdict.** An action reports what else
happened while it ran -- a dialog that appeared, the application becoming
held, the target taking the foreground. None of it changes `ok`. A dialog
may be the application rejecting what was sent or the confirmation the
action was meant to raise, and a result that guessed would be wrong in
whichever direction it guessed. The caller has the context to tell them
apart; this makes sure the caller has the observation too.

Pure orchestration: the primitives are injected, so the ladder, the
fallback and the condition logic are all testable without a desktop.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum

from .disturbance import Snapshot, compare
from .model.result import ActionResult, ErrorKind


class Tier(IntEnum):
    """Where in the stack an implementation lives (spec section 3)."""

    UIA_PATTERN = 1
    MSAA_DEFAULT_ACTION = 2
    WINDOW_MESSAGE = 3
    SYNTHETIC_INPUT = 4
    CAPTURE_OCR = 5


#: Tiers a verb may use unless a caller says otherwise.
#:
#: Tier 4 is excluded, and its absence is the point. Synthetic input moves
#: the physical cursor and requires the target to be frontmost, which is the
#: exact interference this project exists to avoid -- an automation run that
#: reaches tier 4 has stopped being unattended. It is available, but only to
#: a caller who asks for it by name and has therefore thought about it.
DEFAULT_TIERS: tuple[Tier, ...] = (
    Tier.UIA_PATTERN, Tier.WINDOW_MESSAGE,
)

#: How long to let a target act before the *first* postcondition check. A
#: posted message is handled on the target's own thread, so an immediate
#: check races it and reports a failure that is really impatience.
SETTLE_SECONDS = 0.25

#: How long to keep checking before concluding the expectation will not
#: hold. Measured on a real target: a toolbar's popup menu became a window
#: 957ms after the click that opened it. A single check at 250ms declared
#: the click ineffective, fell through the ladder, and reported a working
#: control as unverified -- a false failure manufactured by a fixed wait.
#: So the wait is a deadline, not a delay: a fast target is verified on the
#: first poll, and a slow one is given until here.
VERIFY_TIMEOUT_SECONDS = 2.0

#: Gap between polls. Fine enough that a fast target is not held up, coarse
#: enough that polling a full-tree resolver is not itself the load.
POLL_SECONDS = 0.05


@dataclass(frozen=True, slots=True)
class Condition:
    """Something that must be true, and a name for it.

    The description is not decoration. It ends up in the failure a caller
    has to act on, and "postcondition failed" without it is a dead end.
    """

    check: Callable[[], bool]
    description: str

    def holds(self) -> bool:
        try:
            return bool(self.check())
        except Exception:
            # A condition that cannot be evaluated has not been met. Letting
            # the exception escape would turn an unverifiable action into a
            # crash, which tells a caller even less.
            return False


@dataclass
class Attempt:
    """One tier's implementation of a verb.

    `rank` orders attempts before tier does. The default ladder runs the
    lowest tier first; a verb that has measured a higher tier to be the
    hazard rather than the preference can rank it later without lying
    about which tier it is -- `tier_used` in the result stays the truth.
    """

    tier: Tier
    run: Callable[[], bool]
    rank: int = 0
    #: A name for the route, where one tier has more than one.
    name: str = ""


@dataclass
class Actuator:
    """Runs a verb down the ladder, under its conditions."""

    settle_seconds: float = SETTLE_SECONDS
    verify_timeout_s: float = VERIFY_TIMEOUT_SECONDS
    poll_seconds: float = POLL_SECONDS
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.monotonic
    tiers: tuple[Tier, ...] = DEFAULT_TIERS
    #: Takes a snapshot of everything worth comparing before and after. None
    #: means no watching -- the pure-logic tests pass nothing, and an action
    #: with no observer simply reports no disturbances rather than
    #: pretending it saw none.
    observe: Callable[[], Snapshot] | None = None
    #: Recorded so a caller can see what was skipped and why, rather than
    #: wondering why a tier it expected never ran.
    _skipped: list[str] = field(default_factory=list, repr=False)

    def perform(
        self,
        attempts: list[Attempt],
        *,
        expect_before: Condition | None = None,
        expect_after: Condition | None = None,
    ) -> ActionResult:
        started = self.now()
        before = self._look()

        if expect_before is not None and not expect_before.holds():
            # Not a failure of the action -- the action did not happen. A
            # caller that treats this as "it did not work" would retry, when
            # what is wrong is the state it expected to act on.
            return ActionResult(
                ok=False,
                precondition_verified=False,
                elapsed_ms=self._elapsed(started),
                disturbances=self._changes(before),
                error={
                    "kind": ErrorKind.NOT_ACTIONABLE.value,
                    "message": (
                        "precondition did not hold, so nothing was "
                        f"attempted: {expect_before.description}"
                    ),
                },
            )

        usable = [a for a in attempts if a.tier in self.tiers]
        if not usable:
            offered = sorted({a.tier.name for a in attempts})
            allowed = sorted(t.name for t in self.tiers)
            return ActionResult(
                ok=False,
                precondition_verified=(
                    True if expect_before is not None else None
                ),
                elapsed_ms=self._elapsed(started),
                disturbances=self._changes(before),
                error={
                    "kind": ErrorKind.TIER_EXHAUSTED.value,
                    "message": (
                        f"no permitted tier implements this verb: it offers "
                        f"{offered}, this actuator allows {allowed}"
                    ),
                },
            )

        attempted: list[int] = []
        declined: dict[str, str] = {}
        for attempt in sorted(usable, key=lambda a: (a.rank, a.tier)):
            attempted.append(int(attempt.tier))
            try:
                delivered = attempt.run()
            except Exception as exc:
                # Kept by route: a rung that raised had a reason, and a
                # live guard's abort is the one the operator most needs
                # to read (#124).
                declined[attempt.name or f"tier {int(attempt.tier)}"] = str(exc)
                delivered = False
            if not delivered:
                continue

            if expect_after is None:
                # Nothing was declared, so nothing is claimed beyond "the
                # message went out". postcondition_verified stays None
                # rather than True: unverified is not the same as verified.
                return ActionResult(
                    ok=True,
                    tier_used=int(attempt.tier),
                    route_used=attempt.name or None,
                    tiers_attempted=attempted,
                    precondition_verified=(
                        True if expect_before is not None else None
                    ),
                    elapsed_ms=self._elapsed(started),
                    disturbances=self._changes(before),
                )

            if self._verified(expect_after):
                return ActionResult(
                    ok=True,
                    tier_used=int(attempt.tier),
                    route_used=attempt.name or None,
                    tiers_attempted=attempted,
                    precondition_verified=(
                        True if expect_before is not None else None
                    ),
                    postcondition_verified=True,
                    elapsed_ms=self._elapsed(started),
                    disturbances=self._changes(before),
                )
            # The message was delivered and nothing changed. That is the
            # signature of a tier the target ignores -- a semantic message
            # to a class that never implemented it -- so keep going down
            # the ladder rather than reporting a success nobody can see.

        failed_after = expect_after is not None
        changes = self._changes(before)
        return ActionResult(
            ok=False,
            tiers_attempted=attempted,
            precondition_verified=True if expect_before is not None else None,
            postcondition_verified=False if failed_after else None,
            elapsed_ms=self._elapsed(started),
            disturbances=changes,
            declined=declined,
            error={
                "kind": (
                    ErrorKind.POSTCONDITION_FAILED.value if failed_after
                    else ErrorKind.TIER_EXHAUSTED.value
                ),
                "message": (
                    (
                        "every tier delivered but none produced the expected "
                        f"result: {expect_after.description if expect_after else '?'}"
                    )
                    if failed_after else
                    f"no tier could act on this element (tried {attempted})"
                ) + ("; declined: " + "; ".join(f"{k}: {v}" for k, v in declined.items())
                     if declined else ""),
            },
        )

    def _verified(self, condition: Condition) -> bool:
        """Poll `condition` until it holds or the deadline passes.

        A settle first, because the very first check almost always races
        the target. Then repeated checks up to `verify_timeout_s`, returning
        the moment it holds: a fast target costs one poll, a slow one is
        given the whole window, and only a target that never gets there is
        reported as not having done so.

        Falling through to the next tier therefore waits the full window.
        That is the price of not declaring a working control ineffective
        because its effect took a second to arrive, and it is paid only on
        the failing path.
        """
        self.sleep(self.settle_seconds)
        deadline = self.now() + self.verify_timeout_s
        while True:
            if condition.holds():
                return True
            remaining = deadline - self.now()
            if remaining <= 0:
                return False
            self.sleep(min(self.poll_seconds, remaining))

    def _look(self) -> Snapshot | None:
        """The observation, or nothing if it could not be taken.

        Guarded on both sides. Instrumentation must never be able to stop an
        action from running, and an observer that throws on the way in would
        do exactly that.
        """
        if self.observe is None:
            return None
        try:
            return self.observe()
        except Exception:
            return None

    def _changes(self, before: Snapshot | None) -> list[dict]:
        """What moved while the action ran.

        Failures here are swallowed on purpose: the observer is instrumen-
        tation, and an action that actually happened must not be reported as
        having crashed because the report about it could not be gathered.
        """
        after = self._look()
        if before is None or after is None:
            return []
        return [d.to_dict() for d in compare(before, after)]

    def _elapsed(self, started: float) -> int:
        return int((self.now() - started) * 1000)
