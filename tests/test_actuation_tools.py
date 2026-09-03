"""The actuation tools: what they refuse, and what they claim.

Against the fixture, because every guarantee here is about a real target --
a locator that matches two things, a caption an operator forbade, a field
that takes only part of what it is given, an application that is held.
"""

import json
import subprocess
import sys
import time

import psutil
import pytest

from tests.conftest import on_windows

pytestmark = on_windows


@pytest.fixture
def app():
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp"],
        stdout=subprocess.PIPE, text=True,
    )
    handles = json.loads(proc.stdout.readline())
    time.sleep(0.4)
    try:
        yield handles
    finally:
        if handles["pid"] != proc.pid:
            try:
                psutil.Process(handles["pid"]).terminate()
            except psutil.Error:
                pass
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture
def box():
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    return Toolbox(SessionManager())


def interactive(box, pid, *, denylist=(), sensitivity=None):
    """A session allowed to act, with an optional curated profile."""
    from ghostdriver.policy import ConsentSource, Tier
    from ghostdriver.sensitivity import Sensitivity
    from ghostdriver.session import Profile

    box.sessions.record_grant(pid, allowed=True,
                              source=ConsentSource.ELICITED,
                              note="approved for this test")
    profile = Profile(
        denylist=tuple(denylist),
        sensitivity=sensitivity or Sensitivity(),
    )
    session = box.sessions.attach(pid, command_line=["fixtureapp"],
                                  tier=Tier.INTERACTIVE, profile=profile)
    return session.session_id


def status(box, session):
    return box.read(session, 'class=Static text="/clicks=.*/"')["values"][0]


# --- the tier boundary ---------------------------------------------------

def test_a_read_only_session_cannot_act(box, app):
    """The tier is the promise the session was opened under, so this is the
    guarantee everything else rests on."""
    from ghostdriver.policy import ConsentSource, Tier

    box.sessions.record_grant(app["pid"], allowed=True,
                              source=ConsentSource.ELICITED)
    session = box.sessions.attach(app["pid"], command_line=["fixtureapp"],
                                   tier=Tier.READ_ONLY).session_id

    result = box.click(session, 'class=GhostFixtureCommandButton '
                                'text="Expand All"')

    assert not result["ok"]
    assert result["error"]["kind"] == "denied_by_policy"


def test_a_restricted_target_stops_an_open_session_acting(box, app):
    """Revocation has to reach work already under way, or "leave that one
    alone" would only mean "do not start"."""
    session = interactive(box, app["pid"])
    box.sessions.record_grant(app["pid"], allowed=False,
                              source=ConsentSource_elicited())

    result = box.click(session, 'class=GhostFixtureCommandButton '
                                'text="Expand All"')

    assert not result["ok"]
    assert "no longer approved" in result["error"]["message"]


def ConsentSource_elicited():
    from ghostdriver.policy import ConsentSource

    return ConsentSource.ELICITED


# --- what actuation refuses ----------------------------------------------

def test_an_ambiguous_locator_is_refused_with_the_candidates(box, app):
    """A read of eight matching fields returns eight values and the caller
    sees what happened. A click on eight matching buttons picks one and the
    caller finds out afterwards."""
    session = interactive(box, app["pid"])

    result = box.click(session, "class=GhostFixtureCommandButton")

    assert not result["ok"]
    assert result["error"]["kind"] == "ambiguous"
    assert len(result["error"]["candidates"]) > 1
    assert "within=" in result["error"]["message"], "and says how to fix it"


def test_scoping_the_locator_makes_it_actionable(box, app):
    """The other half: the refusal is answerable."""
    session = interactive(box, app["pid"])

    result = box.click(
        session,
        'class=GhostFixtureCommandButton text="Apply" '
        'within=(class=GhostFixturePage text="Operations")',
        expect={"locator": 'class=Static text="/clicks=1 last=Apply/"'},
    )

    assert result["ok"], result.get("error")
    assert result["verified"] == "effect"


def test_a_denylisted_caption_is_refused_before_anything_is_sent(box, app):
    """Checked on the resolved caption, not the locator, so a locator that
    happens to match a forbidden control is caught even when it was not
    written to name one."""
    session = interactive(box, app["pid"], denylist=("*complete*",))
    before = status(box, session)

    result = box.click(session, 'class=GhostFixtureCommandButton '
                                'text="Complete Task"')

    assert not result["ok"]
    assert result["error"]["kind"] == "denied_by_policy"
    assert status(box, session) == before, "and nothing happened"


