"""The fifth field report (D67): tightening statuses that said ok for nothing.

A click delivered to an inactive window read as success; await_human with
no condition returned instantly and never showed the notice; a region was
dropped when a locator was also passed; expect refused a string; a native
container hid its addressable parts.
"""

import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes

import psutil
import pytest

from ghostdriver.consent import ConsentStore
from ghostdriver.policy import ConsentSource, Tier
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox
from tests.conftest import on_windows

pytestmark = on_windows

GRID = "class=GhostFixtureDataGrid"
FLOAT_GRID = "class=GhostFixtureDataGrid within=(class=GhostFixtureFloat)"
ROW_1 = {"x": 30, "y": 25}
ROW_1_SELECTED = {"locator": 'class=Static text="/last=grid row=1$/"'}


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


# --- 1. an inactive window no longer reads as plain success --------------------------------

def test_a_click_on_an_inactive_window_warns_and_marks_the_verification():
    proc, handles = start("--floating", "--grid-needs-active")
    try:
        box, session = session_for(handles["pid"])

        result = box.click(session, FLOAT_GRID, at=ROW_1, all_windows=True)

        assert result["ok"] is True  # the input was delivered
        assert result["verified"] == "delivered_inactive"
        assert "warning" in result and "not its thread's active window" in result["warning"]
        assert result["focus"]["target_window_active"] is False
    finally:
        stop(proc, handles)


def test_require_active_refuses_rather_than_delivering_into_the_void():
    proc, handles = start("--floating", "--grid-needs-active")
    try:
        box, session = session_for(handles["pid"])

        result = box.click(session, FLOAT_GRID, at=ROW_1, all_windows=True,
                           require_active=True)

        assert result["ok"] is False
        assert "require_active" in result["error"]["message"]
        assert "await_human" in result["error"]["message"]
        assert result["focus"]["target_window_active"] is False
    finally:
        stop(proc, handles)


def test_an_active_window_click_is_unchanged(app):
    box, session = session_for(app["pid"])

    result = box.click(session, GRID, at=ROW_1, expect=ROW_1_SELECTED)

    assert result["ok"] and result["verified"] == "effect"
    assert "warning" not in result


# --- 2. await_human requires a condition and can watch for any change ----------------------

def test_await_human_without_a_condition_is_refused(app):
    box, session = session_for(app["pid"])

    result = box.await_human(session, ask="do a thing")

    assert result["ok"] is False
    assert "until_change" in result["error"]["message"]


def test_await_human_until_change_returns_when_the_surface_moves():
    """A modal appears 300ms in; until_change watches the surface digest and
    returns when it moves, without a locator named ahead of time."""
    proc, handles = start("--onscreen", "--modal-after", "500")
    try:
        box, session = session_for(handles["pid"])

        result = box.await_human(session, ask="wait for the dialog",
                                 until_change=True, all_windows=True,
                                 timeout_s=8, notice=False)

        assert result["ok"] is True and result["verified"] is True
        assert "surface shape changed" in result["expected"]
    finally:
        stop(proc, handles)


def test_await_human_accepts_a_locator_string_for_until(app):
    box, session = session_for(app["pid"])

    result = box.await_human(session, ask="already true",
                             until="class=GhostFixtureShell", timeout_s=3, notice=False)

    assert result["ok"] is True and result["verified"] is True


# --- 3. region and locator together --------------------------------------------------------

def test_capture_honours_a_region_when_a_locator_is_also_given(app):
    box, session = session_for(app["pid"])
    shell = box.find(session, "class=GhostFixtureShell")["elements"][0]["rect"]
    region = {"left": shell["left"] + 4, "top": shell["top"] + 4,
              "right": shell["left"] + 60, "bottom": shell["top"] + 60}

    shot = box.capture(session, locator="class=GhostFixtureShell", region=region)

    assert shot["ok"], shot
    assert shot["width"] <= 60 and shot["height"] <= 60, "cropped, not the whole window"


# --- 4. expect accepts a string ------------------------------------------------------------

def test_click_expect_accepts_a_locator_string(app):
    box, session = session_for(app["pid"])

    # Clicking the grid sets the status label; name it as a bare string.
    result = box.click(session, GRID, at=ROW_1,
                       expect='class=Static text="/last=grid row=1$/"')

    assert result["ok"] and result["verified"] == "effect"


# --- 5. a native container's addressable parts, and a miss made visible --------------------

def test_hit_targets_lists_the_child_windows_of_a_container(app):
    box, session = session_for(app["pid"])
    page = f"handle=0x{app['pages'][0]:08X}"

    targets = box.hit_targets(session, page)

    assert targets["ok"], targets
    classes = [t["class"] for t in targets["hit_targets"]]
    assert classes.count(app["button_class"]) == 2  # Apply and Reset
    assert all("rect" in t for t in targets["hit_targets"])



def _post_later(hwnd):
    from ghostdriver.backends.windows.notice import later_rect
    left, top, right, bottom = later_rect(hwnd)
    x, y = (left + right) // 2, (top + bottom) // 2
    ctypes.windll.user32.PostMessageW(wintypes.HWND(hwnd), 0x0202, 0, (y << 16) | (x & 0xFFFF))
