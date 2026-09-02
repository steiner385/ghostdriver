"""Closing the loop: a session that measures sensitivity can record it.

The interesting assertions here are the refusals. A note that later sessions
will trust must not be writable on a caller's say-so, and the one written
from a measurement must not overrule a person who said otherwise.
"""

import json

import pytest

from ghostdriver.ledger import Outcome
from ghostdriver.policy import ConsentSource, Tier
from ghostdriver.sensitivity import (Note, Sensitivity, Source,
                                     merge_into_document)
from ghostdriver.session import Profile, SessionManager
from ghostdriver.tools import Toolbox


@pytest.fixture
def box():
    return Toolbox(SessionManager())


def profile_file(tmp_path, notes=None, **extra):
    document = {"matched_profile": "L1", "denylist": [],
                "operator_notes": "kept by hand", **extra}
    if notes is not None:
        document["input_sensitivity"] = [n.to_dict() for n in notes]
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def session_on(box, path=None, pid=4242):
    box.sessions.record_grant(pid, allowed=True,
                              source=ConsentSource.ELICITED)
    profile = Profile.load(path) if path else Profile.none()
    return box.sessions.attach(pid, command_line=["app.exe"],
                                tier=Tier.INTERACTIVE,
                                profile=profile).session_id


def saw(box, session, ok, cadence, locator="class=Edit", tool="set_value",
        surface="native"):
    box.sessions.ledger.record(session, Outcome(
        locator=locator, tool=tool, cadence=cadence, ok=ok, surface=surface,
    ))


def differential(box, session, **kw):
    saw(box, session, False, "robot", **kw)
    saw(box, session, True, "fast_human", **kw)


# --- the refusals --------------------------------------------------------

def test_a_note_cannot_be_recorded_on_a_callers_say_so(box, tmp_path):
    """The party asking for a note recorded is the party that most wants it
    recorded, so its own account of its history is not evidence."""
    path = profile_file(tmp_path)
    session = session_on(box, path)

    result = box.record_input_sensitivity(session)

    assert not result["ok"]
    assert "nothing recorded here" in result["error"]["message"]
    assert "input_sensitivity" not in json.loads(path.read_text())


def test_a_refusal_says_which_half_of_the_evidence_is_missing(box, tmp_path):
    """The caller believes it saw something. A bare no leaves it guessing
    whether to retry, re-measure, or give up."""
    session = session_on(box, profile_file(tmp_path))
    saw(box, session, False, "robot")

    result = box.record_input_sensitivity(session)

    assert "cadence=fast_human" in result["error"]["message"]


def test_a_success_with_no_prior_failure_is_not_evidence(box, tmp_path):
    """The value may simply have been right that time."""
    session = session_on(box, profile_file(tmp_path))
    saw(box, session, True, "fast_human")

    result = box.record_input_sensitivity(session)

    assert not result["ok"]
    assert "nothing failed at robot cadence first" in result["error"]["message"]


def test_a_read_only_session_cannot_record_one(box, tmp_path):
    box.sessions.record_grant(99, allowed=True, source=ConsentSource.ELICITED)
    session = box.sessions.attach(
        99, command_line=["app.exe"], tier=Tier.READ_ONLY,
        profile=Profile.load(profile_file(tmp_path)),
    ).session_id
    differential(box, session)

    result = box.record_input_sensitivity(session)

    assert not result["ok"]
    assert result["error"]["kind"] == "denied_by_policy"


# --- what it writes ------------------------------------------------------

def test_a_measured_differential_is_written_to_the_profile(box, tmp_path):
    path = profile_file(tmp_path)
    session = session_on(box, path)
    differential(box, session)

    result = box.record_input_sensitivity(session)

    assert result["ok"] and result["written"]
    written = Sensitivity.from_list(
        json.loads(path.read_text())["input_sensitivity"]
    )
    # Against the surface it was measured on, not the whole target: the
    # evidence was about a native control and says nothing about the rest.
    assert written.cadence_for("native").name == "fast_human"
    assert written.notes[0].source is Source.LEARNED


def test_the_note_carries_the_observation_that_earned_it(box, tmp_path):
    """An operator reading the file later has to be able to judge it."""
    path = profile_file(tmp_path)
    session = session_on(box, path)
    differential(box, session, locator='class=Edit text="Part"')

    box.record_input_sensitivity(session, note="the field reverted silently")

    note = json.loads(path.read_text())["input_sensitivity"][0]
    assert "failed at robot cadence" in note["evidence"]
    assert 'class=Edit text="Part"' in note["evidence"]
    assert "reverted silently" in note["evidence"]
    assert note["recorded"], "and when"


def test_the_note_is_recorded_against_the_surface_that_needed_it(box, tmp_path):
    """A native shell hosting web content is two detectors, so a note about
    one must not slow typing in the other."""
    path = profile_file(tmp_path)
    session = session_on(box, path)
    differential(box, session, surface="web")

    box.record_input_sensitivity(session)

    written = Sensitivity.from_list(
        json.loads(path.read_text())["input_sensitivity"]
    )
    assert written.cadence_for("web").name == "fast_human"
    assert written.cadence_for("native").is_robot