def test_a_missing_element_says_where_else_to_look(box, app):
    """Menus and dialogs are separate top-level windows, and a "not found"
    that did not search them is not evidence of absence."""
    session = interactive(box, app["pid"])

    result = box.click(session, 'class=NoSuchClass text="Nothing"')

    assert result["error"]["kind"] == "not_found"
    assert "all_windows" in result["error"]["message"]


def test_an_unknown_key_name_is_refused_rather_than_typed(box, app):
    """Otherwise "excape" is silently typed into the field as characters."""
    session = interactive(box, app["pid"])

    result = box.send_keys(session, "class=GhostFixtureBoundEdit",
                           ["excape"])

    assert not result["ok"]
    assert "excape" in result["error"]["message"]
    assert "escape" in result["error"]["message"], "and lists the real ones"


# --- what a result claims ------------------------------------------------

def test_without_an_expectation_only_delivery_is_claimed(box, app):
    """On this class of target, "the message went out" and "it worked" are
    genuinely different statements."""
    session = interactive(box, app["pid"])

    result = box.click(session, 'class=GhostFixtureCommandButton '
                                'text="Expand All"')

    assert result["ok"]
    assert result["verified"] == "delivery_only"


def test_an_expectation_that_does_not_hold_fails_the_action(box, app):
    session = interactive(box, app["pid"])

    result = box.click(session, 'class=GhostFixtureCommandButton '
                                'text="Expand All"',
                       expect={"locator": 'class=Static text="never"'})

    assert not result["ok"]
    assert result["error"]["kind"] == "postcondition_failed"


def test_a_result_names_the_tier_that_worked(box, app):
    """Reaching tier 3 after tier 1 declined says something a bare ok does
    not: this target publishes no pattern for that control."""
    session = interactive(box, app["pid"])

    result = box.click(session, 'class=GhostFixtureCommandButton '
                                'text="Expand All"')

    assert result["tiers_attempted"] == [1, 3]
    assert result["tier_used"] == 3


# --- set_value, and the two silent failures ------------------------------

def test_set_value_reports_display_verified_and_says_what_it_did_not_check(
    box, app
):
    """The contract: the display is always checked, the commit is not
    checked unless asked for, and the result says which it got."""
    session = interactive(box, app["pid"])

    result = box.set_value(session, "class=GhostFixturePlainEdit", "HELLO")

    assert result["ok"], result.get("error")
    assert result["verified"] == "display"
    assert ("whether the application accepted it was not checked"
            in result["unverified"])


def test_naming_where_the_value_lands_upgrades_it_to_committed(box, app):
    """The bound field: displaying a value and the application holding it
    are different, and only the caller knows where to look."""
    session = interactive(box, app["pid"])

    result = box.set_value(
        session, "class=GhostFixtureBoundEdit", "PART-0009",
        expect={"locator": 'class=Static text="committed:PART-0009"'},
    )

    assert result["ok"], result.get("error")
    assert result["verified"] == "committed"
    assert "unverified" not in result


def test_a_value_the_field_truncates_fails_and_shows_what_landed(box, app):
    """Caught without the caller asking for anything.

    A single-line field stops accepting keystrokes at its visible width, so
    a long value arrives as a silent prefix. The field's declared limit says
    thirty thousand, so there is nothing to check in advance -- only the
    read-back catches it.
    """
    session = interactive(box, app["pid"])
    long_value = "B" * 80

    result = box.set_value(session, "class=GhostFixturePlainEdit", long_value)

    assert not result["ok"]
    assert result["verified"] == "none"
    assert result["display"] and len(result["display"]) < len(long_value)
    assert long_value.startswith(result["display"])
    assert "expect_text" in result["error"]["message"], "and says what to do"


def test_expect_text_accepts_a_field_that_reformats_what_it_is_given(box, app):
    """The masked-field case. The reformatting becomes something the caller
    asserted rather than something they skimmed past."""
    session = interactive(box, app["pid"])
    long_value = "B" * 80

    first = box.set_value(session, "class=GhostFixturePlainEdit", long_value)
    assert not first["ok"]
    landed = first["display"]

    second = box.set_value(session, "class=GhostFixturePlainEdit", long_value,
                           expect_text=landed)

    assert second["ok"], second.get("error")
    assert second["verified"] == "display"


