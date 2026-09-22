"""The small items of the 2026-09-22 field feedback, backend-free
(#204, #205, #206, #207, #208)."""

import json
import os
from types import SimpleNamespace

import pytest

from ghostdriver.model.result import GhostdriverError
from ghostdriver.operator import ENV_VAR
from ghostdriver.policy import ConsentSource, Tier
from ghostdriver.session import Profile, SessionManager
from ghostdriver.tools import Toolbox
from ghostdriver.tools.guidance import NO_EFFECT_HINT, REQUIRE_ACTIVE_REFUSAL, TYPE_TEXT_MISS_HINT


@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "ops"))
    return Toolbox(SessionManager())


def attach(box, tier):
    pid = os.getpid()
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    return box.sessions.attach(pid, command_line=["pytest"], tier=tier, profile=Profile())


# --- #204 ------------------------------------------------------------------------

def test_attach_says_which_tools_the_tier_excludes(box):
    summary = attach(box, Tier.INTERACTIVE).summary()
    assert "grid_seek" in summary["not_at_this_tier"]
    assert "click" not in summary["not_at_this_tier"]


def test_a_full_session_excludes_nothing(box):
    assert "not_at_this_tier" not in attach(box, Tier.FULL).summary()


# --- #205 ------------------------------------------------------------------------

def test_wait_idle_without_an_indicator_waits_for_the_surface_and_says_so(box, monkeypatch):
    session = attach(box, Tier.READ_ONLY)
    digests = iter(["a", "b", "c", "c", "c", "c", "c", "c", "c", "c"])
    last = {"d": "a"}

    def surfaces(session_id, all_windows=False):
        last["d"] = next(digests, last["d"])
        return {"shape_digest": last["d"]}

    monkeypatch.setattr(box, "surfaces", surfaces)

    idle = box.wait_idle(session.session_id, timeout_s=5, poll_s=0.02, settle_s=0.1)

    assert idle["ok"] and idle["idle"] is True and idle["waited_on"] == "surface"
    assert "weaker evidence" in idle["note"]


def test_a_surface_that_never_settles_times_out_honestly(box, monkeypatch):
    session = attach(box, Tier.READ_ONLY)
    counter = {"n": 0}

    def surfaces(session_id, all_windows=False):
        counter["n"] += 1
        return {"shape_digest": str(counter["n"])}

    monkeypatch.setattr(box, "surfaces", surfaces)
    idle = box.wait_idle(session.session_id, timeout_s=0.3, poll_s=0.02, settle_s=0.2)
    assert not idle["ok"] and idle["error"]["kind"] == "timeout" and idle["waited_on"] == "surface"


# --- #206 ------------------------------------------------------------------------

def test_a_text_locator_with_surrounding_whitespace_is_told_the_match_is_exact(box, monkeypatch):
    monkeypatch.setattr(box, "_resolve", lambda session, where, all_windows: [])
    _node, failure = box._one(SimpleNamespace(session_id="s"), 'class=TEdit text=" / / "', False)
    assert failure["error"]["kind"] == "not_found"
    assert "exact match including the leading/trailing whitespace" in failure["error"]["message"]
    assert "a /regex/ can match without it" in failure["error"]["message"]


def test_a_trimmed_text_locator_gets_no_such_note(box, monkeypatch):
    monkeypatch.setattr(box, "_resolve", lambda session, where, all_windows: [])
    _node, failure = box._one(SimpleNamespace(session_id="s"), 'class=TEdit text="Save"', False)
    assert "whitespace" not in failure["error"]["message"]


# --- #207 ------------------------------------------------------------------------

def test_insert_first_is_read_and_matched(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"insert_first": ["TsfDBInputEdit", "TsfDB*Combo"]}))
    profile = Profile.load(path)
    assert profile.inserts_first("TsfDBInputEdit") and profile.inserts_first("TsfDBLookupCombo")
    assert not profile.inserts_first("TEdit") and not Profile().inserts_first("TsfDBInputEdit")
    path.write_text(json.dumps({"insert_first": "TsfDBInputEdit"}))
    with pytest.raises(GhostdriverError, match="insert_first"):
        Profile.load(path)


@pytest.mark.skipif(os.name != "nt", reason="the Windows ladder")
def test_insert_first_puts_the_insert_route_ahead_of_typing():
    from ghostdriver.backends.windows import verbs
    from ghostdriver.cadence import ROBOT

    def order(**kw):
        attempts = verbs.set_text(0x10, "x", cadence=ROBOT, allow_pattern=False, **kw)
        return [a.name for a in sorted(attempts, key=lambda a: (a.rank, a.tier))]

    assert order() == ["typed", "inserted"]
    assert order(insert_first=True) == ["inserted", "typed"]


# --- #208 ------------------------------------------------------------------------

def test_the_hints_say_what_the_field_asked_for():
    assert "first click may only give it the focus" in NO_EFFECT_HINT
    assert "not a retry" in NO_EFFECT_HINT
    assert "menu_by_keyboard" in REQUIRE_ACTIVE_REFUSAL and "TMenuForm" in REQUIRE_ACTIVE_REFUSAL
    assert "set_value" in TYPE_TEXT_MISS_HINT and "insert_first" in TYPE_TEXT_MISS_HINT
