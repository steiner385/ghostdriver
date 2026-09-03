"""Waiting, tested by arithmetic rather than by sleeping through it."""

import pytest

from ghostdriver.model.window import WindowNode
from ghostdriver.wait import Condition, holds, wait_for


def node(visible=True, enabled=True, responsive=True, handle=1):
    return WindowNode(
        handle=handle, class_name="Thing", text="", rect=(0, 0, 10, 10),
        visible=visible, enabled=enabled, pid=1, responsive=responsive,
    )


class Clock:
    """A clock that only moves when something sleeps on it."""

    def __init__(self):
        self.t = 0.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


def series(*rounds):
    """A resolver returning each round in turn, then repeating the last."""
    remaining = list(rounds)

    def resolve():
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return resolve


# --- conditions ----------------------------------------------------------

def test_each_condition_reads_the_match_set():
    assert holds(Condition.PRESENT, [node()])
    assert not holds(Condition.PRESENT, [])
    assert holds(Condition.ABSENT, [])
    assert not holds(Condition.ABSENT, [node()])
    assert holds(Condition.VISIBLE, [node(visible=True)])
    assert not holds(Condition.VISIBLE, [node(visible=False)])
    assert holds(Condition.ENABLED, [node(enabled=True)])
    assert not holds(Condition.ENABLED, [node(enabled=False)])
    assert holds(Condition.RESPONSIVE, [node(responsive=True)])
    assert not holds(Condition.RESPONSIVE, [node(responsive=False)])


def test_a_condition_must_hold_for_every_match_not_merely_one():
    """Otherwise "wait until they are all visible" returns while half of
    them are not."""
    assert not holds(Condition.VISIBLE, [node(visible=True), node(visible=False)])


def test_responsive_is_not_the_same_as_visible():
    """A control can be on screen and not yet answering."""
    on_screen_but_silent = [node(visible=True, responsive=False)]
    assert holds(Condition.VISIBLE, on_screen_but_silent)
    assert not holds(Condition.RESPONSIVE, on_screen_but_silent)


# --- polling -------------------------------------------------------------

def test_something_already_true_costs_no_wait():
    """A caller should not pay a poll interval for a condition that already
    holds, and a zero timeout should still answer."""
    clock = Clock()
    result = wait_for(series([node()]), Condition.PRESENT, timeout_s=0,
                      now=clock.now, sleep=clock.sleep)

    assert result.ok
    assert result.polls == 1
    assert clock.slept == []


def test_it_keeps_polling_until_the_condition_holds():
    clock = Clock()
    result = wait_for(
        series([], [], [node()]), Condition.PRESENT,
        timeout_s=10, poll_s=0.5, now=clock.now, sleep=clock.sleep,
    )

    assert result.ok
    assert result.polls == 3
    assert clock.slept == [0.5, 0.5]


def test_a_timeout_reports_what_it_saw_rather_than_only_failing():
    clock = Clock()
    result = wait_for(
        series([node(visible=False)]), Condition.VISIBLE,
        timeout_s=1, poll_s=0.5, now=clock.now, sleep=clock.sleep,
    )

    assert not result.ok
    assert "timed out" in result.reason
    assert "1 match(es)" in result.reason, "found, but never became visible"
    assert result.matches, "the near-miss is returned for diagnosis"


def test_the_deadline_is_honoured():
    clock = Clock()
    result = wait_for(
        series([]), Condition.PRESENT,
        timeout_s=1, poll_s=0.4, now=clock.now, sleep=clock.sleep,
    )

    assert not result.ok
    # The last sleep is clamped to the deadline, so the wait ends when it
    # was asked to rather than at the next poll boundary.
    assert clock.now() == pytest.approx(1.0)
    assert result.elapsed_ms == pytest.approx(1000, abs=2)


def test_waiting_for_absence_works_when_nothing_ever_appears():
    clock = Clock()
    result = wait_for(series([]), Condition.ABSENT, timeout_s=5,
                      now=clock.now, sleep=clock.sleep)
    assert result.ok and result.polls == 1


# --- settling ------------------------------------------------------------

def test_settled_waits_for_the_count_to_stop_changing():
    """The case the validation run met: a surface probed too early answers
    accurately and uselessly. An embedded document reported no actionable
    content immediately after its tab opened, and forty-six actionable
    elements four hundred milliseconds later."""
    clock = Clock()
    filling = series([node()], [node(), node()],
                     [node(), node(), node()],
                     [node(), node(), node()],
                     [node(), node(), node()])
    result = wait_for(filling, Condition.SETTLED, timeout_s=10, poll_s=0.2,
                      settle_polls=2, now=clock.now, sleep=clock.sleep)

    assert result.ok
    assert len(result.matches) == 3, "the settled count, not the first one"


def test_settling_needs_consecutive_agreement():
    """A surface filling in bursts can produce two equal counts by
    coincidence between them."""
    clock = Clock()
    bursty = series([node()], [node()], [node(), node()],
                    [node(), node()], [node(), node()])
    result = wait_for(bursty, Condition.SETTLED, timeout_s=10, poll_s=0.1,
                      settle_polls=2, now=clock.now, sleep=clock.sleep)

    assert result.ok
    assert len(result.matches) == 2
    assert result.polls == 5, "the early pair did not satisfy it"


def test_settled_is_never_satisfied_by_nothing():
    """Zero matches are stable forever; reporting that as settled would
    turn "it never arrived" into success."""
    clock = Clock()
    result = wait_for(series([]), Condition.SETTLED, timeout_s=1, poll_s=0.4,
                      now=clock.now, sleep=clock.sleep)
    assert not result.ok


def test_the_resolver_is_called_afresh_every_poll():
    """Handles are recycled, so a stale tree answers about a window that no
    longer exists."""
    calls = []

    def resolve():
        calls.append(1)
        return [node()] if len(calls) >= 3 else []

    clock = Clock()
    wait_for(resolve, Condition.PRESENT, timeout_s=5, poll_s=0.1,
             now=clock.now, sleep=clock.sleep)
    assert len(calls) == 3
