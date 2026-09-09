"""batch (D#75) and pace (D#76), against the fixture.

The batch is only a dispatcher: every step runs the same Toolbox method a
standalone call runs, so these prove the dispatch, the stop-on-failure
semantics, the per-step verdicts, and -- the part that matters for safety --
that a step cannot reach a tool the allowlist withholds.
"""

import json
import subprocess
import sys
import time

import psutil
import pytest

from ghostdriver.policy import ConsentSource, Tier
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox
from tests.conftest import on_windows

pytestmark = on_windows


@pytest.fixture
def app():
    proc = subprocess.Popen([sys.executable, "-m", "tests.fixtureapp"],
                            stdout=subprocess.PIPE, text=True)
    handles = json.loads(proc.stdout.readline())
    time.sleep(0.4)
    yield handles
    if handles["pid"] != proc.pid:
        try:
            psutil.Process(handles["pid"]).terminate()
        except psutil.Error:
            pass
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def box():
    return Toolbox(SessionManager())


def interactive(box, pid):
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED,
                              note="approved for this test")
    return box.sessions.attach(pid, command_line=["fixtureapp"],
                               tier=Tier.INTERACTIVE).session_id


EXPAND = 'class=GhostFixtureCommandButton text="Expand All"'
COLLAPSE = 'class=GhostFixtureCommandButton text="Collapse All"'


# --- batch: the happy path and the verdicts ------------------------------

def test_a_batch_runs_every_step_and_reports_each_verdict(box, app):
    sid = interactive(box, app["pid"])

    result = box.batch(sid, [
        {"tool": "click", "args": {"locator": EXPAND,
                                   "expect": {"locator": 'class=Static text="/last=Expand All$/"'}}},
        {"tool": "click", "args": {"locator": COLLAPSE,
                                   "expect": {"locator": 'class=Static text="/last=Collapse All$/"'}}},
    ])

    assert result["ok"] and result["completed"] == 2 and result["stopped_at"] is None
    assert [s["tool"] for s in result["steps"]] == ["click", "click"]
    assert all(s["ok"] and s["verified"] == "effect" for s in result["steps"])


def test_a_step_without_an_expect_claims_only_delivery(box, app):
    sid = interactive(box, app["pid"])

    result = box.batch(sid, [{"tool": "click", "args": {"locator": EXPAND}}])

    assert result["ok"]
    assert result["steps"][0]["verified"] == "delivery_only"


# --- batch: stop-on-failure ----------------------------------------------

def test_a_failing_step_stops_the_batch_and_the_rest_do_not_run(box, app):
    sid = interactive(box, app["pid"])

    result = box.batch(sid, [
        {"tool": "click", "args": {"locator": EXPAND,
                                   "expect": {"locator": 'class=Static text="never happens"'}}},
        {"tool": "click", "args": {"locator": COLLAPSE}},
    ])

    assert not result["ok"]
    assert result["stopped_at"] == 0 and result["completed"] == 1
    assert len(result["steps"]) == 1, "the second step never ran"
    assert result["steps"][0]["ok"] is False


def test_stop_on_failure_false_runs_every_step(box, app):
    sid = interactive(box, app["pid"])

    result = box.batch(sid, [
        {"tool": "click", "args": {"locator": EXPAND,
                                   "expect": {"locator": 'class=Static text="never happens"'}}},
        {"tool": "click", "args": {"locator": COLLAPSE}},
    ], stop_on_failure=False)

    assert not result["ok"], "a step failed, so the batch is not ok"
    assert result["completed"] == 2 and result["stopped_at"] is None


# --- batch: the allowlist is the safety property -------------------------

@pytest.mark.parametrize("tool", ["attach", "release", "grant_targets",
                                  "launch_isolated", "foreground", "await_human"])
def test_a_lifecycle_or_consent_tool_is_refused_and_nothing_runs(box, app, tool):
    sid = interactive(box, app["pid"])

    result = box.batch(sid, [
        {"tool": "click", "args": {"locator": EXPAND}},
        {"tool": tool, "args": {}},
    ])

    assert not result["ok"]
    assert "cannot run in a batch" in result["error"]["message"]
    assert tool in result["error"]["message"]
    # The whole batch is refused before anything is sent: a batch that would
    # reach a withheld tool does not get to run its earlier steps either.
    assert "steps" not in result


def test_a_step_may_not_carry_its_own_session_id(box, app):
    sid = interactive(box, app["pid"])

    result = box.batch(sid, [{"tool": "click",
                              "args": {"session_id": "somewhere-else", "locator": EXPAND}}])

    assert not result["ok"] and "omit the session" in result["error"]["message"]

    # and the wire name (session_ref) is refused in a step too (#79).
    ref = box.batch(sid, [{"tool": "click",
                           "args": {"session_ref": "elsewhere", "locator": EXPAND}}])
    assert not ref["ok"] and "omit the session" in ref["error"]["message"]


def test_a_malformed_step_is_refused_by_shape(box, app):
    sid = interactive(box, app["pid"])

    assert not box.batch(sid, [{"args": {}}])["ok"]           # no tool
    assert not box.batch(sid, "click")["ok"]                    # not a list
    assert not box.batch(sid, [])["ok"]                         # empty
    bad_args = box.batch(sid, [{"tool": "click", "args": "x"}])
    assert not bad_args["ok"] and "args must be an object" in bad_args["error"]["message"]


def test_bad_arguments_to_a_step_are_that_step_s_failure(box, app):
    """A TypeError from a step's own args is a step failure, not a batch
    crash, so it obeys stop_on_failure like any other."""
    sid = interactive(box, app["pid"])

    result = box.batch(sid, [{"tool": "click", "args": {"no_such_arg": 1}}])

    assert not result["ok"] and result["stopped_at"] == 0
    assert "bad arguments" in result["steps"][0]["error"]["message"]


def test_a_read_only_session_cannot_act_through_a_batch(box, app):
    """The tier is enforced per step, so a batch grants nothing the session
    could not do standalone."""
    box.sessions.record_grant(app["pid"], allowed=True, source=ConsentSource.ELICITED)
    sid = box.sessions.attach(app["pid"], command_line=["fixtureapp"],
                              tier=Tier.READ_ONLY).session_id

    result = box.batch(sid, [{"tool": "click", "args": {"locator": EXPAND}}])

    assert not result["ok"] and result["steps"][0]["ok"] is False


# --- pace ----------------------------------------------------------------

def test_pace_dwells_for_about_the_requested_time(box, app):
    sid = interactive(box, app["pid"])

    started = time.monotonic()
    result = box.pace(sid, 0.2)
    elapsed = time.monotonic() - started

    assert result["ok"] and result["requested_s"] == 0.2
    assert 0.18 <= elapsed < 1.0
    assert "wait_idle" in result["note"] and "wait_for" in result["note"]


def test_pace_is_clamped(box, app):
    sid = interactive(box, app["pid"])
    box.PACE_MAX_S = 0.05  # so the test does not actually wait the cap

    result = box.pace(sid, 30.0)

    assert result["ok"] and result["capped_to_s"] == 0.05
    assert result["requested_s"] == 30.0
    assert "clamped" in result["note"]


def test_pace_refuses_a_non_positive_or_non_numeric_dwell(box, app):
    sid = interactive(box, app["pid"])

    assert not box.pace(sid, 0)["ok"]
    assert not box.pace(sid, -1)["ok"]
    assert not box.pace(sid, "soon")["ok"]
