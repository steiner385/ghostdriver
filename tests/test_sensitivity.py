"""What is known about a target's appetite for machine-speed input."""

import pytest

from ghostdriver.cadence import FAST_HUMAN, ROBOT
from ghostdriver.sensitivity import (Note, Sensitivity, Source,
                                     learned_from_differential)


def declared(cadence="fast_human", surface="*"):
    return Note(cadence=cadence, source=Source.DECLARED, surface=surface)


def learned(cadence="fast_human", surface="*"):
    return Note(cadence=cadence, source=Source.LEARNED, surface=surface)


def test_a_target_nobody_has_said_anything_about_types_at_full_speed():
    """Robot is the default because most targets do not look, and paying
    human pacing everywhere would make every session minutes longer."""
    assert Sensitivity().cadence_for() is ROBOT


def test_a_declared_note_applies_before_any_session_has_run():
    """The whole point of declaring. The first encounter is the one that
    counts, and one failure mode -- accepted input, flagged server-side --
    is invisible, so nothing can be learned from it."""
    known = Sensitivity([declared()])

    assert known.cadence_for() is FAST_HUMAN


def test_a_note_about_one_surface_does_not_widen_to_the_whole_target():
    """A native shell hosting web content is two detectors in one window,
    and they will not agree."""
    known = Sensitivity([declared(surface="web")])

    assert known.cadence_for("web") is FAST_HUMAN
    assert known.cadence_for("native") is ROBOT


def test_a_specific_note_wins_over_a_blanket_one():
    """Otherwise a later catch-all silently overrides the careful answer."""
    known = Sensitivity([declared("robot", surface="*"),
                         declared("fast_human", surface="web")])

    assert known.cadence_for("web") is FAST_HUMAN
    assert known.cadence_for("native") is ROBOT


def test_declared_beats_learned_at_the_same_specificity():
    """A person who says so knows things a measurement cannot reach --
    including that the target flags without ever visibly refusing."""
    known = Sensitivity([learned("robot"), declared("fast_human")])

    assert known.cadence_for() is FAST_HUMAN


def test_recording_a_second_note_replaces_the_first_for_that_surface():
    """Two beliefs about one surface is not richer information; it is a
    contradiction the next reader has to arbitrate."""
    known = Sensitivity([declared("robot", surface="web")])
    known.record(declared("fast_human", surface="web"))

    assert len(known.notes) == 1
    assert known.cadence_for("web") is FAST_HUMAN


def test_recording_leaves_other_surfaces_alone():
    known = Sensitivity([declared("fast_human", surface="web")])
    known.record(declared("robot", surface="native"))

    assert known.cadence_for("web") is FAST_HUMAN
    assert len(known.notes) == 2


def test_a_learned_note_says_what_was_actually_seen():
    """"Learned" has to mean the differential held, not that something felt
    off -- so the note carries the observation that earned it."""
    note = learned_from_differential("web", 'set_text on "Part Number"')

    assert note.source is Source.LEARNED
    assert note.cadence == "fast_human"
    assert "failed at robot cadence" in note.evidence
    assert 'set_text on "Part Number"' in note.evidence
    assert note.recorded


def test_no_notes_and_a_note_saying_robot_read_differently():
    """One is ignorance, the other is a decision, and a session being told
    what is known needs to tell them apart."""
    assert Sensitivity().describe() == ""

    stated = Sensitivity([declared("robot")]).describe()
    assert "robot" in stated and "declared" in stated


def test_the_description_names_the_surface_and_the_source():
    known = Sensitivity([declared("fast_human", surface="web"),
                         learned("fast_human", surface="native")])
    line = known.describe()

    assert "web: fast_human (declared)" in line
    assert "native: fast_human (learned)" in line


def test_notes_survive_a_round_trip_through_the_document():
    known = Sensitivity([declared("fast_human", surface="web"),
                         learned("robot", surface="native")])

    revived = Sensitivity.from_list(known.to_list())

    assert revived.cadence_for("web") is FAST_HUMAN
    assert [n.source for n in revived.notes] == [Source.DECLARED,
                                                 Source.LEARNED]


def test_a_typo_in_a_hand_edited_note_is_loud():
    """This file is meant to be hand-edited, so a mistake in it must not
    resolve to the reassuring answer. A caller who asked for pacing and
    silently got a robot would find out from the target."""
    known = Sensitivity([declared("humanish")])

    with pytest.raises(ValueError, match="unknown cadence"):
        known.cadence_for()


def test_an_empty_document_section_loads_as_no_notes():
    assert Sensitivity.from_list(None).notes == []
    assert Sensitivity.from_list([]).cadence_for() is ROBOT


# --- the path from a hand-written file to a session ----------------------

def write_profile(tmp_path, **extra):
    import json

    document = {"matched_profile": "L1", "denylist": [], **extra}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def test_a_declared_note_reaches_the_session_summary(tmp_path):
    """The whole point of putting it in the file: a session is *told*.

    Learning it instead means learning it by tripping the target at machine
    speed, which is what the note exists to prevent.
    """
    from ghostdriver.session import Profile

    path = write_profile(tmp_path, input_sensitivity=[
        {"cadence": "fast_human", "source": "declared", "surface": "web",
         "evidence": "the hosted content counts input events"},
    ])
    profile = Profile.load(path)

    assert profile.sensitivity.cadence_for("web").name == "fast_human"
    assert "web: fast_human (declared)" in profile.sensitivity.describe()


def test_a_profile_with_no_section_loads_and_says_nothing(tmp_path):
    """Most profiles will not have one, and that has to stay ordinary."""
    from ghostdriver.session import Profile

    profile = Profile.load(write_profile(tmp_path))

    assert profile.sensitivity.describe() == ""
    assert profile.sensitivity.cadence_for().is_robot


def test_a_malformed_section_refuses_to_load_rather_than_defaulting(tmp_path):
    """Consistent with how the rest of this file is treated: a profile that
    fails to parse is an error, because falling back silently turns a typo
    into a session running at the wrong speed against a target that
    notices."""
    from ghostdriver.model.result import GhostdriverError
    from ghostdriver.session import Profile

    path = write_profile(tmp_path, input_sensitivity=[{"source": "declared"}])

    with pytest.raises(GhostdriverError, match="input_sensitivity"):
        Profile.load(path)


def test_the_session_summary_carries_it_to_every_caller(tmp_path):
    from ghostdriver.policy import ConsentSource
    from ghostdriver.session import SessionManager

    manager = SessionManager()
    manager.record_grant(4242, allowed=True, source=ConsentSource.ELICITED,
                         note="approved for this test")
    path = write_profile(tmp_path, input_sensitivity=[
        {"cadence": "fast_human", "source": "declared"},
    ])

    from ghostdriver.session import Profile

    session = manager.attach(4242, command_line=["app.exe"],
                             profile=Profile.load(path))
    summary = session.summary()

    assert "fast_human" in summary["input_sensitivity"]
    assert "declared" in summary["input_sensitivity"]


def test_a_session_with_nothing_known_says_nothing_at_all(tmp_path):
    """No key rather than an empty one: a caller should be able to tell
    "nobody has said" from "somebody said robot"."""
    from ghostdriver.policy import ConsentSource
    from ghostdriver.session import Profile, SessionManager

    manager = SessionManager()
    manager.record_grant(99, allowed=True, source=ConsentSource.ELICITED)
    session = manager.attach(99, command_line=["app.exe"],
                             profile=Profile.load(write_profile(tmp_path)))

    assert "input_sensitivity" not in session.summary()
