"""The ladder and the conditions, tested without a desktop.

The primitives are injected, so everything here is about *policy*: which
tier runs, when a failure falls through, and what an action is allowed to
claim about itself.
"""

from ghostdriver.actuate import Actuator, Attempt, Condition, Tier
from ghostdriver.model.result import ErrorKind


def always(value: bool):
    return lambda: value


def condition(value, description="a stated expectation"):
    """A condition whose answer can change between calls."""
    answers = list(value) if isinstance(value, list) else [value]

    def check():
        return answers.pop(0) if len(answers) > 1 else answers[0]

    return Condition(check=check, description=description)


class FakeClock:
    """Time that passes only when something sleeps.

    The actuator now polls its postcondition to a deadline, so a no-op sleep
    against the real clock would spin for the whole window. Advancing a fake
    clock on each sleep keeps the deadline logic real and the test instant.
    """

    def __init__(self) -> None:
        self.t = 0.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


def actuator(**kw):
    clock = FakeClock()
    kw.setdefault("sleep", clock.sleep)
    kw.setdefault("now", clock.now)
    act = Actuator(**kw)
    act.clock = clock  # type: ignore[attr-defined]
    return act


# --- the ladder ----------------------------------------------------------

def test_the_highest_permitted_tier_runs_first():
    ran = []
    result = actuator().perform([
        Attempt(Tier.WINDOW_MESSAGE, lambda: ran.append(3) or True),
        Attempt(Tier.UIA_PATTERN, lambda: ran.append(1) or True),
    ])

    assert ran == [1], "tier 1 answered, so tier 3 was never needed"
    assert result.ok and result.tier_used == 1


def test_a_declining_tier_falls_through_to_the_next():
    ran = []
    result = actuator().perform([
        Attempt(Tier.UIA_PATTERN, lambda: ran.append(1) or False),
        Attempt(Tier.WINDOW_MESSAGE, lambda: ran.append(3) or True),
    ])

    assert ran == [1, 3]
    assert result.ok and result.tier_used == 3
    assert result.tiers_attempted == [1, 3], "both are reported, not just the winner"


def test_a_tier_that_raises_is_treated_as_declining():
    """A primitive that throws has not actuated anything, and the ladder
    exists precisely so that one failing rung is not fatal."""
    def explode():
        raise OSError("COM is not available")

    result = actuator().perform([
        Attempt(Tier.UIA_PATTERN, explode),
        Attempt(Tier.WINDOW_MESSAGE, always(True)),
    ])

    assert result.ok and result.tier_used == 3


def test_exhausting_every_tier_reports_which_were_tried():
    result = actuator().perform([
        Attempt(Tier.UIA_PATTERN, always(False)),
        Attempt(Tier.WINDOW_MESSAGE, always(False)),
    ])

    assert not result.ok
    assert result.error["kind"] == ErrorKind.TIER_EXHAUSTED.value
    assert result.tiers_attempted == [1, 3]


def test_synthetic_input_is_not_used_unless_asked_for():
    """Tier 4 moves the physical cursor and needs the target frontmost.

    An automation run that reaches it has stopped being unattended, which
    is the interference this project exists to avoid -- so it is available
    only to a caller who names it and has therefore thought about it.
    """
    ran = []
    result = actuator().perform([
        Attempt(Tier.SYNTHETIC_INPUT, lambda: ran.append(4) or True),
    ])

    assert ran == [], "not attempted by default"
    assert not result.ok
    assert result.error["kind"] == ErrorKind.TIER_EXHAUSTED.value
    assert "SYNTHETIC_INPUT" in result.error["message"], "and says what it skipped"

    opted_in = actuator(tiers=(Tier.WINDOW_MESSAGE, Tier.SYNTHETIC_INPUT))
    assert opted_in.perform(
        [Attempt(Tier.SYNTHETIC_INPUT, always(True))]
    ).ok


# --- preconditions -------------------------------------------------------

def test_a_failing_precondition_stops_the_action_running():
    ran = []
    result = actuator().perform(
        [Attempt(Tier.WINDOW_MESSAGE, lambda: ran.append(3) or True)],
        expect_before=condition(False, "the dialog is open"),
    )

    assert ran == [], "nothing was attempted"
    assert not result.ok
    assert result.precondition_verified is False
    assert "the dialog is open" in result.error["message"]


def test_a_failed_precondition_is_not_reported_as_a_failed_action():
    """A caller that read it that way would retry, when what is wrong is
    the state it expected to act on."""
    result = actuator().perform(
        [Attempt(Tier.WINDOW_MESSAGE, always(True))],
        expect_before=condition(False),
    )

    assert result.error["kind"] == ErrorKind.NOT_ACTIONABLE.value
    assert result.error["kind"] != ErrorKind.TIER_EXHAUSTED.value


def test_a_holding_precondition_lets_the_action_run():
    result = actuator().perform(
        [Attempt(Tier.WINDOW_MESSAGE, always(True))],
        expect_before=condition(True),
    )

    assert result.ok and result.precondition_verified is True


# --- postconditions ------------------------------------------------------

