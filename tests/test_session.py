"""Sessions, session-scoped consent, and the gate every call passes through."""

import json

import pytest

from ghostdriver.model.result import ErrorKind, GhostdriverError
from ghostdriver.policy import ConsentSource, Tier
from ghostdriver.session import ConsentRequired, Profile, SessionManager

CMD = [r"C:\App.exe", "/od", "http://devhost:8183/devenv/gateway"]


def allowed(manager, pid=1234):
    manager.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    return pid


# --- consent gates attaching --------------------------------------------

def test_a_target_nobody_has_decided_on_cannot_be_attached():
    """Nothing is automatable until someone says so."""
    manager = SessionManager()

    with pytest.raises(ConsentRequired) as raised:
        manager.attach(1234, command_line=CMD)

    assert raised.value.pid == 1234
    assert "grant_targets" in raised.value.message


def test_consent_required_is_a_question_not_a_refusal():
    """Not-yet-asked and refused are different states, and only one of them
    is worth putting to a person."""
    manager = SessionManager()
    manager.record_grant(1234, allowed=False, source=ConsentSource.ELICITED)

    with pytest.raises(GhostdriverError) as raised:
        manager.attach(1234, command_line=CMD)

    assert not isinstance(raised.value, ConsentRequired)
    assert raised.value.kind is ErrorKind.DENIED_BY_POLICY
    assert "restricted" in raised.value.message


def test_an_approved_target_attaches():
    manager = SessionManager()
    pid = allowed(manager)

    session = manager.attach(pid, command_line=CMD)

    assert session.pid == pid
    assert session.tier is Tier.READ_ONLY, "the safe default"
    assert session.grant.source is ConsentSource.ELICITED


def test_a_restriction_names_its_reason_back():
    manager = SessionManager()
    manager.record_grant(9, allowed=False, source=ConsentSource.OPERATOR_TOOL,
                         note="this one is production")

    with pytest.raises(GhostdriverError) as raised:
        manager.attach(9, command_line=CMD)

    assert "production" in raised.value.message


# --- consent is revisable, and revocation bites immediately -------------

def test_a_decision_can_be_changed_mid_session():
    """Someone doing a task changes their mind, and should not have to
    restart anything to do it."""
    manager = SessionManager()
    manager.record_grant(1, allowed=False, source=ConsentSource.ELICITED)
    manager.record_grant(1, allowed=True, source=ConsentSource.ELICITED)

    assert manager.attach(1, command_line=CMD)


def test_restricting_a_target_stops_a_session_already_open():
    """Otherwise "leave that one alone" only applies to work not yet
    started, which is not what anybody means by it."""
    manager = SessionManager()
    pid = allowed(manager)
    session = manager.attach(pid, command_line=CMD)
    manager.authorize(session.session_id, "describe")

    manager.record_grant(pid, allowed=False, source=ConsentSource.ELICITED)

    with pytest.raises(GhostdriverError) as raised:
        manager.authorize(session.session_id, "describe")
    assert raised.value.kind is ErrorKind.DENIED_BY_POLICY


def test_grants_are_listed_for_inspection():
    manager = SessionManager()
    manager.record_grant(1, allowed=True, source=ConsentSource.ELICITED)
    manager.record_grant(2, allowed=False, source=ConsentSource.ELICITED)

    grants = {g.pid: g.allowed for g in manager.grants()}
    assert grants == {1: True, 2: False}


# --- the gate ------------------------------------------------------------

def test_a_read_only_session_is_refused_an_action():
    manager = SessionManager()
    session = manager.attach(allowed(manager), command_line=CMD)

    manager.authorize(session.session_id, "describe")

    with pytest.raises(GhostdriverError) as raised:
        manager.authorize(session.session_id, "click")
    assert raised.value.kind is ErrorKind.DENIED_BY_POLICY
    assert "read_only" in raised.value.message


def test_an_interactive_session_keeps_the_read_tools():
    manager = SessionManager()
    session = manager.attach(allowed(manager), command_line=CMD,
                             tier=Tier.INTERACTIVE)

    manager.authorize(session.session_id, "describe")
    manager.authorize(session.session_id, "click")


def test_the_tier_cannot_be_changed_after_attach():
    """Raising it would mean the guarantee earlier calls were made under no
    longer describes the session."""
    manager = SessionManager()
    session = manager.attach(allowed(manager), command_line=CMD)

    with pytest.raises((AttributeError, TypeError)):
        session.tier = Tier.FULL


def test_a_call_against_an_unknown_session_is_not_found():
    manager = SessionManager()
    with pytest.raises(GhostdriverError) as raised:
        manager.authorize("nope", "describe")
    assert raised.value.kind is ErrorKind.NOT_FOUND


