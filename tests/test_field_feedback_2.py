"""The second field report (D64), each item proven on the fixture.

Consent "evaporated" between an attach and the next call: the trace showed
a second chat, sharing the server, restricting the target. probe_grid gave
UNKNOWN on two grids and the session wondered if the probe had failed.
Posted row clicks selected in one grid and were ignored by another.
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

GRID = "class=GhostFixtureDataGrid"
ROW_1 = {"x": 30, "y": 25}
ROW_1_SELECTED = {"locator": 'class=Static text="/last=grid row=1$/"'}
ROW_2 = {"x": 30, "y": 45}
ROW_2_SELECTED = {"locator": 'class=Static text="/last=grid row=2$/"'}


def start(*args):
    proc = subprocess.Popen([sys.executable, "-m", "tests.fixtureapp", *args],
                            stdout=subprocess.PIPE, text=True)
    handles = json.loads(proc.stdout.readline())
    time.sleep(0.4)
    return proc, handles


def stop(proc, handles):
    if handles["pid"] != proc.pid:
        try:
            psutil.Process(handles["pid"]).terminate()
        except psutil.Error:
            pass
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def app():
    proc, handles = start()
    yield handles
    stop(proc, handles)


def session_for(pid, tier=Tier.INTERACTIVE):
    box = Toolbox(SessionManager())
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    return box, box.sessions.attach(pid, command_line=["fixtureapp"], tier=tier).session_id


# --- consent that "evaporated" ---------------------------------------------------------

def test_restricting_a_target_names_the_open_sessions_it_stops(app):
    box, session = session_for(app["pid"])

    out = box.grant_targets(restrict=[app["pid"]], note="the other chat said leave it alone")

    assert out["open_sessions_stopped"] == [session]
    assert "several chats" in out["caution"]


def test_a_refused_session_names_the_decision_and_the_way_back(app):
    box, session = session_for(app["pid"])
    box.grant_targets(restrict=[app["pid"]], note="the other chat said leave it alone")

    refused = box.describe(session)

    assert not refused["ok"]
    message = refused["error"]["message"]
    assert "restricted at" in message and "the other chat said leave it alone" in message
    assert f"allow=[{app['pid']}]" in message and "another chat" in message


def test_re_allowing_lets_the_same_session_continue(app):
    box, session = session_for(app["pid"])
    box.grant_targets(restrict=[app["pid"]])

    box.grant_targets(allow=[app["pid"]])

    assert box.describe(session)["ok"]


# --- an empty probe is an answer ---------------------------------------------------

def test_probe_grid_unknown_says_it_is_a_real_outcome():
    proc, handles = start("--grid-no-copy")
    try:
        box, session = session_for(handles["pid"], tier=Tier.FULL)

        report = box.probe_grid(session, GRID, allow_clipboard=True)

        assert report["ok"] and report["grid_strategy"] == "unknown", report
        assert "real outcome" in report["meaning"] and "capture" in report["meaning"]
    finally:
        stop(proc, handles)


# --- where the target thread's focus stands --------------------------------------

def test_a_click_reports_that_the_shell_is_its_threads_active_window(app):
    """Measured, against the first assumption: a window shown without
    activation is still its thread's active window."""
    box, session = session_for(app["pid"])

    result = box.click(session, GRID, at=ROW_1, expect=ROW_1_SELECTED)

    assert result["ok"], result
    assert result["focus"]["target_window_active"] is True
    assert result["focus"]["thread_active_window"]["class"] == "GhostFixtureShell"
    assert "note" not in result["focus"]


def test_a_grid_in_a_floating_window_that_checks_the_active_window_ignores_the_click():
    """The two-grids report, reproduced: same flag on both grids, the one
    in the shell selects, the one in the floating window does not, and the
    result says which window is active instead."""
    proc, handles = start("--floating", "--grid-needs-active")
    try:
        box, session = session_for(handles["pid"])

        in_shell = box.click(session, GRID,
                             at=ROW_1, expect=ROW_1_SELECTED)
        assert in_shell["ok"], in_shell
        assert in_shell["focus"]["target_window_active"] is True

        # A different row, so the expectation cannot be satisfied by the
        # click before it.
        floating = box.click(session, GRID + " within=(class=GhostFixtureFloat)",
                             all_windows=True, at=ROW_2, expect=ROW_2_SELECTED)

        assert not floating["ok"], floating
        assert floating["focus"]["target_window_active"] is False
        assert floating["focus"]["thread_active_window"]["class"] == "GhostFixtureShell"
        assert "await_human" in floating["focus"]["note"]
    finally:
        stop(proc, handles)
