"""`at` is pixels from the window's top-left as find reports it and a capture
shows -- on a top-level window with a frame too (#203)."""

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

SHELL = "class=GhostFixtureShell"
GRID = "class=GhostFixtureDataGrid"


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
def session(app):
    box = Toolbox(SessionManager())
    box.sessions.record_grant(app["pid"], allowed=True, source=ConsentSource.ELICITED)
    sid = box.sessions.attach(app["pid"], command_line=["fixtureapp"],
                              tier=Tier.INTERACTIVE).session_id
    return box, sid


def test_a_framed_window_s_client_area_starts_inside_its_rect(app):
    from ghostdriver.backends.windows.input import client_offset, client_point

    dx, dy = client_offset(app["main"])
    assert dy > dx >= 0, "a title bar is taller than a border"
    assert client_point(app["main"], (100, 100)) == (100 - dx, 100 - dy)


def test_a_child_control_has_no_offset(session):
    from ghostdriver.backends.windows.input import client_offset

    box, sid = session
    grid = int(box.find(sid, GRID)["elements"][0]["handle_ephemeral"], 16)
    assert client_offset(grid) == (0, 0)


def test_at_measured_on_the_shell_lands_where_the_shell_s_capture_shows(session):
    """The grid's row 1, aimed through the shell: at is the grid's position
    in the shell's own rect plus the row offset, exactly as a capture of the
    shell would show it. Before #203 this landed a title bar too high."""
    box, sid = session
    shell = box.find(sid, SHELL)["elements"][0]["rect"]
    grid = box.find(sid, GRID)["elements"][0]["rect"]
    at = {"x": grid["left"] - shell["left"] + 30, "y": grid["top"] - shell["top"] + 25}

    result = box.click(sid, SHELL, at=at,
                       expect={"locator": 'class=Static text="/last=grid row=1/"'})

    assert result["ok"] and result["verified"] == "effect", result
    assert result["delivered_to"]["class"] == "GhostFixtureDataGrid"
