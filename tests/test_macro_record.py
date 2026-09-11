"""macro recording (#88): capture_step's logic, the record lifecycle, and one
end-to-end capture against the fixture.

The capture rule and the record_start/save/discard bookkeeping are proven
against a backend-free session (`SessionManager.attach`), so they run on any
platform; the one test that exercises the wrapper actually buffering a real
call is the fixture-driven, Windows-only one at the bottom.
"""

import os
import sys

import pytest

from ghostdriver.operator import ENV_VAR
from ghostdriver.policy import ConsentSource, Tier
from ghostdriver.session import Profile, SessionManager
from ghostdriver.tools import Toolbox
from ghostdriver.tools.recording import capture_step


@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "ops"))
    return Toolbox(SessionManager())


def attach(box, *, tier=Tier.INTERACTIVE, profile_id="prof-1"):
    pid = os.getpid()
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    profile = Profile(profile_id=profile_id)
    return box.sessions.attach(pid, command_line=["pytest"], tier=tier,
                               profile=profile).session_id


# --- capture_step: what becomes a step, and how it is flagged -------------

def test_a_verified_click_is_captured_as_a_verified_step():
    step = capture_step("click",
                        {"session_id": "s", "locator": "name=Save",
                         "expect": {"locator": "name=Saved"}},
                        {"ok": True, "verified": "effect"})
    assert step == {"tool": "click",
                    "args": {"locator": "name=Save", "expect": {"locator": "name=Saved"}},
                    "verified": True, "delivery_only": False}


def test_an_unverified_click_is_captured_but_flagged_delivery_only():
    step = capture_step("click", {"session_id": "s", "locator": "name=X"},
                        {"ok": True, "verified": "delivery_only"})
    assert step["verified"] is False and step["delivery_only"] is True


def test_an_offset_click_is_delivery_only_whatever_the_verdict():
    step = capture_step("click", {"session_id": "s", "locator": "class=Grid",
                                  "at": {"x": 5, "y": 9}},
                        {"ok": True, "verified": "effect"})
    assert step["delivery_only"] is True, "an offset click can never be confirmed by locator"


def test_a_successful_wait_is_verified_by_construction():
    step = capture_step("wait_for", {"session_id": "s", "locator": "name=Ready"},
                        {"ok": True})
    assert step["verified"] is True and step["delivery_only"] is False


def test_a_read_is_not_recorded():
    assert capture_step("find", {"session_id": "s", "locator": "x"},
                        {"ok": True, "match_count": 1}) is None
    assert capture_step("describe", {"session_id": "s"}, {"ok": True}) is None


def test_a_failed_call_is_not_recorded():
    # a set_value refused because the field is protected never returns ok,
    # so a typed secret is never buffered.
    assert capture_step("set_value", {"session_id": "s", "locator": "pw", "text": "x"},
                        {"ok": False, "error": {"kind": "not_actionable"}}) is None


# --- the record lifecycle -------------------------------------------------

def test_record_start_opens_a_buffer_and_a_second_start_is_refused(box):
    sid = attach(box)

    started = box.record_start(sid)
    assert started["ok"] and started["recording"] is True
    assert sid in box._recordings

    again = box.record_start(sid)
    assert not again["ok"] and "already recording" in again["error"]["message"]


def test_record_save_writes_the_buffered_steps_with_provenance(box):
    sid = attach(box, tier=Tier.INTERACTIVE, profile_id="ca4904")
    box.record_start(sid)
    # simulate what the wrapper captures during the session
    box._recordings[sid]["steps"] = [
        {"tool": "click", "args": {"locator": "name=Save"}, "verified": True,
         "delivery_only": False},
        {"tool": "click", "args": {"locator": "class=Grid", "at": {"x": 1, "y": 2}},
         "verified": False, "delivery_only": True},
    ]

    saved = box.record_save(sid, "my-macro", description="did a thing")

    assert saved["ok"] and saved["recorded"] == 2 and saved["delivery_only"] == 1
    assert "delivery_only" in saved["note"]
    assert sid not in box._recordings, "the buffer is cleared on save"

    shown = box.macro_show("my-macro")
    assert shown["tier"] == "interactive", "the macro carries the tier it was recorded at"
    assert shown["provenance"]["recorded_against"] == "ca4904"
    assert shown["provenance"]["recorded_at"].endswith("Z")
    assert [s["tool"] for s in shown["steps"]] == ["click", "click"]
    assert shown["steps"][1]["delivery_only"] is True


def test_record_save_with_an_empty_buffer_is_refused_and_keeps_nothing(box):
    sid = attach(box)
    box.record_start(sid)

    result = box.record_save(sid, "empty")

    assert not result["ok"] and "nothing a macro can replay" in result["error"]["message"]
    assert box.macro_list()["total"] == 0


def test_record_save_without_recording_is_refused(box):
    sid = attach(box)
    result = box.record_save(sid, "m")
    assert not result["ok"] and "not recording" in result["error"]["message"]


def test_a_refused_save_keeps_the_recording(box, monkeypatch):
    sid = attach(box)
    box.record_start(sid)
    box._recordings[sid]["steps"] = [
        {"tool": "click", "args": {"locator": "x"}, "verified": True, "delivery_only": False}]
    # a name with a path separator is refused by save_workflow
    result = box.record_save(sid, "bad/name")
    assert not result["ok"]
    assert sid in box._recordings, "the buffer was put back, not lost"


