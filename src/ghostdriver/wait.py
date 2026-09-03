"""Waiting for a condition to hold.

GUI automation without waits is flaky by construction (spec §6.2). A screen
that is still drawing, a grid still filling, a dialog still opening — all of
them answer a query correctly and unhelpfully if asked too early. The
validation run met this directly: an embedded document probed immediately
after its tab opened reported no actionable content, and four hundred
milliseconds later reported forty-six actionable elements. Both readings
were accurate; only one was useful.

Pure, with the clock injected, so the timeout behaviour is tested by
arithmetic rather than by sleeping through it.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum

from .model.window import WindowNode


class Condition(str, Enum):
    """What is being waited for."""

    PRESENT = "present"
    ABSENT = "absent"
    VISIBLE = "visible"
    ENABLED = "enabled"
    #: Answered a text query, whatever it answered with. Distinct from
    #: VISIBLE: a control can be on screen and not yet talking.
    RESPONSIVE = "responsive"
    #: The count stopped changing between polls. For a surface that fills in
    #: progressively, "there is something there" is a weaker claim than
    #: "it has finished arriving".
    SETTLED = "settled"


def holds(condition: Condition, matches: Sequence[WindowNode]) -> bool:
    """Whether `condition` is satisfied by the current match set."""
    if condition is Condition.ABSENT:
        return not matches
    if not matches:
        return False
    if condition is Condition.PRESENT:
        return True
    if condition is Condition.VISIBLE:
        return all(n.visible for n in matches)
    if condition is Condition.ENABLED:
        # `actionable` where a backend computed it. Anyone waiting to act on
        # a control means "until I can act on it", and the window's own flag
        # answers yes for every control in a modally blocked application --
        # so the wait would return immediately and the action would then run
        # into the block.
        return all(
            n.enabled if n.actionable is None else n.actionable
            for n in matches
        )
    if condition is Condition.RESPONSIVE:
        return all(n.responsive for n in matches)
    return False  # SETTLED is decided across polls, not within one


@dataclass(frozen=True, slots=True)
class WaitResult:
    ok: bool
    condition: Condition
    polls: int
    elapsed_ms: int
    matches: tuple[WindowNode, ...] = ()
    reason: str = ""


def wait_for(
    resolve: Callable[[], Sequence[WindowNode]],
    condition: Condition = Condition.PRESENT,
    *,
    timeout_s: float = 10.0,
    poll_s: float = 0.15,
    settle_polls: int = 2,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> WaitResult:
    """Poll `resolve` until `condition` holds, or the timeout expires.

    `resolve` is called afresh each poll rather than being handed a tree,
    because the tree is what is changing: handles are recycled and a stale
    one answers about a window that no longer exists.

    The condition is checked *before* the first sleep. A caller waiting for
    something already true should not pay a poll interval for it, and a
    timeout of zero should still answer.
    """
    started = now()
    deadline = started + timeout_s
    polls = 0
    previous_count: int | None = None
    stable = 0
    matches: Sequence[WindowNode] = ()

    while True:
        matches = resolve()
        polls += 1

        if condition is Condition.SETTLED:
            count = len(matches)
            stable = stable + 1 if count == previous_count else 0
            previous_count = count
            # `settle_polls` *consecutive* identical readings, not merely two
            # that happen to agree. A surface filling in steadily can produce
            # a pair of equal counts by coincidence between bursts.
            satisfied = bool(matches) and stable >= settle_polls
        else:
            satisfied = holds(condition, matches)

        if satisfied:
            return WaitResult(
                ok=True,
                condition=condition,
                polls=polls,
                elapsed_ms=int((now() - started) * 1000),
                matches=tuple(matches),
                reason=f"{condition.value} after {polls} poll(s)",
            )

        if now() >= deadline:
            return WaitResult(
                ok=False,
                condition=condition,
                polls=polls,
                elapsed_ms=int((now() - started) * 1000),
                matches=tuple(matches),
                reason=(
                    f"timed out after {timeout_s}s with {len(matches)} "
                    f"match(es); {condition.value} never held"
                ),
            )
        # Never sleep past the deadline. Without this the wait overshoots
        # by up to a full poll interval, so a caller asking for one second
        # can wait one and a bit -- and a caller composing several waits
        # accumulates the error.
        sleep(min(poll_s, deadline - now()))