def test_the_pattern_tier_is_skipped_when_nothing_would_catch_it(box, app):
    """Tier 1 writes a control's text without the keyboard path running, so
    on a bound field it sets the display and commits nothing. With no commit
    expectation nothing would notice, so it is not offered."""
    session = interactive(box, app["pid"])

    result = box.set_value(session, "class=GhostFixtureBoundEdit", "TYPED")

    assert result["ok"], result.get("error")
    assert result["tiers_attempted"] == [3], "typed, and only typed"


def test_the_pattern_tier_is_offered_when_a_commit_check_would_catch_it(
    box, app
):
    """And then it falls through on its own, which is the ladder working."""
    session = interactive(box, app["pid"])

    result = box.set_value(
        session, "class=GhostFixtureBoundEdit", "CHECKED",
        expect={"locator": 'class=Static text="committed:CHECKED"'},
    )

    assert result["ok"], result.get("error")
    assert result["tiers_attempted"] == [1, 3]
    assert result["tier_used"] == 3


# --- cadence -------------------------------------------------------------

def test_the_profile_decides_the_cadence_when_the_caller_does_not(box, app):
    """The point of recording it: a session is told, rather than finding out
    by tripping the target."""
    from ghostdriver.sensitivity import Note, Sensitivity, Source

    session = interactive(box, app["pid"], sensitivity=Sensitivity(
        [Note(cadence="fast_human", source=Source.DECLARED)]
    ))

    result = box.set_value(session, "class=GhostFixturePlainEdit", "SLOW")

    assert result["ok"], result.get("error")
    assert result["cadence"] == "fast_human"


def test_the_caller_can_override_what_the_profile_says(box, app):
    from ghostdriver.sensitivity import Note, Sensitivity, Source

    session = interactive(box, app["pid"], sensitivity=Sensitivity(
        [Note(cadence="fast_human", source=Source.DECLARED)]
    ))

    result = box.set_value(session, "class=GhostFixturePlainEdit", "FAST",
                           cadence="robot")

    assert result["cadence"] == "robot"


def test_an_unannotated_target_types_at_full_speed(box, app):
    session = interactive(box, app["pid"])

    result = box.set_value(session, "class=GhostFixturePlainEdit", "X")

    assert result["cadence"] == "robot"


def test_an_unknown_cadence_is_refused(box, app):
    """Silently downgrading a caller who asked for pacing would mean they
    find out from the target."""
    session = interactive(box, app["pid"])

    result = box.set_value(session, "class=GhostFixturePlainEdit", "X",
                           cadence="humanish")

    assert not result["ok"]
    assert "unknown cadence" in result["error"]["message"]


# --- a held application --------------------------------------------------

def test_a_modal_stops_every_actuation_tool():
    """Posted messages do not respect modality, so without the precondition
    a driver would operate an application the user cannot touch."""
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp", "--modal-after", "300"],
        stdout=subprocess.PIPE, text=True,
    )
    handles = json.loads(proc.stdout.readline())
    box = Toolbox(SessionManager())
    try:
        time.sleep(0.7)
        session = interactive(box, handles["pid"])

        for call in (
            lambda: box.click(session, 'class=GhostFixtureCommandButton '
                                        'text="Expand All"'),
            lambda: box.set_value(session, "class=GhostFixturePlainEdit", "x"),
            lambda: box.type_text(session, "class=GhostFixturePlainEdit", "x"),
            lambda: box.send_keys(session, "class=GhostFixturePlainEdit",
                                  ["enter"]),
        ):
            result = call()
            assert not result["ok"]
            assert result["error"]["kind"] == "not_actionable"
            assert "modal" in result["error"]["message"]
    finally:
        try:
            psutil.Process(handles["pid"]).terminate()
        except psutil.Error:
            pass
        proc.terminate()
        proc.wait(timeout=5)


# --- disturbances reach the caller ---------------------------------------

def test_a_successful_action_still_reports_what_appeared_beside_it():
    """The case disturbances exist for: nothing the caller declared would
    ever have mentioned the dialog."""
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp", "--modal-after", "1200"],
        stdout=subprocess.PIPE, text=True,
    )
    handles = json.loads(proc.stdout.readline())
    box = Toolbox(SessionManager())
    try:
        time.sleep(0.4)
        session = interactive(box, handles["pid"])

        result = box.set_value(session, "class=GhostFixturePlainEdit",
                               "TYPED SLOWLY", cadence="fast_human")

        assert result["ok"], result.get("error")
        assert any("Confirm Delete Record" in d["detail"]
                   for d in result["disturbances"]), result["disturbances"]
    finally:
        try:
            psutil.Process(handles["pid"]).terminate()
        except psutil.Error:
            pass
        proc.terminate()
        proc.wait(timeout=5)


