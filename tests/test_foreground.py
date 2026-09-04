"""Bringing a window forward on request (D73), and the frame/telemetry
polish from the same report.

`foreground` is the one tool that deliberately interrupts the operator, so
its real activation is exercised only when GHOSTDRIVER_TEST_FOREGROUND is
set; the rest stubs the backend call, so the suite never steals focus.
"""

import json
import os
import subprocess
import sys
import time

import psutil
import pytest

from ghostdriver.consent import ConsentStore
from ghostdriver.policy import ConsentSource, Tier
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox
from tests.conftest import on_windows

pytestmark = on_windows

GRID = "class=GhostFixtureDataGrid"


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
    box = Toolbox(SessionManager(store=ConsentStore(None)))
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    return box, box.sessions.attach(pid, command_line=["fixtureapp"], tier=tier).session_id


def stub_raise(monkeypatch, took):
    """Replace the real activation so the test never steals focus."""
    from ghostdriver.backends.windows import winapi

    calls = []

    def fake(hwnd):
        calls.append(hwnd)
        return took

    monkeypatch.setattr(winapi, "bring_foreground", fake)
    return calls


def test_foreground_reports_taking_the_front_and_warns(app, monkeypatch):
    calls = stub_raise(monkeypatch, took=True)
    box, session = session_for(app["pid"])

    result = box.foreground(session)

    assert result["ok"] and result["took_foreground"] is True
    assert calls == [app["main"]], "it raised the main window"
    assert "keyboard focus" in result["warning"] and "note" not in result


def test_foreground_is_honest_when_windows_refuses(app, monkeypatch):
    stub_raise(monkeypatch, took=False)
    box, session = session_for(app["pid"])

    result = box.foreground(session)

    assert result["ok"] and result["took_foreground"] is False
    assert "refused the foreground" in result["note"]


def test_foreground_can_name_a_window(app, monkeypatch):
    calls = stub_raise(monkeypatch, took=True)
    box, session = session_for(app["pid"])

    result = box.foreground(session, locator="class=GhostFixtureShell")

    assert result["ok"] and calls == [app["main"]]
    assert result["window"]["class"] == "GhostFixtureShell"


def test_foreground_needs_the_interactive_tier(app, monkeypatch):
    stub_raise(monkeypatch, took=True)
    box, session = session_for(app["pid"], tier=Tier.READ_ONLY)

    result = box.foreground(session)

    assert not result["ok"] and "interactive" in result["error"]["message"]


@pytest.mark.slow
@pytest.mark.skipif(not os.environ.get("GHOSTDRIVER_TEST_FOREGROUND"),
                    reason="really steals focus; opt in with GHOSTDRIVER_TEST_FOREGROUND=1")
def test_foreground_really_brings_the_window_forward(monkeypatch):
    from ghostdriver.backends.windows import winapi

    proc, handles = start("--onscreen")
    box, session = session_for(handles["pid"])
    try:
        result = box.foreground(session)
        time.sleep(0.3)
        assert result["ok"]
        if result["took_foreground"]:
            assert winapi.window_pid(winapi.foreground_window()) == handles["pid"]
    finally:
        for sid in list(box._watches):
            box.release(sid)
        stop(proc, handles)


# --- physical_rect on find and capture (D73) ------------------------------------------

def test_find_carries_a_physical_rect_when_the_display_is_scaled(app):
    from ghostdriver.backends.windows import winapi

    box, session = session_for(app["pid"])
    found = box.find(session, "class=GhostFixtureShell")["elements"][0]
    scale = winapi.display_scale()

    if scale == 1.0:
        assert "physical_rect" not in found
    else:
        phys = found["physical_rect"]
        assert phys["scale"] == scale
        assert phys["left"] == round(found["rect"]["left"] * scale)


# --- modals returns the dialog's whole text (D73) --------------------------------------

def test_dialog_text_reads_child_controls_top_to_bottom(app):
    from ghostdriver.tools.status import _dialog_text

    _box, _session = session_for(app["pid"])  # keeps the target process alive

    text = _dialog_text(app["main"])

    assert "plain text" in text  # a Static caption in the shell
    assert "Expand All" in text


# --- grant_targets summarises instead of dumping every pid (D73) -----------------------

def test_grant_targets_reports_counts_not_a_wall_of_pids(app):
    box, _ = session_for(app["pid"])

    out = box.grant_targets(allow=[app["pid"], 999001, 999002])

    assert out["allowed_count"] >= 3
    assert "allowed" not in out, "the full allowed list is a count now"
    assert len(out["recorded"]) == 3, "what changed is still named in full"
