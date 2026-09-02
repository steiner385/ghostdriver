"""What phase 2 concludes from what it saw, with nothing actuated.

The acting is injected, so everything here is about judgement: which
evidence reaches the map, how disagreement is treated, and what a failure is
allowed to mean.
"""

import pytest

from ghostdriver.probe.phase2 import (ControlOutcome, SafeControl,
                                      actuation_map, focus_behavior, learn)


def outcome(class_name="TVendorButton", tier=3, verified=True, **kw):
    return ControlOutcome(
        locator=kw.pop("locator", f"class={class_name}"),
        class_name=class_name,
        tiers_attempted=kw.pop("tiers_attempted", [1, 3]),
        tier_used=tier,
        verified=verified,
        **kw,
    )


# --- what may be listed --------------------------------------------------

def test_a_control_without_an_expectation_is_refused():
    """Requiring it is what keeps `verified` meaning anything. A probe that
    recorded "the message went out" would be writing down exactly what this
    codebase refuses to call success."""
    with pytest.raises(ValueError, match="needs an expect"):
        SafeControl.from_dict({"locator": 'class=TButton text="Go"'})


def test_an_expectation_without_a_locator_is_refused():
    with pytest.raises(ValueError, match="needs an expect"):
        SafeControl.from_dict({"locator": "class=TButton", "expect": {}})


def test_a_control_without_a_locator_is_refused():
    with pytest.raises(ValueError, match="needs a locator"):
        SafeControl.from_dict({"expect": {"locator": "class=X"}})


def test_an_expectation_defaults_to_having_come_from_a_person():
    """The safer reading. A drafted guess has to say so explicitly, because
    saying so is what softens a failure into "maybe I guessed wrong"."""
    control = SafeControl.from_dict({
        "locator": "class=TButton", "expect": {"locator": "class=TStatus"},
    })

    assert control.expect_source == "operator"


# --- what reaches the map ------------------------------------------------

def test_a_refused_control_teaches_nothing():
    """A denylisted caption or a blocked application produces a refusal, and
    a refusal is not evidence about how a class actuates."""
    refused = ControlOutcome(locator="class=A", class_name="A",
                             refused="caption is on the denylist")

    assert actuation_map([refused]) == {}
    assert not refused.usable


def test_a_control_that_no_tier_reached_teaches_nothing():
    nothing = ControlOutcome(locator="class=A", class_name="A",
                             tiers_attempted=[1, 3], tier_used=None)

    assert actuation_map([nothing]) == {}


def test_the_tier_that_worked_is_recorded_by_its_mechanism():
    """The map is read by a person deciding whether to trust it, so it names
    the mechanism rather than a number."""
    learned = actuation_map([outcome(tier=3)])

    assert learned["TVendorButton"]["click"] == "wm_mouse_pair"
    assert learned["TVendorButton"]["verified"] is True
    assert learned["TVendorButton"]["samples"] == 1


# --- a class is only as strong as its weakest sample ---------------------

def test_one_unverified_sample_makes_the_class_unverified():
    """Otherwise the entry is a claim nobody checked, wearing a word that
    says somebody did."""
    learned = actuation_map([
        outcome(verified=True), outcome(verified=False),
    ])

    assert learned["TVendorButton"]["verified"] is False
    assert learned["TVendorButton"]["samples"] == 2


def test_disagreement_records_the_more_universal_tier():
    """If one button of a class answers at tier 1 and another does not, tier
    1 is not how the class actuates -- it is how that one control happened
    to respond, and a map recording it sends callers to a rung that works
    sometimes."""
    learned = actuation_map([outcome(tier=1), outcome(tier=3)])

    assert learned["TVendorButton"]["click"] == "wm_mouse_pair"


def test_disagreement_is_kept_rather_than_smoothed_over():
    """A reader deciding whether to trust this needs to see it."""
    learned = actuation_map([outcome(tier=1), outcome(tier=3)])

    assert "disagreement" in learned["TVendorButton"]
    assert "uia_pattern" in learned["TVendorButton"]["disagreement"]
    assert "wm_mouse_pair" in learned["TVendorButton"]["disagreement"]


