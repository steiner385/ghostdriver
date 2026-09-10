"""macro_replay (#87): binding, the dry-run plan, tier and profile checks --
with a backend-free session, so the logic is proven on any platform.

The pieces that need a target (the interference watch, the actuation) are
covered by the fixture smoke test at the bottom (`env: windows`); everything
above it runs against a session opened through `SessionManager.attach`, which
touches no backend, exactly as the tool-contract tests do.
"""

import json
import os
import sys

import pytest

from ghostdriver.operator import ENV_VAR
from ghostdriver.policy import ConsentSource, Tier
from ghostdriver.session import Profile, SessionManager
from ghostdriver.tools import Toolbox


@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "ops"))
    return Toolbox(SessionManager())


def attach(box, *, tier=Tier.INTERACTIVE, profile_id=""):
    """A session opened without a backend (its pid is this process's own;
    nothing ever acts on it in these tests)."""
    pid = os.getpid()
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    profile = Profile(profile_id=profile_id) if profile_id else Profile()
    return box.sessions.attach(pid, command_line=["pytest"], tier=tier,
                               profile=profile).session_id


TOGGLE = [{"tool": "click", "args": {"locator": "name=${plan}"},
           "expect": {"verified": "effect"}},
          {"when": {"locator": "class=Funnel", "pressed": True},
           "then": [{"tool": "click", "args": {"locator": "once"}}],
           "else": [{"tool": "click", "args": {"locator": "twice"}}]}]


# --- dry run: inspect without acting or being gated -----------------------

def test_dry_run_returns_the_plan_with_params_bound_and_does_not_act(box):
    box.macro_save("m", TOGGLE, tier="interactive",
                   params={"plan": {"required": True}})
    sid = attach(box)

    out = box.macro_replay(sid, "m", params={"plan": "PLAN-1"}, dry_run=True)

    assert out["ok"] and out["dry_run"] is True
    leaf, branch = out["plan"]
    assert leaf["args"]["locator"] == "name=PLAN-1"
    assert branch["when"] == "class=Funnel"
    assert [n["args"]["locator"] for n in branch["then"]] == ["once"]
    assert [n["args"]["locator"] for n in branch["else"]] == ["twice"]


def test_dry_run_marks_an_unbound_param_but_does_not_refuse(box):
    box.macro_save("m", [{"tool": "click", "args": {"locator": "${plan}"}}],
                   params={"plan": {"required": True}})
    sid = attach(box)

    out = box.macro_replay(sid, "m", dry_run=True)

    assert out["ok"] and out["missing_required"] == ["plan"]
    assert out["plan"][0]["unbound"] == ["plan"]


def test_dry_run_is_allowed_even_below_the_macro_tier(box):
    box.macro_save("m", [{"tool": "click", "args": {"locator": "x"}}], tier="full")
    sid = attach(box, tier=Tier.READ_ONLY)

    assert box.macro_replay(sid, "m", dry_run=True)["ok"], "inspection is safe"


# --- a real run is bound or refused, and gated by tier --------------------

def test_a_real_run_refuses_an_unbound_required_param(box):
    box.macro_save("m", [{"tool": "click", "args": {"locator": "${plan}"}}],
                   tier="interactive", params={"plan": {"required": True}})
    sid = attach(box)

    out = box.macro_replay(sid, "m")

    assert not out["ok"] and "needs param(s) ['plan']" in out["error"]["message"]


def test_a_real_run_refuses_a_session_below_the_macro_tier(box):
    box.macro_save("m", [{"tool": "click", "args": {"locator": "x"}}], tier="interactive")
    sid = attach(box, tier=Tier.READ_ONLY)

    out = box.macro_replay(sid, "m")

    assert not out["ok"] and out["error"]["kind"] == "denied_by_policy"
    assert "interactive" in out["error"]["message"]


# --- the profile-mismatch warning -----------------------------------------

def test_a_profile_mismatch_warns_but_does_not_refuse(box):
    box.macro_save("m", [{"tool": "click", "args": {"locator": "x"}}],
                   provenance={"recorded_against": "profA"})
    sid = attach(box, profile_id="profB")

    out = box.macro_replay(sid, "m", dry_run=True)

    assert out["ok"] and out["warnings"]
    assert "profA" in out["warnings"][0] and "profB" in out["warnings"][0]


def test_a_matching_profile_does_not_warn(box):
    box.macro_save("m", [{"tool": "click", "args": {"locator": "x"}}],
                   provenance={"recorded_against": "profA"})
    sid = attach(box, profile_id="profA")

    assert box.macro_replay(sid, "m", dry_run=True)["warnings"] == []


# --- the error paths ------------------------------------------------------

def test_an_unknown_session_is_refused(box):
    assert box.macro_replay("nope", "m", dry_run=True)["error"]["kind"] == "not_found"


def test_an_unknown_macro_is_refused(box):
    sid = attach(box)
    assert box.macro_replay(sid, "nope", dry_run=True)["error"]["kind"] == "not_found"


# --- the end-to-end run, against the fixture (env: windows) ----------------

@pytest.mark.skipif(sys.platform != "win32", reason="fixture-driven; Windows only")
def test_macro_replay_runs_the_body_and_writes_a_report(tmp_path, monkeypatch):
    """Save a tiny macro, attach to the fixture, replay it for real, and check
    the steps ran and a report landed. Needs the target, so it is the one
    Windows-only test here; the logic above is platform-neutral."""
    import subprocess

    monkeypatch.setenv(ENV_VAR, str(tmp_path / "ops"))
    proc = subprocess.Popen([sys.executable, "-m", "tests.fixtureapp"],
                            stdout=subprocess.PIPE, text=True)
    handles = json.loads(proc.stdout.readline())
    try:
        box = Toolbox(SessionManager())
        box.macro_save("expand", [
            {"tool": "click",
             "args": {"locator": 'class=GhostFixtureCommandButton text="Expand All"',
                      "expect": {"locator": 'class=Static text="/last=Expand All$/"'}}},
        ], tier="interactive")
        box.sessions.record_grant(handles["pid"], allowed=True,
                                  source=ConsentSource.ELICITED)
        sid = box.sessions.attach(handles["pid"], command_line=["fixtureapp"],
                                  tier=Tier.INTERACTIVE).session_id

        out = box.macro_replay(sid, "expand")

        assert out["ok"] and out["completed"] == 1
        assert out["steps"][0]["ok"]
        assert out["report_saved_to"] and os.path.exists(out["report_saved_to"])
    finally:
        proc.terminate()
        proc.wait(timeout=5)
