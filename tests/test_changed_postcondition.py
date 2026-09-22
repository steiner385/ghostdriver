"""A click can name the surface changing as its postcondition (D77).

Some controls publish no window-level effect to name -- an owner-drawn
toggle bar whose click docks a palette a few seconds later. `expect={
"changed": true}` verifies against the surface shape digest instead, and
tells "delivered and something changed" from "delivered and nothing did".

And the delivered_inactive warning is suppressed when the click's own
disturbances show a window appeared or vanished: that is the click
plainly having acted, so the caveat would be noise.
"""

import json
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
MENU = "class=#32768"


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
    proc, handles = start("--onscreen")
    yield handles
    stop(proc, handles)


def session_for(pid):
    box = Toolbox(SessionManager(store=ConsentStore(None)))
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    return box, box.sessions.attach(pid, command_line=["fixtureapp"],
                                    tier=Tier.INTERACTIVE).session_id


def test_a_right_click_that_opens_a_menu_is_verified_by_the_surface_changing(app):
    """The context menu is a new top-level of a class not there before, so
    the shape digest moves -- an effect with no single control to name."""
    box, session = session_for(app["pid"])

    result = box.click(session, GRID, button="right", at={"x": 40, "y": 25},
                       all_windows=True,
                       expect={"changed": True, "all_windows": True, "timeout_s": 4})

    assert result["ok"] and result["verified"] == "effect", result
    assert "surface changed" in result["expected"]


def test_a_click_that_changes_no_shape_is_not_verified_as_changed(app):
    """A left click on a grid row moves only a status caption; the shape
    digest is blind to text, so 'changed' does not hold -- the honest
    'delivered, nothing docked' the report needed."""
    box, session = session_for(app["pid"])

    result = box.click(session, GRID, at={"x": 40, "y": 25},
                       expect={"changed": True, "timeout_s": 2})

    assert not result["ok"], result
    assert result["verified"] != "effect"
    assert result["error"]["kind"] in ("postcondition_failed", "not_verified", "timeout")


def test_the_inactive_warning_is_suppressed_when_a_window_vanishes(app):
    """Clicking the modal dismisses it; the click's disturbances show the
    window gone, so the delivered_inactive caveat is not added (D77)."""
    import ctypes
    from ctypes import wintypes

    from tests.fixtureapp import WM_FIXTURE_RAISE_MODAL

    box, session = session_for(app["pid"])
    ctypes.windll.user32.PostMessageW(wintypes.HWND(app["main"]),
                                      WM_FIXTURE_RAISE_MODAL, 0, 0)
    time.sleep(0.6)
    assert box.modals(session)["blocked"], "the modal should be up"

    result = box.click(session, "class=GhostFixtureModal", all_windows=True)

    assert result["ok"], result
    kinds = {d["change"] for d in result["disturbances"]}
    assert "window_disappeared" in kinds, result["disturbances"]
    assert "warning" not in result, "a click that closed a window is not 'maybe ignored'"


def test_a_dialog_that_appears_counts_as_changed(app):
    """A click that raises a dialog did something. The digest is blind to a
    new top-level window, so {changed: true} used to read as a flat miss
    while disturbances said window_appeared (#194)."""
    import ctypes
    import threading
    from ctypes import wintypes

    from tests.fixtureapp import WM_FIXTURE_RAISE_MODAL

    box, session = session_for(app["pid"])

    def raise_the_modal_shortly():
        time.sleep(0.5)
        ctypes.windll.user32.PostMessageW(wintypes.HWND(app["main"]),
                                          WM_FIXTURE_RAISE_MODAL, 0, 0)

    threading.Thread(target=raise_the_modal_shortly, daemon=True).start()
    result = box.click(session, GRID, at={"x": 40, "y": 25},
                       expect={"changed": True, "timeout_s": 4})

    assert result["ok"] and result["verified"] == "effect", result
    assert any(d["change"] == "window_appeared" for d in result["disturbances"]), result["disturbances"]