def test_agreement_says_nothing_extra():
    learned = actuation_map([outcome(tier=3), outcome(tier=3)])

    assert "disagreement" not in learned["TVendorButton"]


def test_classes_are_learned_independently():
    learned = actuation_map([
        outcome(class_name="TVendorButton", tier=3),
        outcome(class_name="TNativeButton", tier=1),
    ])

    assert learned["TVendorButton"]["click"] == "wm_mouse_pair"
    assert learned["TNativeButton"]["click"] == "uia_pattern"


# --- focus behaviour -----------------------------------------------------

def test_a_target_that_never_grabs_says_so():
    assert focus_behavior([outcome(), outcome()]) == {
        "self_foregrounds_on_click": False, "samples": 2,
    }


def test_a_delay_is_a_range_not_an_average():
    """It decides how long a watchdog waits, and an average under-waits half
    the time."""
    behavior = focus_behavior([
        outcome(foreground_taken=True, foreground_delay_ms=300),
        outcome(foreground_taken=True, foreground_delay_ms=1300),
        outcome(),
    ])

    assert behavior["self_foregrounds_on_click"] is True
    assert behavior["delay_ms"] == [300, 1300]


def test_nothing_actuated_teaches_nothing_about_focus():
    """An empty dict, not a confident "it does not grab" -- which is what a
    reader would take `self_foregrounds_on_click: false` to mean."""
    assert focus_behavior([]) == {}
    assert focus_behavior([
        ControlOutcome(locator="a", class_name="A", refused="denylisted")
    ]) == {}


# --- the report ----------------------------------------------------------

def control(locator="class=A", source="operator"):
    return SafeControl(locator=locator, expect={"locator": "class=Status"},
                       expect_source=source)


def test_the_report_counts_what_was_tried_and_what_was_learned():
    controls = [control("class=A"), control("class=B")]
    outcomes = {
        "class=A": outcome(locator="class=A"),
        "class=B": ControlOutcome(locator="class=B", class_name="B",
                                  refused="caption is on the denylist"),
    }

    report = learn(controls, lambda c: outcomes[c.locator])

    assert report["attempted"] == 2
    assert report["learned"] == 1
    assert report["refused"] == [
        {"locator": "class=B", "reason": "caption is on the denylist"}
    ]


def test_a_failed_drafted_guess_reads_differently_from_a_failed_promise():
    """The distinction that makes drafting the expectations safe.

    A control held to a guess that did not hold may be fine -- the guess may
    be wrong. One held to what an operator said would happen is a finding
    about the control.
    """
    drafted = learn(
        [control("class=A", source="drafted")],
        lambda c: outcome(locator="class=A", verified=False,
                          expect_source="drafted",
                          observed=[{"change": "window_appeared",
                                     "detail": "Confirm"}]),
    )
    stated = learn(
        [control("class=B", source="operator")],
        lambda c: outcome(locator="class=B", verified=False,
                          expect_source="operator"),
    )

    assert "may be the guess that is wrong" in drafted["unverified"][0]["reading"]
    assert "what you said would be true was not" in stated["unverified"][0]["reading"]


def test_a_failure_carries_what_did_change():
    """Without it, "did not verify" is a dead end -- and repairing a drafted
    guess is exactly what this material is for."""
    report = learn(
        [control(source="drafted")],
        lambda c: outcome(verified=False, expect_source="drafted",
                          observed=[{"change": "window_appeared",
                                     "detail": "Confirm Delete Record"}]),
    )

    observed = report["unverified"][0]["observed"]
    assert observed[0]["detail"] == "Confirm Delete Record"


def test_a_clean_run_reports_nothing_unverified():
    report = learn([control()], lambda c: outcome())

    assert report["unverified"] == []
    assert report["refused"] == []
