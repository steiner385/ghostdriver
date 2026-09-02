"""Sessions, and the gate every tool call passes through."""

import json

import pytest

from ghostdriver.model.result import ErrorKind, GhostdriverError
from ghostdriver.policy import GuardVerdict, Tier
from ghostdriver.session import Profile, SessionManager

ALLOWED_CMD = [r"C:\App.exe", "/od", "http://devhost:8183/devenv/gateway"]
DEV_ONLY = Profile(environment_allowlist=("http://devhost:8183/*",))


def test_attaching_to_an_allowlisted_target_opens_a_session():
    manager = SessionManager()
    session = manager.attach(1234, command_line=ALLOWED_CMD, profile=DEV_ONLY)

    assert session.pid == 1234
    assert session.tier is Tier.READ_ONLY, "the safe default"
    assert manager.get(session.session_id) is session


def test_attaching_to_a_target_outside_the_allowlist_is_refused():
    """The validation gate for this iteration turns on exactly this."""
    manager = SessionManager()
    production = [r"C:\App.exe", "/od", "http://prodhost:8183/live/gateway"]

    with pytest.raises(GhostdriverError) as raised:
        manager.attach(1234, command_line=production, profile=DEV_ONLY)

    assert raised.value.kind is ErrorKind.DENIED_BY_ENVIRONMENT
    assert "prodhost" in raised.value.message
    assert manager.open_sessions() == [], "and no session is left behind"


def test_a_freshly_probed_profile_refuses_everything():
    """The probe emits environment_allowlist empty for curation. Until
    somebody curates it nothing is approved, and reading empty as "no
    restrictions" would make every new application automatable against
    production by default."""
    manager = SessionManager()

    with pytest.raises(GhostdriverError) as raised:
        manager.attach(1234, command_line=ALLOWED_CMD,
                       profile=Profile.unguarded())

    assert raised.value.kind is ErrorKind.DENIED_BY_ENVIRONMENT


def test_a_target_whose_endpoint_cannot_be_read_is_refused():
    manager = SessionManager()
    with pytest.raises(GhostdriverError):
        manager.attach(1234, command_line=[r"C:\App.exe"], profile=DEV_ONLY)


def test_an_override_attaches_and_leaves_the_verdict_on_the_record():
    """An override that erased the finding would defeat having checked."""
    manager = SessionManager()
    production = [r"C:\App.exe", "/od", "http://prodhost/live/gateway"]

    session = manager.attach(
        1234, command_line=production, profile=DEV_ONLY,
        override_environment=True,
    )

    assert session.guard.verdict is GuardVerdict.REFUSED
    assert session.guard.overridden
    assert session.summary()["environment"]["overridden"] is True


def test_the_summary_names_the_endpoint_that_was_checked():
    manager = SessionManager()
    session = manager.attach(1234, command_line=ALLOWED_CMD, profile=DEV_ONLY)

    endpoints = session.summary()["environment"]["endpoints"]
    assert endpoints == ["http://devhost:8183/devenv/gateway"]


# --- the gate ------------------------------------------------------------

def test_a_read_only_session_is_refused_an_action():
    manager = SessionManager()
    session = manager.attach(1234, command_line=ALLOWED_CMD, profile=DEV_ONLY)

    manager.authorize(session.session_id, "describe")

    with pytest.raises(GhostdriverError) as raised:
        manager.authorize(session.session_id, "click")
    assert raised.value.kind is ErrorKind.DENIED_BY_POLICY
    assert "read_only" in raised.value.message


def test_an_interactive_session_keeps_the_read_tools():
    manager = SessionManager()
    session = manager.attach(1234, command_line=ALLOWED_CMD, profile=DEV_ONLY,
                             tier=Tier.INTERACTIVE)

    manager.authorize(session.session_id, "describe")
    manager.authorize(session.session_id, "click")


def test_the_tier_cannot_be_changed_after_attach():
    """Raising it would mean the guarantee earlier calls were made under no
    longer describes the session."""
    manager = SessionManager()
    session = manager.attach(1234, command_line=ALLOWED_CMD, profile=DEV_ONLY)

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
    session = manager.attach(1234, command_line=ALLOWED_CMD, profile=DEV_ONLY)

    manager.release(session.session_id)
    manager.release(session.session_id)

    assert manager.open_sessions() == []


# --- denylist ------------------------------------------------------------

def test_a_denied_caption_is_refused_by_the_session():
    manager = SessionManager()
    guarded = Profile(
        environment_allowlist=("http://devhost:8183/*",),
        denylist=("*delete*", "*complete task*"),
    )
    session = manager.attach(1234, command_line=ALLOWED_CMD, profile=guarded)

    manager.check_caption(session.session_id, "Expand All")

    with pytest.raises(GhostdriverError) as raised:
        manager.check_caption(session.session_id, "Confirm Delete Record")
    assert raised.value.kind is ErrorKind.DENIED_BY_POLICY


# --- loading a curated document -----------------------------------------

def test_a_curated_profile_loads_its_policy(tmp_path):
    document = tmp_path / "profile.json"
    document.write_text(json.dumps({
        "matched_profile": "L1",
        "denylist": ["*delete*"],
        "environment_allowlist": ["http://devhost:8183/*"],
        "window_count": 435,
    }), encoding="utf-8")

    profile = Profile.load(document)

    assert profile.matched_profile == "L1"
    assert profile.denylist == ("*delete*",)
    assert profile.environment_allowlist == ("http://devhost:8183/*",)


def test_an_uncurated_probe_output_loads_as_no_policy(tmp_path):
    """What the probe actually emits: both fields present and empty."""
    document = tmp_path / "profile.json"
    document.write_text(json.dumps({
        "matched_profile": "L1", "denylist": [], "environment_allowlist": [],
    }), encoding="utf-8")

    profile = Profile.load(document)

    assert profile.environment_allowlist == ()
    with pytest.raises(GhostdriverError):
        SessionManager().attach(1, command_line=ALLOWED_CMD, profile=profile)


def test_an_unreadable_profile_raises_rather_than_defaulting(tmp_path):
    """Falling back to an empty profile would turn a typo in a path into an
    unguarded session."""
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    with pytest.raises(GhostdriverError) as raised:
        Profile.load(broken)
    assert raised.value.kind is ErrorKind.DENIED_BY_ENVIRONMENT

    with pytest.raises(GhostdriverError):
        Profile.load(tmp_path / "does-not-exist.json")
