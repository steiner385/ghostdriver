"""Learning how a target's controls actuate, by actuating them.

Phase 1 is read-only and can say what a target *is*. It cannot say which
message makes a vendor button do something, because the only way to know
that is to send one and look. So phase 2 exists, and everything about it is
shaped by the fact that it is the one part of this tool that acts without a
task asking it to.

Three rules, from spec section 5.1, and none of them is negotiable:

- **The probe never chooses its own targets.** It actuates exactly the
  controls an operator listed, and nothing else. Not "controls that look
  safe", not "controls matching a pattern the probe inferred".
- **Every control carries what should be true afterwards.** A probe that
  recorded "tier 3 delivered a message" would be writing down the thing this
  whole codebase refuses to call success. `actuation_map` says `verified`,
  and it has to mean it.

  The expectation may be *drafted* rather than supplied, because an operator
  listing thirty controls should not have to write thirty predictions. But
  then a failed check has two possible meanings -- the control did nothing,
  or the guess was wrong -- and those must not be confused. Every outcome
  records which kind of expectation it was held to, and a failure carries
  what *did* change, so a wrong guess can be repaired rather than mistaken
  for a broken control.
- **Nothing is learned from a control that was refused.** A denylisted
  caption, a blocked application, an ambiguous locator: these produce a
  refusal in the report, never an entry in the map.

The aggregation here is pure, so what a class *means* can be tested without
a desktop. The acting is injected.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

#: How a tier reads in a profile document. The map is for a person deciding
#: whether to trust it, so it names the mechanism rather than a number.
TIER_METHOD: dict[int, str] = {
    1: "uia_pattern",
    2: "msaa_default_action",
    3: "wm_mouse_pair",
    4: "synthetic_input",
    5: "capture_ocr",
}


@dataclass(frozen=True, slots=True)
class SafeControl:
    """One control an operator has said may be actuated, and its proof.

    `expect` is the same shape the actuation tools take -- `{locator, text?,
    absent?}` -- because it is the same question: what will be true once
    this worked. Requiring it is what keeps `verified` honest.
    """

    locator: str
    expect: dict
    note: str = ""
    #: "operator" when a person wrote the expectation, "drafted" when it was
    #: inferred from reconnaissance. Carried all the way into the report,
    #: because it changes what a failure means.
    expect_source: str = "operator"

    @classmethod
    def from_dict(cls, raw: dict) -> "SafeControl":
        locator = raw.get("locator")
        if not locator:
            raise ValueError("a safe control needs a locator")
        expect = raw.get("expect")
        if not isinstance(expect, dict) or not expect.get("locator"):
            raise ValueError(
                f"safe control {locator!r} needs an expect naming what will "
                "be true after it actuates; without one nothing learned from "
                "it could be called verified"
            )
        return cls(locator=locator, expect=expect, note=raw.get("note", ""),
                   expect_source=raw.get("expect_source", "operator"))

    def to_dict(self) -> dict:
        return {"locator": self.locator, "expect": self.expect,
                "note": self.note, "expect_source": self.expect_source}


@dataclass(frozen=True, slots=True)
class ControlOutcome:
    """What happened when one listed control was actuated."""

    locator: str
    class_name: str
    tiers_attempted: list[int] = field(default_factory=list)
    tier_used: int | None = None
    verified: bool = False
    #: The target pulled itself to the front afterwards, and how long after.
    foreground_taken: bool = False
    foreground_delay_ms: int | None = None
    #: Set when the control was refused rather than tried. A refusal teaches
    #: nothing and must not reach the map.
    refused: str = ""
    #: Which kind of expectation this was held to.
    expect_source: str = "operator"
    #: Every tier sent its message and none produced the expected result.
    #: Distinct from `tier_used`, which means one of them *worked*: this
    #: control did something, or nothing, and the expectation could not tell
    #: -- which is the ordinary outcome of a drafted guess being wrong.
    delivered: bool = False
    #: What was seen to change around the action, whether or not the
    #: expectation held. On a failure this is the material for repairing a
    #: drafted guess; without it "did not verify" is a dead end.
    observed: list[dict] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Whether this taught the map anything.

        Deliberately narrow. A control that delivered without verifying
        teaches nothing about *which* tier drives its class -- a tier that
        cannot be shown to have worked is not a tier that works -- so it
        stays out of the map. It does not stay out of the report.
        """
        return not self.refused and self.tier_used is not None

    @property
    def reportable(self) -> bool:
        """Whether it happened at all, verified or not.

        The distinction that stops a control vanishing. One that actuated
        against a wrong guess is neither learned nor refused, and an earlier
        version listed it in neither -- so the single most likely outcome of
        drafting an expectation produced silence.
        """
        return not self.refused and (self.usable or self.delivered)