def test_record_discard_throws_the_buffer_away(box):
    sid = attach(box)
    box.record_start(sid)

    discarded = box.record_discard(sid)
    assert discarded["ok"] and discarded["discarded"] is True
    assert sid not in box._recordings
    assert box.record_discard(sid)["discarded"] is False, "discarding nothing is not an error"


def test_recording_tools_refuse_an_unknown_session(box):
    assert box.record_start("nope")["error"]["kind"] == "not_found"
    assert box.record_save("nope", "m")["error"]["kind"] == "not_found"
    assert box.record_discard("nope")["error"]["kind"] == "not_found"


# --- end to end: the wrapper buffers a real call (env: windows) -----------

@pytest.mark.skipif(sys.platform != "win32", reason="fixture-driven; Windows only")
def test_recording_captures_a_real_click_and_replays_it(tmp_path, monkeypatch):
    import json
    import subprocess

    monkeypatch.setenv(ENV_VAR, str(tmp_path / "ops"))
    proc = subprocess.Popen([sys.executable, "-m", "tests.fixtureapp"],
                            stdout=subprocess.PIPE, text=True)
    handles = json.loads(proc.stdout.readline())
    try:
        box = Toolbox(SessionManager())
        box.sessions.record_grant(handles["pid"], allowed=True,
                                  source=ConsentSource.ELICITED)
        sid = box.sessions.attach(handles["pid"], command_line=["fixtureapp"],
                                  tier=Tier.INTERACTIVE).session_id

        box.record_start(sid)
        box.click(sid, 'class=GhostFixtureCommandButton text="Expand All"',
                  expect={"locator": 'class=Static text="/last=Expand All$/"'})
        box.find(sid, "class=Static")  # a read: must NOT be recorded
        saved = box.record_save(sid, "expand")

        assert saved["ok"] and saved["recorded"] == 1, "the click, not the find"
        shown = box.macro_show("expand")
        assert shown["steps"][0]["tool"] == "click"
        assert shown["steps"][0]["verified"] is True
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_a_verified_click_over_the_wire_is_not_flagged_an_offset_click():
    """The MCP layer passes every parameter explicitly, so a click arrives
    with at=None as a *present* key. Found on the first live shakedown against
    the VendorApp sandbox (#108): a verified tab switch was recorded delivery_only,
    and its args carried every default the wire sent. A None is "not given"."""
    wire_shaped = {"session_id": "s", "locator": "type=TabItem name=Parts",
                   "all_windows": False,
                   "expect": {"locator": "type=TabItem name=Parts", "selected": True},
                   "button": "left", "modifiers": None, "at": None, "count": 1,
                   "frame": "logical", "require_active": False}

    step = capture_step("click", wire_shaped, {"ok": True, "verified": "effect"})

    assert step["verified"] is True and step["delivery_only"] is False
    assert "at" not in step["args"] and "modifiers" not in step["args"], \
        "a None arg is not given, and must not be recorded"
    assert step["args"]["locator"] == "type=TabItem name=Parts"
    assert step["args"]["expect"]["selected"] is True, "the real expect is kept"


# --- #112: a recording keeps only what was asked --------------------------

CLICK_DEFAULTS = {"all_windows": False, "expect": None, "button": "left",
                  "modifiers": None, "at": None, "count": 1, "frame": "logical",
                  "require_active": False}


def test_args_equal_to_the_tool_default_are_not_recorded():
    """The wire passes every parameter explicitly; only `locator` and `expect`
    were asked for here, so only they should survive (#112)."""
    wire_shaped = {"session_id": "s", "locator": "type=TabItem name=Parts",
                   "all_windows": False,
                   "expect": {"locator": "type=TabItem name=Parts", "selected": True},
                   "button": "left", "modifiers": None, "at": None, "count": 1,
                   "frame": "logical", "require_active": False}

    step = capture_step("click", wire_shaped, {"ok": True, "verified": "effect"},
                        defaults=CLICK_DEFAULTS)

    assert set(step["args"]) == {"locator", "expect"}, step["args"]
    assert step["verified"] is True and step["delivery_only"] is False


def test_a_non_default_value_is_always_kept():
    wire_shaped = {"session_id": "s", "locator": "class=Grid", "all_windows": True,
                   "button": "right", "count": 2, "frame": "logical",
                   "require_active": False}

    step = capture_step("click", wire_shaped, {"ok": True, "verified": "delivery_only"},
                        defaults=CLICK_DEFAULTS)

    assert step["args"] == {"locator": "class=Grid", "all_windows": True,
                            "button": "right", "count": 2}, "the asked-for values stay"


def test_a_real_offset_is_kept_and_still_flags_delivery_only():
    wire_shaped = {"session_id": "s", "locator": "class=Grid", "at": {"x": 5, "y": 9},
                   "button": "left", "count": 1}

    step = capture_step("click", wire_shaped, {"ok": True, "verified": "effect"},
                        defaults=CLICK_DEFAULTS)

    assert step["args"]["at"] == {"x": 5, "y": 9}
    assert step["delivery_only"] is True, "a real offset is the least replayable step"


def test_without_defaults_only_none_values_are_dropped():
    """Callers that do not pass defaults get the #108 behaviour unchanged."""
    step = capture_step("click", {"session_id": "s", "locator": "x", "button": "left",
                                  "at": None},
                        {"ok": True, "verified": "effect"})
    assert step["args"] == {"locator": "x", "button": "left"}
