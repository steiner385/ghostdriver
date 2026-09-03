"""The minimized-isolation watchdog as policy, with no desktop.

Observations go in, actions and events come out. The point of the module is
judgement -- when the target has escaped, what to report, and how not to
flap -- so that is what is tested here.
"""

from ghostdriver.isolation import (Action, FLAP_LIMIT, HOLD_AFTER_ACTION_S,
                                    Observation, Watchdog)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt
        return self.t


def watchdog():
    return Watchdog(now=Clock())


def quiet(at):
    return Observation(at=at, target_on_screen=False,
                       target_is_foreground=False)


def foreground(at):
    return Observation(at=at, target_on_screen=True,
                       target_is_foreground=True)


def restored(at):
    return Observation(at=at, target_on_screen=True,
                       target_is_foreground=False)


# --- the quiet case ------------------------------------------------------

def test_a_minimized_background_target_provokes_nothing():
    dog = watchdog()
    assert dog.observe(quiet(0.0)) is Action.NOTHING
    assert dog.observe(quiet(1.0)) is Action.NOTHING
    assert dog.events == []


# --- the event the whole strategy exists to produce ----------------------

def test_a_grab_is_captured_then_reminimized():
    """Section 7.2: a background app taking the foreground is almost always
    raising a modal, so the capture is the product and re-minimizing is the
    housekeeping."""
    dog = watchdog()
    dog.observe(quiet(0.0))

    action = dog.observe(foreground(0.9))

    assert action is Action.CAPTURE_THEN_MINIMIZE
    assert [e.kind for e in dog.events] == ["unexpected_foreground"]


def test_the_event_records_how_long_since_the_target_was_quiet():
    """From a single quiet observation this is the full gap; under the
    guard's continuous polling it is about one interval. Either way it marks
    that the target was quiet a moment ago and is not now."""
    dog = watchdog()
    dog.observe(quiet(0.0))
    dog.observe(foreground(0.957))

    assert dog.events[-1].after_quiet_s == 0.957


def test_a_restore_is_also_captured():
    """A window coming on screen is the whole question, whether or not it
    grabbed focus -- a modal often appears without taking the foreground.
    Capture is cheap and it is the value, so both escape kinds take one."""
    dog = watchdog()
    dog.observe(quiet(0.0))

    action = dog.observe(restored(0.5))

    assert action is Action.CAPTURE_THEN_MINIMIZE
    assert dog.events[-1].kind == "unexpected_restore"


# --- not flapping --------------------------------------------------------

def test_the_targets_own_restore_flicker_does_not_trigger_a_second_action():
    """After re-minimizing, the app re-shows its forms for a moment on its
    own thread. Sampling straight into that would act again and loop."""
    clock = Clock()
    dog = Watchdog(now=clock)
    dog.observe(quiet(clock.advance(0)))
    assert dog.observe(foreground(clock.advance(0.9))) is \
        Action.CAPTURE_THEN_MINIMIZE

    # Still on screen a moment later, inside the hold.
    assert dog.observe(foreground(clock.advance(0.05))) is Action.NOTHING
    assert len(dog.events) == 1, "one event, not one per sample"


def test_after_the_hold_a_still_present_grab_is_acted_on_again():
    """The hold is a debounce, not a blindfold: a window that is genuinely
    still up after the flicker window is put back again."""
    clock = Clock()
    dog = Watchdog(now=clock)
    dog.observe(quiet(clock.advance(0)))
    dog.observe(foreground(clock.advance(0.9)))
    clock.advance(HOLD_AFTER_ACTION_S + 0.01)

    assert dog.observe(foreground(clock())) is Action.CAPTURE_THEN_MINIMIZE


# --- losing gracefully ---------------------------------------------------

def test_a_target_that_fights_back_makes_the_watchdog_stand_down():
    """A window that keeps surfacing faster than it can be put back is not
    raising a dialog, it is fighting -- and turning the desktop into a
    flicker helps nobody. The watchdog stops acting and says so."""
    clock = Clock()
    dog = Watchdog(now=clock)
    dog.observe(quiet(clock()))

    actions = []
    for _ in range(FLAP_LIMIT + 3):
        clock.advance(HOLD_AFTER_ACTION_S + 0.01)
        actions.append(dog.observe(foreground(clock())))

    assert Action.NOTHING in actions, "it gave up acting at some point"
    assert any(e.kind == "watchdog_suspended" for e in dog.events)
    assert dog.suspended_reason


def test_a_suspended_watchdog_still_observes_but_does_not_act():
    clock = Clock()
    dog = Watchdog(now=clock)
    dog.observe(quiet(clock()))
    for _ in range(FLAP_LIMIT + 2):
        clock.advance(HOLD_AFTER_ACTION_S + 0.01)
        dog.observe(foreground(clock()))

    clock.advance(HOLD_AFTER_ACTION_S + 0.01)
    assert dog.observe(foreground(clock())) is Action.NOTHING


# --- draining for the caller ---------------------------------------------

def test_draining_hands_over_the_events_and_clears_them():
    """The agent asks periodically 'what happened while I was working'; each
    answer should be new, not the whole history again."""
    dog = watchdog()
    dog.observe(quiet(0.0))
    dog.observe(foreground(0.9))

    first = dog.drain()
    assert len(first) == 1
    assert dog.drain() == [], "already handed over"


def test_a_capture_is_attached_to_the_event_that_wanted_one():
    dog = watchdog()
    dog.observe(quiet(0.0))
    dog.observe(foreground(0.9))

    dog.attach_capture(b"\x89PNG-pretend")

    event = dog.events[-1]
    assert event.capture_png == b"\x89PNG-pretend"
    assert event.to_dict()["captured"] is True


def test_attaching_no_capture_is_harmless():
    dog = watchdog()
    dog.observe(quiet(0.0))
    dog.observe(restored(0.5))
    dog.attach_capture(None)

    assert dog.events[-1].capture_png is None
    assert dog.events[-1].to_dict()["captured"] is False


# --- you cannot escape a state you were never in -------------------------

def test_a_target_on_screen_at_the_start_is_not_reported_as_a_grab():
    """A freshly shown window owns the foreground. That is the opening
    state, not an escape, so it is put away without an event -- otherwise
    the watchdog cries wolf on every session's first sample."""
    clock = Clock()
    dog = Watchdog(now=clock)

    action = dog.observe(foreground(clock()))

    assert action is Action.MINIMIZE, "put it away to establish quiet"
    assert dog.events == [], "but do not report it as a grab"


def test_a_grab_after_a_baseline_is_reported():
    """Once quiet has been seen, the same foreground state is a real
    escape and does fire."""
    clock = Clock()
    dog = Watchdog(now=clock)
    dog.observe(foreground(clock()))          # opening minimize, no event
    dog.observe(quiet(clock.advance(0.3)))    # baseline established
    dog.observe(foreground(clock.advance(0.5)))

    assert [e.kind for e in dog.events] == ["unexpected_foreground"]


def test_minimized_but_still_owning_the_foreground_handle_is_quiet():
    """Minimizing without activating anything else leaves the minimized
    window owning the foreground handle -- measured against a real window.
    That is put away, not an escape."""
    dog = watchdog()
    seen = Observation(at=0.0, target_on_screen=False,
                       target_is_foreground=True)

    assert dog.observe(seen) is Action.NOTHING
    assert dog.events == []