def actuation_map(outcomes: Iterable[ControlOutcome]) -> dict[str, dict]:
    """What was learned, per control class.

    A class entry is only as strong as its weakest sample, and that is the
    whole of the policy here.

    If one button of a class actuates at tier 1 and another does not, tier 1
    is not how that class actuates -- it is how that *one control* happened
    to respond, and a map recording it would send a caller to a rung that
    works sometimes. The lower, more universal tier is recorded instead and
    the disagreement is kept, because a reader deciding whether to trust
    this needs to see it.

    `verified` is true only when every sample verified. One unverified
    sample makes the class's entry a claim nobody checked.
    """
    by_class: dict[str, list[ControlOutcome]] = {}
    for outcome in outcomes:
        if not outcome.usable:
            continue
        by_class.setdefault(outcome.class_name, []).append(outcome)

    learned: dict[str, dict] = {}
    for class_name, samples in sorted(by_class.items()):
        tiers = sorted({s.tier_used for s in samples if s.tier_used})
        # The highest tier number is the lowest-level mechanism, and the one
        # every sample could fall back to.
        chosen = tiers[-1]
        entry: dict = {
            "click": TIER_METHOD.get(chosen, f"tier_{chosen}"),
            "verified": all(s.verified for s in samples),
            "samples": len(samples),
        }
        if len(tiers) > 1:
            entry["disagreement"] = (
                "controls of this class did not all actuate the same way ("
                + ", ".join(TIER_METHOD.get(t, f"tier_{t}") for t in tiers)
                + "); the most universal is recorded"
            )
        learned[class_name] = entry
    return learned


def focus_behavior(outcomes: Iterable[ControlOutcome]) -> dict:
    """Whether the target pulls itself to the front when acted on.

    Worth learning because it cannot be prevented -- the application is
    entitled to do it -- and a caller planning unattended work needs to know
    the desktop will be disturbed before it starts, not afterwards.

    The delay is a range rather than an average. It is used to decide how
    long a watchdog waits, and an average would under-wait half the time.
    """
    tried = [o for o in outcomes if o.usable]
    if not tried:
        return {}
    grabs = [o.foreground_delay_ms for o in tried
             if o.foreground_taken and o.foreground_delay_ms is not None]
    behavior: dict = {
        "self_foregrounds_on_click": bool(grabs),
        "samples": len(tried),
    }
    if grabs:
        behavior["delay_ms"] = [min(grabs), max(grabs)]
    return behavior


def learn(
    controls: Iterable[SafeControl],
    attempt: Callable[[SafeControl], ControlOutcome],
) -> dict:
    """Actuate each listed control and summarise what it taught.

    The acting is injected, so the ordering, the aggregation and the
    refusal accounting are testable without a desktop -- and so this module
    cannot accidentally acquire a way to actuate something on its own.
    """
    outcomes = [attempt(control) for control in controls]
    refused = [
        {"locator": o.locator, "reason": o.refused}
        for o in outcomes if o.refused
    ]
    # Named and explained, not just counted. A control that delivered and
    # did not verify is the interesting one, and which way it is interesting
    # depends on who wrote the expectation.
    unverified = [
        {
            "locator": o.locator,
            "class": o.class_name,
            "expect_source": o.expect_source,
            "tiers_attempted": o.tiers_attempted,
            "observed": o.observed,
            "reading": (
                "the control delivered but the drafted expectation did not "
                "hold; it may be the guess that is wrong rather than the "
                "control. What changed is listed, to repair it"
                if o.expect_source == "drafted" else
                "the control delivered and what you said would be true was "
                "not"
            ),
        }
        for o in outcomes if o.reportable and not o.verified
    ]
    return {
        "actuation_map": actuation_map(outcomes),
        "focus_behavior": focus_behavior(outcomes),
        "attempted": len(outcomes),
        "learned": sum(1 for o in outcomes if o.usable),
        # Acted on but not learned from. Separate from both counts, because
        # "we sent input to this control" is a thing an operator needs to
        # know happened whether or not it taught us anything.
        "actuated_without_learning": sum(
            1 for o in outcomes if o.delivered and not o.usable
        ),
        "refused": refused,
        # Named, not just counted. A control that delivered but could not be
        # verified is the interesting one: either the expectation is wrong
        # or the control does not do what the operator thought.
        "unverified": unverified,
    }
