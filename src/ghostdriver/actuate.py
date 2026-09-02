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

Pure orchestration: the primitives are injected, so the ladder, the
fallback and the condition logic are all testable without a desktop.
"""

import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable

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

#: How long to let a target act before checking a postcondition. A posted
#: message is handled on the target's own thread, so an immediate check
#: races it and reports a failure that is really impatience.
SETTLE_SECONDS = 0.25


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
    """One tier's implementation of a verb."""

    tier: Tier
    run: Callable[[], bool]


@dataclass
class Actuator:
    """Runs a verb down the ladder, under its conditions."""

    settle_seconds: float = SETTLE_SECONDS
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.monotonic
    tiers: tuple[Tier, ...] = DEFAULT_TIERS
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

        if expect_before is not None and not expect_before.holds():
            # Not a failure of the action -- the action did not happen. A
            # caller that treats this as "it did not work" would retry, when
            # what is wrong is the state it expected to act on.
            return ActionResult(
                ok=False,
                precondition_verified=False,
                elapsed_ms=self._elapsed(started),
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
                error={
                    "kind": ErrorKind.TIER_EXHAUSTED.value,
                    "message": (
                        f"no permitted tier implements this verb: it offers "
                        f"{offered}, this actuator allows {allowed}"
                    ),
                },
            )

        attempted: list[int] = []
        for attempt in sorted(usable, key=lambda a: a.tier):
            attempted.append(int(attempt.tier))
            try:
                delivered = attempt.run()
            except Exception:
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
                    tiers_attempted=attempted,
                    precondition_verified=(
                        True if expect_before is not None else None
                    ),
                    elapsed_ms=self._elapsed(started),
                )

            self.sleep(self.settle_seconds)
            if expect_after.holds():
                return ActionResult(
                    ok=True,
                    tier_used=int(attempt.tier),
                    tiers_attempted=attempted,
                    precondition_verified=(
                        True if expect_before is not None else None
                    ),
                    postcondition_verified=True,
                    elapsed_ms=self._elapsed(started),
                )
            # The message was delivered and nothing changed. That is the
            # signature of a tier the target ignores -- a semantic message
            # to a class that never implemented it -- so keep going down
            # the ladder rather than reporting a success nobody can see.

        failed_after = expect_after is not None
        return ActionResult(
            ok=False,
            tiers_attempted=attempted,
            precondition_verified=True if expect_before is not None else None,
            postcondition_verified=False if failed_after else None,
            elapsed_ms=self._elapsed(started),
            error={
                "kind": (
                    ErrorKind.POSTCONDITION_FAILED.value if failed_after
                    else ErrorKind.TIER_EXHAUSTED.value
                ),
                "message": (
                    (
                        "every tier delivered but none produced the expected "
                        f"result: {expect_after.description}"
                    )
                    if failed_after else
                    f"no tier could act on this element (tried {attempted})"
                ),
            },
        )

    def _elapsed(self, started: float) -> int:
        return int((self.now() - started) * 1000)