def test_an_unverifiable_postcondition_fails_the_action():
    """The rule that stops false passes.

    Every tier delivered its message and nothing observable changed. An
    action that reported success here would be indistinguishable from one
    that did nothing at all.
    """
    result = actuator().perform(
        [Attempt(Tier.WINDOW_MESSAGE, always(True))],
        expect_after=condition(False, "the click counter increased"),
    )

    assert not result.ok
    assert result.postcondition_verified is False
    assert result.error["kind"] == ErrorKind.POSTCONDITION_FAILED.value
    assert "the click counter increased" in result.error["message"]


def test_a_delivered_but_ineffective_tier_falls_through():
    """The signature of a semantic message reaching a class that never
    implemented it: the send succeeds and nothing happens.

    Without this, the ladder would stop at the first tier that *accepted* a
    message rather than the first that *did* something -- which is exactly
    how a driver ends up believing BM_CLICK works.
    """
    ran = []
    result = actuator().perform(
        [
            Attempt(Tier.UIA_PATTERN, lambda: ran.append(1) or True),
            Attempt(Tier.WINDOW_MESSAGE, lambda: ran.append(3) or True),
        ],
        # Holds only once tier 3 has actually run, however often it is
        # polled -- tier 1 delivers, is given the whole window, and never
        # produces the effect.
        expect_after=Condition(lambda: 3 in ran, "the control acted"),
    )

    assert ran == [1, 3], "tier 1 delivered, achieved nothing, and gave way"
    assert result.ok and result.tier_used == 3
    assert result.postcondition_verified is True


def test_without_a_postcondition_nothing_is_claimed_about_the_effect():
    """`ok` then means the message went out, and the result says so by
    leaving verification unset rather than asserting True."""
    result = actuator().perform([Attempt(Tier.WINDOW_MESSAGE, always(True))])

    assert result.ok
    assert result.postcondition_verified is None, "unverified is not verified"


def test_the_settle_wait_happens_before_a_postcondition_is_checked():
    """A posted message is handled on the target's own thread. Checking
    immediately races it and reports impatience as failure."""
    order = []
    clock = FakeClock()

    def sleep(s):
        order.append(("slept", s))
        clock.sleep(s)

    act = Actuator(sleep=sleep, now=clock.now)
    act.perform(
        [Attempt(Tier.WINDOW_MESSAGE, lambda: order.append("sent") or True)],
        expect_after=Condition(
            check=lambda: order.append("checked") or True, description="x"
        ),
    )

    assert [o[0] if isinstance(o, tuple) else o for o in order] == [
        "sent", "slept", "checked"
    ]


# --- conditions ----------------------------------------------------------

def test_a_condition_that_raises_has_not_been_met():
    """Letting it escape would turn an unverifiable action into a crash,
    which tells a caller even less than a failure does."""
    def explode():
        raise RuntimeError("the window went away")

    assert not Condition(check=explode, description="x").holds()


def test_every_result_carries_how_long_it_took():
    result = actuator().perform([Attempt(Tier.WINDOW_MESSAGE, always(True))])
    assert result.elapsed_ms >= 0


# --- the postcondition is polled to a deadline, not sampled once ---------

def test_an_effect_that_arrives_late_is_still_verified():
    """Measured on a real target: a popup menu became a window 957ms after
    the click that opened it. A single check at 250ms called that click
    ineffective and fell through the ladder -- a false failure manufactured
    by a fixed wait."""
    act = actuator()
    ready_at = 0.95

    result = act.perform(
        [Attempt(Tier.WINDOW_MESSAGE, always(True))],
        expect_after=Condition(lambda: act.clock.now() >= ready_at,
                               "the menu window exists"),
    )

    assert result.ok and result.postcondition_verified is True
    assert result.tier_used == 3


def test_a_fast_effect_costs_one_poll():
    """Polling must not make the common case slower."""
    act = actuator()
    act.perform(
        [Attempt(Tier.WINDOW_MESSAGE, always(True))],
        expect_after=condition(True),
    )

    assert act.clock.slept == [act.settle_seconds], "settle, one check, done"


def test_an_effect_that_never_arrives_fails_at_the_deadline():
    """And not before: the deadline is the whole of the claim being made."""
    act = actuator()
    result = act.perform(
        [Attempt(Tier.WINDOW_MESSAGE, always(True))],
        expect_after=condition(False, "something that never happens"),
    )

    assert not result.ok
    waited = sum(act.clock.slept)
    assert waited >= act.settle_seconds + act.verify_timeout_s - 1e-9
    assert waited < act.settle_seconds + act.verify_timeout_s + act.poll_seconds


def test_the_deadline_is_per_tier():
    """Each rung is given the full window before the ladder moves on, so a
    slow effect is never mistaken for an ineffective tier."""
    act = actuator()
    ran = []
    act.perform(
        [
            Attempt(Tier.UIA_PATTERN, lambda: ran.append(1) or True),
            Attempt(Tier.WINDOW_MESSAGE, lambda: ran.append(3) or True),
        ],
        expect_after=condition(False),
    )

    assert ran == [1, 3]
    assert sum(act.clock.slept) >= 2 * (act.settle_seconds + act.verify_timeout_s) - 1e-9