def test_everything_else_in_the_document_survives(box, tmp_path):
    """These files are hand-curated, so a writer that rebuilt the document
    from what this process happens to know would quietly drop the rest."""
    path = profile_file(tmp_path)
    session = session_on(box, path)
    differential(box, session)

    box.record_input_sensitivity(session)

    document = json.loads(path.read_text())
    assert document["operator_notes"] == "kept by hand"
    assert document["matched_profile"] == "L1"


def test_a_session_with_no_profile_gets_the_note_to_hand_over(box):
    """Writing a file nobody pointed at would be a side effect nobody asked
    for -- but the measurement is still worth something."""
    session = session_on(box)
    differential(box, session)

    result = box.record_input_sensitivity(session)

    assert result["ok"] and not result["written"]
    assert result["note"]["cadence"] == "fast_human"
    assert "operator" in result["reason"]


# --- what it will not overwrite ------------------------------------------

def test_a_measurement_does_not_overrule_a_person(box, tmp_path):
    """A person who declared robot knows things a measurement cannot reach.
    A session that measured otherwise has not disproved them."""
    declared = Note(cadence="robot", source=Source.DECLARED, surface="*",
                    evidence="this target does not inspect input")
    path = profile_file(tmp_path, notes=[declared])
    session = session_on(box, path)
    differential(box, session)

    result = box.record_input_sensitivity(session)

    assert result["ok"] and not result["written"]
    assert "does not overrule" in result["reason"]
    still = json.loads(path.read_text())["input_sensitivity"]
    assert still[0]["source"] == "declared"


def test_a_measurement_cannot_overrule_a_person_at_a_finer_grain(tmp_path):
    """The hole the same rule nearly had.

    A learned note for one surface does not *replace* a blanket declared
    note -- but it beats it at act time, because specific wins over blanket.
    Checking only for a note on the same surface would have let a
    measurement override a person by writing at a finer grain.
    """
    path = profile_file(tmp_path, notes=[
        Note(cadence="robot", source=Source.DECLARED, surface="*"),
    ])

    outcome = merge_into_document(path, Note(
        cadence="fast_human", source=Source.LEARNED, surface="native",
    ))

    assert not outcome["written"]
    assert "everywhere" in outcome["reason"]
    assert Sensitivity.from_list(
        json.loads(path.read_text())["input_sensitivity"]
    ).cadence_for("native").is_robot


def test_a_declaration_about_another_surface_does_not_block_it(tmp_path):
    """The rule has to stop short of blanket refusal: a note about web
    content says nothing about the native shell."""
    path = profile_file(tmp_path, notes=[
        Note(cadence="fast_human", source=Source.DECLARED, surface="web"),
    ])

    outcome = merge_into_document(path, Note(
        cadence="fast_human", source=Source.LEARNED, surface="native",
    ))

    assert outcome["written"]


def test_a_learned_note_replaces_an_earlier_learned_one(tmp_path):
    """Two beliefs about one surface is a contradiction, not richer data."""
    path = profile_file(tmp_path, notes=[
        Note(cadence="robot", source=Source.LEARNED, evidence="an old run"),
    ])

    outcome = merge_into_document(path, Note(
        cadence="fast_human", source=Source.LEARNED, evidence="a newer run",
    ))

    assert outcome["written"]
    notes = json.loads(path.read_text())["input_sensitivity"]
    assert len(notes) == 1
    assert notes[0]["evidence"] == "a newer run"


def test_a_declared_note_may_still_be_declared_over(tmp_path):
    """The rule protects a person from a measurement, not from another
    person editing the same file."""
    path = profile_file(tmp_path, notes=[
        Note(cadence="robot", source=Source.DECLARED),
    ])

    outcome = merge_into_document(path, Note(
        cadence="fast_human", source=Source.DECLARED,
    ))

    assert outcome["written"]


def test_an_interrupted_write_cannot_leave_a_half_parsed_profile(tmp_path):
    """Written whole and moved into place. An operator whose profile was
    truncated mid-write would find every later session refusing to attach."""
    path = profile_file(tmp_path)
    merge_into_document(path, Note(cadence="fast_human",
                                   source=Source.LEARNED))

    assert json.loads(path.read_text()), "still valid JSON"
    assert not list(path.parent.glob("*.tmp")), "and no debris left behind"


# --- the loop, end to end ------------------------------------------------

def test_the_note_written_is_the_note_the_next_session_is_told(box, tmp_path):
    """The whole point. A later session reads this and is told, rather than
    finding out the way this one did."""
    path = profile_file(tmp_path)
    first = session_on(box, path)
    differential(box, first, surface="web")
    box.record_input_sensitivity(first)

    later = Profile.load(path)

    assert "web: fast_human (learned)" in later.sensitivity.describe()
    assert later.sensitivity.cadence_for("web").name == "fast_human"


def test_releasing_a_session_forgets_what_it_saw(box, tmp_path):
    """The evidence was about one session's work, and a later session on the
    same server did not see it."""
    path = profile_file(tmp_path)
    session = session_on(box, path)
    differential(box, session)
    box.sessions.release(session)

    assert box.sessions.ledger.outcomes(session) == []