def test_releasing_twice_is_not_an_error():
    """A caller tidying up after a failure should not have to track whether
    it got far enough to open a session."""
    manager = SessionManager()
    session = manager.attach(allowed(manager), command_line=CMD)

    manager.release(session.session_id)
    manager.release(session.session_id)

    assert manager.open_sessions() == []


# --- denylist ------------------------------------------------------------

def test_a_denied_caption_is_refused_by_the_session():
    manager = SessionManager()
    session = manager.attach(
        allowed(manager), command_line=CMD,
        profile=Profile(denylist=("*delete*", "*complete task*")),
    )

    manager.check_caption(session.session_id, "Expand All")

    with pytest.raises(GhostdriverError) as raised:
        manager.check_caption(session.session_id, "Confirm Delete Record")
    assert raised.value.kind is ErrorKind.DENIED_BY_POLICY


# --- profile loading -----------------------------------------------------

def test_a_curated_profile_loads_its_denylist(tmp_path):
    document = tmp_path / "profile.json"
    document.write_text(json.dumps({
        "matched_profile": "L1",
        "denylist": ["*delete*"],
        "window_count": 435,
    }), encoding="utf-8")

    profile = Profile.load(document)

    assert profile.matched_profile == "L1"
    assert profile.denylist == ("*delete*",)


def test_an_unreadable_profile_raises_rather_than_defaulting(tmp_path):
    """Falling back silently would turn a typo in a path into a session with
    no denylist."""
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    with pytest.raises(GhostdriverError):
        Profile.load(broken)
    with pytest.raises(GhostdriverError):
        Profile.load(tmp_path / "does-not-exist.json")


def test_a_session_needs_no_profile_at_all():
    """The profile now carries only the caption denylist. A session without
    one is perfectly valid -- it simply denies no captions."""
    manager = SessionManager()
    session = manager.attach(allowed(manager), command_line=CMD)

    assert session.profile.denylist == ()
    manager.check_caption(session.session_id, "Delete Everything")


# --- consent covers a process tree ---------------------------------------

def tree_manager(parents: dict[int, int]) -> SessionManager:
    """A manager whose parent walk is a table, not psutil."""
    return SessionManager(parent_of=parents.get)


def test_a_child_process_inherits_its_ancestors_approval():
    """A browser's file dialog runs in a helper process with its own pid;
    it is the application the operator approved, not a new question."""
    manager = tree_manager({300: 200, 200: 100})
    manager.record_grant(100, allowed=True, source=ConsentSource.ELICITED, note="the browser")

    grant = manager.grant_for(300)

    assert grant is not None and grant.allowed
    assert grant.inherited_from == 100 and grant.pid == 300
    assert "via pid 100" in grant.describe()
    session = manager.attach(300, command_line=["dialog-helper"])
    assert session.pid == 300


def test_a_restriction_inherits_exactly_as_an_approval_does():
    manager = tree_manager({300: 200, 200: 100})
    manager.record_grant(100, allowed=False, source=ConsentSource.ELICITED,
                         note="production")

    with pytest.raises(GhostdriverError) as raised:
        manager.attach(300, command_line=["dialog-helper"])

    assert raised.value.kind is ErrorKind.DENIED_BY_POLICY
    assert "production" in raised.value.message


def test_a_decision_about_the_pid_itself_beats_an_inherited_one():
    manager = tree_manager({300: 100})
    manager.record_grant(100, allowed=True, source=ConsentSource.ELICITED)
    manager.record_grant(300, allowed=False, source=ConsentSource.OPERATOR_TOOL,
                         note="not this helper")

    grant = manager.grant_for(300)

    assert grant is not None and not grant.allowed and grant.inherited_from is None


def test_an_undecided_tree_is_still_a_question():
    manager = tree_manager({300: 200, 200: 100})

    assert manager.grant_for(300) is None
    with pytest.raises(ConsentRequired):
        manager.attach(300, command_line=["x"])


def test_the_parent_walk_survives_a_cycle_and_a_missing_parent():
    manager = tree_manager({300: 200, 200: 300})
    assert manager.grant_for(300) is None
    assert tree_manager({}).grant_for(300) is None


def test_revoking_the_ancestor_stops_a_session_on_the_child():
    manager = tree_manager({300: 100})
    manager.record_grant(100, allowed=True, source=ConsentSource.ELICITED)
    session = manager.attach(300, command_line=["helper"])
    manager.record_grant(100, allowed=False, source=ConsentSource.ELICITED)

    with pytest.raises(GhostdriverError) as raised:
        manager.authorize(session.session_id, "describe")

    assert raised.value.kind is ErrorKind.DENIED_BY_POLICY
