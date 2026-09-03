"""What a real session's report changed, each proven on the fixture.

The report (D63): capture of a modal returned the pixels underneath it,
silently; an address field dropped typed characters and nothing could
deliver the value whole; ctrl+ combinations could not be sent; and three
tools that existed were never found because nothing named them at the
moment of need.
"""

import json
import subprocess
import sys
import time

import psutil
import pytest

from ghostdriver.model.locator import Locator
from ghostdriver.policy import ConsentSource, Tier
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox
from tests.conftest import on_windows

pytestmark = on_windows


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


@pytest.fixture
def held_app():
    """A target with its own modal up: raised at 300ms, on screen (the modal
    is shown no-activate), holding the main window."""
    proc, handles = start("--onscreen", "--modal-after", "300")
    time.sleep(0.8)
    yield handles
    stop(proc, handles)


def session_for(pid, tier=Tier.INTERACTIVE):
    box = Toolbox(SessionManager())
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    return box, box.sessions.attach(pid, command_line=["fixtureapp"], tier=tier).session_id


# --- 1. capture renders the window that holds the match ---------------------------

def test_capturing_a_modal_renders_the_modal_not_the_window_beneath(held_app):
    """The silent failure: naming the modal used to crop the main window to
    the modal's rectangle -- the pixels underneath, returned with confidence."""
    box, session = session_for(held_app["pid"])

    shot = box.capture(session, locator="class=GhostFixtureModal")

    assert shot["ok"], shot
    assert shot["rendered"]["class"] == "GhostFixtureModal"
    assert shot["frame"] == "screen"
    assert shot["width"] <= 320 and shot["height"] <= 160, "the modal's size, not the shell's"


def test_a_region_copied_from_find_renders_the_window_it_lies_in(held_app):
    box, session = session_for(held_app["pid"])
    modal = box.find(session, "class=GhostFixtureModal", all_windows=True)["elements"][0]
    assert modal["pid"] == held_app["pid"]

    shot = box.capture(session, region=modal["rect"])

    assert shot["ok"], shot
    assert shot["rendered"]["class"] == "GhostFixtureModal"


def test_a_region_overlapping_no_window_is_refused_with_the_frame_named(app):
    box, session = session_for(app["pid"])

    shot = box.capture(session, region={"left": -50000, "top": -50000,
                                        "right": -49990, "bottom": -49990})

    assert not shot["ok"]
    assert "screen coordinates" in shot["error"]["message"]


def test_find_says_its_frame(app):
    box, session = session_for(app["pid"])

    assert box.find(session, "class=Static")["frame"] == "screen"


# --- 2. a value can be delivered whole -----------------------------------------------

def test_paste_delivers_the_whole_value_and_restores_the_clipboard(app):
    from ghostdriver.backends.windows.grid import read_clipboard_text, write_clipboard_text
    from ghostdriver.backends.windows.input import paste_text
    from ghostdriver.backends.windows.text import read_window_text

    write_clipboard_text("what was there before")
    try:
        assert paste_text(app["plain_edit"], "PASTED-WHOLE-0001")
        time.sleep(0.2)

        assert read_window_text(app["plain_edit"]) == "PASTED-WHOLE-0001"
        assert read_clipboard_text() == "what was there before"
    finally:
        write_clipboard_text("")


def test_set_value_names_the_route_that_delivered(app):
    box, session = session_for(app["pid"])

    result = box.set_value(session, "class=GhostFixturePlainEdit", "typed-fine")

    assert result["ok"], result
    assert result["route"] == "typed", "typing worked, so the paste rung never ran"
    assert result["tier_used"] == 3


def test_a_mismatch_says_what_to_do_next(app):
    """The fixture's plain edit takes at most 20 characters, so a longer
    value comes back short from typing -- and from pasting, which the field
    limits the same way. The failure names the next steps."""
    box, session = session_for(app["pid"])

    result = box.set_value(session, "class=GhostFixturePlainEdit", "x" * 40)

    assert not result["ok"]
    assert "record_input_sensitivity" in result["error"]["message"]
    assert "pasting" in result["error"]["message"]


# --- 4. editing actions in place of modifiers ----------------------------------------

def test_send_keys_select_all_and_paste_are_the_messages_ctrl_a_and_ctrl_v_become(app):
    from ghostdriver.backends.windows.grid import write_clipboard_text

    box, session = session_for(app["pid"])
    write_clipboard_text("from-the-clipboard")
    try:
        result = box.send_keys(session, "class=GhostFixturePlainEdit",
                               ["select-all", "paste"],
                               expect={"locator": "class=GhostFixturePlainEdit",
                                       "text": "from-the-clipboard"})
        assert result["ok"], result
    finally:
        write_clipboard_text("")


def test_a_ctrl_combination_is_refused_with_the_alternative_named(app):
    box, session = session_for(app["pid"])

    result = box.send_keys(session, "class=GhostFixturePlainEdit", ["ctrl+v"])

    assert not result["ok"]
    message = result["error"]["message"]
    assert "modifier state" in message and "paste" in message


# --- 5. the tool that helps is named at the moment of need ---------------------------

def test_a_blocked_target_names_modals_and_await_human(held_app):
    box, session = session_for(held_app["pid"])

    described = box.describe(session)

    assert described["blocked"], described
    assert "modals" in described["blocked_hint"] and "await_human" in described["blocked_hint"]


def test_a_pixels_only_region_names_probe_grid_and_the_point_click(app):
    box, session = session_for(app["pid"])

    surfaces = box.surfaces(session)

    grids = [r for r in surfaces["regions_needing_another_mechanism"]
             if r["class"] == "GhostFixtureDataGrid"]
    assert grids, surfaces
    assert "probe_grid" in grids[0]["hint"] and "at={x, y}" in grids[0]["hint"]


def test_attach_says_the_target_is_minimized_and_names_restore(app):
    from ghostdriver.backends.windows import winapi

    winapi.minimize_no_activate(app["main"])
    time.sleep(0.3)
    box = Toolbox(SessionManager())
    box.sessions.record_grant(app["pid"], allowed=True, source=ConsentSource.ELICITED)

    attached = box.attach(app["pid"])

    assert attached["ok"]
    assert attached.get("minimized_or_hidden") is True
    assert "restore" in attached["hint"]


# --- 6 and 7. the messages that cost a round trip -----------------------------------

def test_an_unquoted_regex_with_spaces_is_told_how_to_quote():
    with pytest.raises(ValueError, match="must be quoted"):
        Locator.parse("text=/.*Release Packages.*/")


def test_consent_required_mentions_that_a_restart_forgets(app):
    box = Toolbox(SessionManager())

    result = box.attach(app["pid"])

    assert result["needs_consent"] and "restarted" in result["error"]["message"]