def test_an_ordinary_action_reports_no_disturbances(box, app):
    """Silence has to mean something."""
    session = interactive(box, app["pid"])

    result = box.click(session, 'class=GhostFixtureCommandButton '
                                'text="Expand All"')

    assert result["disturbances"] == []


def test_a_mistyped_expectation_says_so_instead_of_failing_the_action(box, app):
    """A malformed locator and an unmet expectation look identical from
    outside and mean opposite things.

    One says the application did not do what you expected; the other says
    you mistyped. Reported as the first, a caller goes looking at their
    target -- and since a bad locator can never hold, every action would
    fail and the target would look like it never responds.
    """
    session = interactive(box, app["pid"])

    result = box.click(
        session, 'class=GhostFixtureCommandButton text="Expand All"',
        # An unquoted regex: shlex splits it and `last=Apply/` is not a key.
        expect={"locator": 'class=Static text=/clicks=1 last=Apply/'},
    )

    assert not result["ok"]
    assert "expect is unusable" in result["error"]["message"]
    assert result["error"]["kind"] != "postcondition_failed"


# --- the sensitivity loop, driven by real actions ------------------------

def test_the_ledger_records_what_each_tool_actually_did(box, app):
    """The evidence a learned note rests on has to come from the server's
    own observations, so those observations have to exist."""
    session = interactive(box, app["pid"])

    box.set_value(session, "class=GhostFixturePlainEdit", "ONE")
    box.set_value(session, "class=GhostFixturePlainEdit", "TWO",
                  cadence="fast_human")

    seen = box.sessions.ledger.outcomes(session)
    assert [o.cadence for o in seen] == ["robot", "fast_human"]
    assert all(o.tool == "set_value" for o in seen)
    assert all(o.ok for o in seen)


def test_a_real_differential_is_measured_and_recorded(box, app, tmp_path):
    """The loop end to end, without seeding anything by hand.

    A value the field cannot take fails at robot cadence. The same value
    with an expectation that matches what the field will actually hold
    succeeds when paced. That is the shape of the experiment an agent runs
    when a target pushes back -- and it is the server, not the agent, that
    saw both halves.
    """
    import json

    from ghostdriver.session import Profile

    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"matched_profile": "L1", "denylist": []}),
                    encoding="utf-8")

    from ghostdriver.policy import ConsentSource, Tier

    box.sessions.record_grant(app["pid"], allowed=True,
                              source=ConsentSource.ELICITED)
    session = box.sessions.attach(
        app["pid"], command_line=["fixtureapp"], tier=Tier.INTERACTIVE,
        profile=Profile.load(path),
    ).session_id

    locator = "class=GhostFixturePlainEdit"
    long_value = "B" * 80

    failed = box.set_value(session, locator, long_value)
    assert not failed["ok"], "the field will not take all of it"
    landed = failed["display"]

    worked = box.set_value(session, locator, long_value,
                           expect_text=landed, cadence="fast_human")
    assert worked["ok"], worked.get("error")

    recorded = box.record_input_sensitivity(session)

    assert recorded["ok"] and recorded["written"], recorded
    written = json.loads(path.read_text())["input_sensitivity"]
    assert written[0]["source"] == "learned"
    assert locator in written[0]["evidence"]


def test_recording_is_refused_when_only_the_robot_attempt_ran(box, app,
                                                              tmp_path):
    """Half the evidence is not the evidence. A failure at speed is what an
    ordinary validation error looks like too."""
    import json

    from ghostdriver.policy import ConsentSource, Tier
    from ghostdriver.session import Profile

    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"matched_profile": "L1", "denylist": []}),
                    encoding="utf-8")
    box.sessions.record_grant(app["pid"], allowed=True,
                              source=ConsentSource.ELICITED)
    session = box.sessions.attach(
        app["pid"], command_line=["fixtureapp"], tier=Tier.INTERACTIVE,
        profile=Profile.load(path),
    ).session_id

    box.set_value(session, "class=GhostFixturePlainEdit", "B" * 80)

    recorded = box.record_input_sensitivity(session)

    assert not recorded["ok"]
    assert "cadence=fast_human" in recorded["error"]["message"]
    assert "input_sensitivity" not in json.loads(path.read_text())
