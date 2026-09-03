"""Cadence as arithmetic, with no window in sight.

The rhythm is the whole point of the feature, so it is tested where it can
be tested exactly: given text and a cadence, what pauses come out. Whether
the backend then sleeps through them is a separate question, checked against
a real target in `test_windows_actuate.py`.
"""

import random

import pytest

from ghostdriver.cadence import CADENCES, FAST_HUMAN, ROBOT, Cadence, by_name


def test_a_robot_waits_for_nothing():
    assert ROBOT.is_robot
    assert ROBOT.delays("hello world") == [0.0] * 11


def test_the_first_character_is_never_delayed():
    """Nothing precedes the first keystroke, so a leading pause would be
    latency the caller pays for no reason."""
    assert FAST_HUMAN.delays("abc")[0] == 0.0


def test_a_person_types_unevenly():
    """A uniform rhythm is its own tell, which is the thing being avoided --
    so jitter is a requirement, not a decoration."""
    delays = FAST_HUMAN.delays("aaaaaaaaaaaaaaaaaaaa",
                               rng=random.Random(7))[1:]

    assert len(set(delays)) > 1, "no two gaps the same"
    assert min(delays) >= (FAST_HUMAN.mean_ms - FAST_HUMAN.jitter_ms) / 1000
    assert max(delays) <= (FAST_HUMAN.mean_ms + FAST_HUMAN.jitter_ms) / 1000


def test_the_pause_lands_after_a_word_ends_not_before():
    """A typist slows at the end of a word, so the longer gap belongs to the
    character that follows the boundary."""
    quiet = Cadence("test", mean_ms=10.0, word_pause_ms=100.0)
    delays = quiet.delays("ab cd")

    # index:      0=a  1=b  2=space  3=c   4=d
    # the gap before 'c' is the one that follows the space.
    assert delays[3] == pytest.approx(0.110)
    assert delays[1] == pytest.approx(0.010)
    assert delays[4] == pytest.approx(0.010)


def test_a_gap_is_never_negative():
    """Jitter wider than the mean would otherwise ask the backend to sleep
    backwards."""
    wild = Cadence("wild", mean_ms=5.0, jitter_ms=50.0)

    assert all(d >= 0 for d in wild.delays("a" * 50, rng=random.Random(1)))


def test_an_estimate_says_what_a_long_field_will_cost():
    """Told in advance, because a human-paced memo is minutes and that is
    not something to discover from a timeout."""
    assert ROBOT.estimate_ms("x" * 500) == 0
    assert FAST_HUMAN.estimate_ms("x" * 21) == pytest.approx(1600, abs=100)

    memo = "word " * 400
    assert FAST_HUMAN.estimate_ms(memo) > 60_000, "minutes, and it says so"


def test_an_empty_or_single_character_string_costs_nothing():
    assert FAST_HUMAN.delays("") == []
    assert FAST_HUMAN.delays("x") == [0.0]
    assert FAST_HUMAN.estimate_ms("x") == 0


def test_an_unknown_cadence_is_an_error_not_a_robot():
    """Falling back silently would hand a caller who asked for human pacing
    a robot, and they would find out from the target -- the one place they
    did not want to."""
    assert by_name("fast_human") is FAST_HUMAN
    with pytest.raises(ValueError, match="unknown cadence"):
        by_name("humanish")


def test_every_named_cadence_is_reachable_by_its_own_name():
    assert all(by_name(name) is c for name, c in CADENCES.items())
