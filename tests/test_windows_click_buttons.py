"""Right and middle buttons, and modifiers, on a click.

The case that asked for this: a Ctrl+right-click on a status bar opens a
menu, and the tool could only post a plain left pair, so the step went to
a person. A posted mouse message carries its button in the message id and
its modifiers in its flags -- the only place a posted message can carry
them. The fixture records what its window procedure saw, so a test can
tell that a posted Ctrl+right-click arrived as one.
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
def session(app):
    box = Toolbox(SessionManager())
    box.sessions.record_grant(app["pid"], allowed=True, source=ConsentSource.ELICITED)
    sid = box.sessions.attach(app["pid"], command_line=["fixtureapp"],
                              tier=Tier.INTERACTIVE).session_id
    return box, sid


EXPAND = 'class=GhostFixtureCommandButton text="Expand All"'


def test_a_plain_click_reads_exactly_as_before(session):
    box, sid = session

    result = box.click(sid, EXPAND,
                       expect={"locator": 'class=Static text="/clicks=1 last=Expand All$/"'})

    assert result["ok"], result
    assert result["button"] == "left" and result["modifiers"] == []


def test_a_right_click_arrives_as_one(session):
    box, sid = session

    result = box.click(sid, EXPAND, button="right",
                       expect={"locator": 'class=Static text="/button=right mods=none/"'})

    assert result["ok"], result
    assert result["tier_used"] == 3, "no pattern can right-click"
    assert result["tiers_attempted"] == [3]


def test_a_ctrl_right_click_carries_its_modifier_in_the_message(session):
    """What a VCL control reads its shift state from, so on the primary
    target this is the Ctrl+right-click that opens its status-bar menu."""
    box, sid = session

    result = box.click(sid, EXPAND, button="right", modifiers=["ctrl"],
                       expect={"locator": 'class=Static text="/button=right mods=ctrl$/"'})

    assert result["ok"], result
    assert result["modifiers"] == ["ctrl"]


def test_shift_and_ctrl_together(session):
    box, sid = session

    result = box.click(sid, EXPAND, button="middle", modifiers=["shift", "ctrl"],
                       expect={"locator": 'class=Static text="/button=middle mods=ctrl\\+shift/"'})

    assert result["ok"], result


def test_an_unknown_button_or_modifier_is_refused_by_name(session):
    box, sid = session

    bad_button = box.click(sid, EXPAND, button="back")
    bad_modifier = box.click(sid, EXPAND, modifiers=["alt"])

    assert not bad_button["ok"] and "back" in bad_button["error"]["message"]
    assert not bad_modifier["ok"] and "alt" in bad_modifier["error"]["message"]


def test_a_posted_pair_of_one_button_does_not_complete_another(app):
    """The fixture presses on down and clicks on the matching up: a right
    down followed by a left up is not a click of either."""
    from ghostdriver.backends.windows import input as win_input
    from ghostdriver.backends.windows.enumerate import enumerate_process
    from ghostdriver.backends.windows.text import read_window_text
    from ghostdriver.model.window import select_main_tree

    tree = select_main_tree(enumerate_process(app["pid"]))
    button = next(n for n in tree.walk() if n.text == "Expand All")
    status = next(n for n in tree.walk() if (n.text or "").startswith("clicks="))
    down_msg, _, down_flags, _ = win_input.button_pair("right")
    _, up_msg, _, up_flags = win_input.button_pair("left")
    x, y = win_input.client_centre(button.handle)
    point = win_input._lparam_for_point(x, y)
    win_input.user32.PostMessageW(button.handle, win_input.WM_MOUSEMOVE, 0, point)
    win_input.user32.PostMessageW(button.handle, down_msg, down_flags, point)
    win_input.user32.PostMessageW(button.handle, up_msg, up_flags, point)
    time.sleep(0.3)

    assert read_window_text(status.handle) == "clicks=0 last="


def test_a_pair_with_no_move_in_front_of_it_is_not_a_click(app):
    """A person's pointer arrives before their button goes down, and a
    toolkit sets its hot state from that arrival; the glow buttons on the
    primary target gate their click on it. The fixture gates the same way,
    so this is the difference between the bare pair the tool used to post
    and what it posts now (D#69)."""
    from ghostdriver.backends.windows import input as win_input
    from ghostdriver.backends.windows.enumerate import enumerate_process
    from ghostdriver.backends.windows.text import read_window_text
    from ghostdriver.model.window import select_main_tree

    tree = select_main_tree(enumerate_process(app["pid"]))
    button = next(n for n in tree.walk() if n.text == "Expand All")
    status = next(n for n in tree.walk() if (n.text or "").startswith("clicks="))
    down_msg, up_msg, down_flags, up_flags = win_input.button_pair("left")
    x, y = win_input.client_centre(button.handle)
    point = win_input._lparam_for_point(x, y)

    win_input.user32.PostMessageW(button.handle, down_msg, down_flags, point)
    win_input.user32.PostMessageW(button.handle, up_msg, up_flags, point)
    time.sleep(0.3)
    assert read_window_text(status.handle) == "clicks=0 last=", "bare pair: no click"

    assert win_input.click(button.handle)
    time.sleep(0.3)
    assert read_window_text(status.handle) == "clicks=1 last=Expand All",         "the move the tool posts first is what makes it a click"


# --- a point inside the element, and a double-click --------------------------------

GRID = "class=GhostFixtureDataGrid"


def test_a_click_at_a_point_reaches_a_row_the_grid_will_not_name(session):
    """The painted grid exposes no rows; a capture says where row 2 is
    (rows are 20px from y=4), and the click lands there. Still posted."""
    box, sid = session

    result = box.click(sid, GRID, at={"x": 30, "y": 4 + 2 * 20 + 8},
                       expect={"locator": 'class=Static text="/last=grid row=2$/"'})

    assert result["ok"], result
    assert result["at"] == (30, 52) or result["at"] == [30, 52]
    assert result["tier_used"] == 3


def test_a_double_click_is_the_double_click_message(session):
    box, sid = session

    result = box.click(sid, GRID, at={"x": 30, "y": 4 + 1 * 20 + 8}, count=2,
                       expect={"locator": 'class=Static text="/clicks=2 last=grid row=1 double/"'})

    assert result["ok"], result
    assert result["count"] == 2


def test_a_point_outside_the_element_is_refused_before_anything_is_sent(session):
    box, sid = session

    result = box.click(sid, GRID, at={"x": 5000, "y": 5})

    assert not result["ok"]
    assert result["error"]["kind"] == "not_actionable"
    assert "outside" in result["error"]["message"]
    assert box.read(sid, 'class=Static text="/clicks=/"')["values"][0]["text"] == "clicks=0 last="


def test_a_bad_count_is_refused(session):
    box, sid = session

    result = box.click(sid, EXPAND, count=3)

    assert not result["ok"] and "count" in result["error"]["message"]
